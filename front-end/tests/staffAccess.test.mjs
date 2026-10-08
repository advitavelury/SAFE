import assert from "node:assert/strict";
import { test } from "node:test";
import { isApprovedStaff, staffAccessErrorMessage, watchStaffAccess } from "../src/api/staffAccess.js";

const user = { uid: "staff-1", isAnonymous: false };
const admin = { active: true, role: "admin" };

test("only active staff with an explicit supported role are approved", () => {
  for (const role of ["admin", "operator"]) {
    assert.equal(isApprovedStaff(user, { active: true, role }), true);
  }
  for (const profile of [null, {}, { ...admin, active: false },
    { ...admin, active: "true" }, { ...admin, role: "visitor" }]) {
    assert.equal(isApprovedStaff(user, profile), false);
  }
  assert.equal(isApprovedStaff(null, admin), false);
  assert.equal(isApprovedStaff({ ...user, isAnonymous: true }, admin), false);
});

function harness() {
  const events = [];
  const subscriptions = [];
  let authNext;
  let authError;
  let authStopped = false;
  const stop = watchStaffAccess({
    watchAuth(next, error) {
      authNext = next;
      authError = error;
      return () => { authStopped = true; };
    },
    watchProfile(uid, next, error) {
      const sub = { uid, next, error, stopped: false };
      subscriptions.push(sub);
      return () => { sub.stopped = true; };
    },
  }, (event) => events.push(event));
  return { events, subscriptions, stop,
    login: (value) => authNext(value), failAuth: (error) => authError(error),
    isAuthStopped: () => authStopped };
}

test("approval needs a server response and revocation removes access", () => {
  const h = harness();
  h.login(user);
  h.subscriptions[0].next(admin, true);
  assert.equal(h.events.at(-1).status, "checking");
  h.subscriptions[0].next(admin, false);
  assert.equal(h.events.at(-1).status, "ready");
  h.subscriptions[0].next({ ...admin, active: false }, false);
  assert.equal(h.events.at(-1).status, "denied");
  h.subscriptions[0].error();
  assert.equal(h.events.at(-1).status, "error");
});

test("sign-out and account switching ignore old profile responses", () => {
  const h = harness();
  h.login(user);
  const first = h.subscriptions[0];
  h.login(null);
  first.next(admin, false);
  assert.equal(first.stopped, true);
  assert.equal(h.events.at(-1).status, "signed-out");
  h.login({ ...user, uid: "staff-2" });
  first.next(admin, false);
  assert.equal(h.events.at(-1).status, "checking");
  h.subscriptions[1].next(null, false);
  assert.equal(h.events.at(-1).status, "denied");
  h.stop();
  const count = h.events.length;
  h.subscriptions[1].next(admin, false);
  assert.equal(h.events.length, count);
  assert.equal(h.subscriptions[1].stopped, true);
  assert.equal(h.isAuthStopped(), true);
});

test("anonymous users never subscribe to profiles", () => {
  const h = harness();
  h.login({ ...user, isAnonymous: true });
  assert.equal(h.subscriptions.length, 0);
  assert.equal(h.events.at(-1).status, "signed-out");
});

test("auth errors invalidate any outstanding approval", () => {
  const h = harness();
  h.login(user);
  h.failAuth();
  h.subscriptions[0].next(admin, false);
  assert.equal(h.events.at(-1).status, "error");
  assert.equal(h.subscriptions[0].stopped, true);
});

test("profile errors distinguish permissions from connectivity without granting access", () => {
  for (const code of ["permission-denied", "unavailable", "unauthenticated", "failed-precondition"]) {
    const h = harness();
    h.login(user);
    h.subscriptions[0].next(admin, false);
    h.subscriptions[0].error({ code, message: "Private service details" });
    assert.deepEqual(h.events.at(-1), { status: "error", user, errorCode: code });
    assert.ok(staffAccessErrorMessage(code).includes(`(${code})`));
    assert.ok(!staffAccessErrorMessage(code).includes("Private service details"));
  }
  assert.match(staffAccessErrorMessage("permission-denied"), /access rules/);
  assert.match(staffAccessErrorMessage("unavailable"), /connection/);
});

test("unknown errors retain the generic message without exposing raw details", () => {
  const h = harness();
  h.login(user);
  h.subscriptions[0].error({ code: "Private service details", message: "Secret" });
  assert.deepEqual(h.events.at(-1), { status: "error", user, errorCode: "unknown" });
  for (const code of [undefined, "unknown", "constructor", "__proto__"]) {
    assert.equal(staffAccessErrorMessage(code), "Check your connection or contact your administrator.");
  }
});

test("auth error diagnostics discard the prior profile and ignore stale profile errors", () => {
  const h = harness();
  h.login(user);
  h.subscriptions[0].next(admin, false);
  h.failAuth({ code: "auth/network-request-failed" });
  const error = h.events.at(-1);
  assert.deepEqual(error, { status: "error", user: null, errorCode: "auth/network-request-failed" });
  assert.match(staffAccessErrorMessage(error.errorCode), /connection/);
  h.subscriptions[0].error({ code: "permission-denied" });
  assert.equal(h.events.at(-1), error);
});
