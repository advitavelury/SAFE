import { useEffect, useRef, useState } from "react";
import { Camera, Square, RefreshCw } from "lucide-react";
import { auth } from "../api/firebase.js";
import { useStaffSession } from "../api/StaffSession.jsx";
import { canEditIncidents } from "../api/staffAccess.js";
import { mediaServiceEnabled, mediaServiceUrl } from "../api/mediaService.js";

async function cameraRequest(path, options = {}) {
  if (!auth?.currentUser) throw new Error("Staff sign-in required.");
  const token = await auth.currentUser.getIdToken();
  const response = await fetch(mediaServiceUrl(`/api/camera/${path}`), {
    ...options, cache: "no-store", redirect: "error", credentials: "omit", headers: { Authorization: `Bearer ${token}` },
    signal: AbortSignal.any([options.signal, AbortSignal.timeout(5000)].filter(Boolean)),
  });
  if (response.status === 401 || response.status === 403) {
    throw new Error("Camera access denied. Sign in with an approved staff account.");
  }
  return response;
}

export default function LiveCameraStage({ zoneId, className = "" }) {
  const session = useStaffSession();
  const canControl = canEditIncidents(session?.user, session?.profile);
  const [state, setState] = useState({ state: "connecting", message: "Connecting to camera..." });
  const [image, setImage] = useState(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const objectUrl = useRef(null);

  useEffect(() => {
    if (!mediaServiceEnabled) {
      setImage(null);
      setState({ state: "unavailable", message: "Live camera is not connected to this deployment." });
      return;
    }
    const controller = new AbortController();
    let timer;
    let disposed = false;
    setImage(null);
    setState({ state: "connecting", message: "Connecting to camera..." });
    const clearImage = () => {
      setImage(null);
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = null;
    };
    async function poll() {
      let delay = 1000;
      try {
        const statusResponse = await cameraRequest("status", { signal: controller.signal });
        if (!statusResponse.ok) throw new Error("Camera service unavailable.");
        const status = await statusResponse.json();
        if (disposed) return;
        if (status.zoneId !== zoneId) {
          setState({ state: "unassigned", message: "No camera assigned to this zone." });
          clearImage();
          return;
        }
        setState(status);
        if (["running", "starting"].includes(status.state)) {
          const response = await cameraRequest("frame", { signal: controller.signal });
          if (response.ok) {
            const blob = await response.blob();
            if (disposed) return;
            const previous = objectUrl.current;
            objectUrl.current = URL.createObjectURL(blob);
            setImage(objectUrl.current);
            if (previous) URL.revokeObjectURL(previous);
            delay = 200;
          } else {
            clearImage();
            setState({ ...status, state: "starting", message: "Waiting for camera frames..." });
          }
        } else clearImage();
      } catch (error) {
        if (disposed) return;
        clearImage();
        setState({ state: "offline", message: error.message.startsWith("Camera access denied")
          ? error.message : "Camera service unavailable." });
      } finally {
        if (!disposed) timer = setTimeout(poll, delay);
      }
    }
    poll();
    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timer);
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = null;
    };
  }, [zoneId, attempt]);

  async function command(action) {
    if (!canControl || !mediaServiceEnabled) return;
    setBusy(true);
    try {
      const response = await cameraRequest(action, { method: "POST" });
      if (!response.ok) throw new Error("Camera service unavailable.");
      setState(await response.json());
      setAttempt((n) => n + 1);
    } catch (error) {
      setState({ state: "offline", message: error.message });
    } finally { setBusy(false); }
  }
  const active = ["running", "starting"].includes(state.state);
  return (
    <div className={`relative overflow-hidden rounded-lg bg-neutral-900 text-white ${className}`}>
      {image && <img className="absolute inset-0 h-full w-full object-contain" src={image} alt={`Monitored camera for Zone ${zoneId}`} />}
      {!image && <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-5 text-center">
        <Camera size={28} className="text-gray-400" />
        <p role="status" className="text-sm">{!canControl && ["idle", "ended"].includes(state.state) ? "Camera is off. An administrator can start it." : state.message}</p>
      </div>}
      {image && <span className="absolute left-3 top-3 rounded bg-black/70 px-2 py-1 text-xs font-semibold">{state.source === "video" ? "TEST VIDEO" : "LIVE"}</span>}
      {mediaServiceEnabled && state.state !== "unassigned" && <div className="absolute bottom-3 right-3 flex gap-2">
        {canControl && active ? <button title="Stop camera" aria-label="Stop camera" disabled={busy} onClick={() => command("stop")}
          className="flex h-10 w-10 items-center justify-center rounded-md bg-red-700 disabled:opacity-50"><Square size={18} /></button>
          : canControl && ["idle", "ended", "error"].includes(state.state)
            ? <button disabled={busy} onClick={() => command("start")} className="flex items-center gap-2 rounded-md bg-teal-700 px-3 py-2 text-sm font-semibold disabled:opacity-50"><Camera size={18} />Start camera</button>
            : <button title="Reconnect camera" aria-label="Reconnect camera" onClick={() => setAttempt((n) => n + 1)}
              className="flex h-10 w-10 items-center justify-center rounded-md bg-neutral-700"><RefreshCw size={18} /></button>}
      </div>}
    </div>
  );
}
