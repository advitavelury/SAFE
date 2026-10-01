import { initializeApp } from "firebase/app";
import { getAuth, browserSessionPersistence, setPersistence, signInWithEmailAndPassword } from "firebase/auth";
import { getFirestore } from "firebase/firestore";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

export const firebaseConfigured = Object.values(firebaseConfig).every(Boolean);

const app = firebaseConfigured ? initializeApp(firebaseConfig) : null;

export const db = app ? getFirestore(app) : null;
export const auth = app ? getAuth(app) : null;

export async function signInStaff(email, password) {
  if (!auth) throw new Error("Firebase is not configured.");
  await setPersistence(auth, browserSessionPersistence);
  return signInWithEmailAndPassword(auth, email.trim(), password);
}

export const INCIDENTS_COLLECTION =
  import.meta.env.VITE_FIREBASE_INCIDENTS_COLLECTION || "incidents";
