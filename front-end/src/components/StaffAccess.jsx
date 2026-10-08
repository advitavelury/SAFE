import { useEffect, useState } from "react";
import { onAuthStateChanged, signOut } from "firebase/auth";
import { doc, onSnapshot } from "firebase/firestore";
import { LogIn, LogOut, ShieldCheck } from "lucide-react";
import { auth, db, firebaseConfigured, signInStaff } from "../api/firebase.js";
import { staffAccessErrorMessage, watchStaffAccess } from "../api/staffAccess.js";
import { StaffSession } from "../api/StaffSession.jsx";
import { C, FONT } from "../theme.js";

const buttonStyle = { background: C.tealDeep, color: "white" };

function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await signInStaff(email, password);
      setPassword("");
    } catch (err) {
      const messages = {
        "auth/network-request-failed": "Unable to connect. Check your internet connection and try again.",
        "auth/too-many-requests": "Too many attempts. Please wait before trying again.",
        "auth/operation-not-allowed": "Staff sign-in is unavailable. Contact your administrator.",
      };
      setError(messages[err.code] || "Unable to sign in. Check your email and password.");
      setPassword("");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-5">
      <h2 className="text-xl font-semibold">Staff sign-in</h2>
      <label className="flex flex-col gap-2 text-sm font-medium">
        Email
        <input type="email" name="email" autoComplete="username" required value={email}
          onChange={(e) => setEmail(e.target.value)} disabled={busy}
          className="min-w-0 rounded-md border border-gray-300 bg-white p-3 text-base focus:outline-2 focus:outline-teal-700" />
      </label>
      <label className="flex flex-col gap-2 text-sm font-medium">
        Password
        <input type="password" name="password" autoComplete="current-password" required value={password}
          onChange={(e) => setPassword(e.target.value)} disabled={busy}
          className="min-w-0 rounded-md border border-gray-300 bg-white p-3 text-base focus:outline-2 focus:outline-teal-700" />
      </label>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <button disabled={busy} type="submit" style={buttonStyle}
        className="flex min-h-12 items-center justify-center gap-2 rounded-md px-4 py-3 font-semibold disabled:opacity-60">
        <LogIn size={18} />{busy ? "Signing in..." : "Sign in"}
      </button>
    </form>
  );
}

export default function StaffAccess({ children }) {
  const [session, setSession] = useState({ status: "checking" });
  const [attempt, setAttempt] = useState(0);
  const [logoutError, setLogoutError] = useState("");
  useEffect(() => {
    if (!firebaseConfigured) return;
    setSession({ status: "checking" });
    return watchStaffAccess({
      watchAuth: (next, error) => onAuthStateChanged(auth, next, error),
      watchProfile: (uid, next, error) => onSnapshot(doc(db, "users", uid),
        { includeMetadataChanges: true },
        (snapshot) => next(snapshot.exists() ? snapshot.data() : null, snapshot.metadata.fromCache), error),
    }, setSession);
  }, [attempt]);

  async function logout() {
    setLogoutError("");
    try { await signOut(auth); }
    catch { setLogoutError("Sign-out failed. Please try again."); }
  }

  if (firebaseConfigured && session.status === "ready") {
    return (
      <div style={{ fontFamily: FONT, color: C.ink }}>
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 bg-white px-5 py-3 text-sm">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <ShieldCheck size={18} color={C.tealDeep} />
            <span className="break-all">{session.user.email}</span>
            <span className="capitalize text-gray-600">({session.profile.role})</span>
          </div>
          <button type="button" onClick={logout} className="flex items-center gap-2 rounded-md border border-gray-300 px-3 py-2">
            <LogOut size={16} />Sign out
          </button>
          {logoutError && <p role="alert" className="w-full text-red-700">{logoutError}</p>}
        </header>
        <StaffSession.Provider value={session}>{children}</StaffSession.Provider>
      </div>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-50 px-5 py-10" style={{ fontFamily: FONT, color: C.ink }}>
      <div className="w-full max-w-sm">
        <div className="mb-8 border-b border-gray-200 pb-6">
          <h1 className="text-4xl font-bold" style={{ color: C.tealDeep }}>SAFE</h1>
          <p className="mt-2 text-sm text-gray-600">Smart Assisted Fall and Emergency</p>
        </div>
        {!firebaseConfigured ? <p role="alert">Staff sign-in is not configured. Contact your administrator.</p>
          : session.status === "signed-out" ? <Login />
          : <div className="flex flex-col gap-4">
            <h2 className="text-xl font-semibold">
              {session.status === "checking" ? "Checking staff access..." : session.status === "denied" ? "Access not approved" : "Unable to verify access"}
            </h2>
            <p role="status" className="text-sm text-gray-600">
              {session.status === "checking" ? "Waiting for a connection."
                : session.status === "denied" ? "Your account needs an active staff role. Contact your administrator."
                : staffAccessErrorMessage(session.errorCode)}
            </p>
            <button type="button" onClick={() => setAttempt((n) => n + 1)} className="rounded-md px-4 py-3 font-semibold" style={buttonStyle}>Retry</button>
            {session.user && <button type="button" onClick={logout} className="flex items-center justify-center gap-2 py-2"><LogOut size={16} />Sign out</button>}
            {logoutError && <p role="alert" className="text-sm text-red-700">{logoutError}</p>}
          </div>}
      </div>
    </main>
  );
}
