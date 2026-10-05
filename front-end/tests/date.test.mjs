import { test } from "node:test";
import assert from "node:assert/strict";
import { iso } from "../src/utils/date.js";

test("incident dates and calendar cells use the same local day", () => {
  process.env.TZ = "Australia/Melbourne";
  const incident = new Date("2026-10-01T03:47:16Z");
  assert.equal(iso(incident), "2026-10-01");
  assert.equal(iso(new Date(2026, 9, 1)), iso(incident));
});

test("local date remains correct near midnight and daylight saving", () => {
  process.env.TZ = "Australia/Melbourne";
  assert.equal(iso(new Date("2026-09-30T14:05:00Z")), "2026-10-01");
  assert.equal(iso(new Date("2026-10-04T13:05:00Z")), "2026-10-05");
});
