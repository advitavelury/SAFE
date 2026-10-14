import { useEffect, useRef, useState } from "react";
import { Camera, Square, RefreshCw } from "lucide-react";
import { useStaffSession } from "../api/StaffSession.jsx";
import { streamVideoFeed } from "../api/videoFeed.js";

export default function LiveCameraStage({ className = "" }) {
  const { user } = useStaffSession() ?? {};
  const canvas = useRef(null);
  const [enabled, setEnabled] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState({ status: "connecting", message: "Connecting to video feed..." });

  useEffect(() => {
    const controller = new AbortController();
    const surface = canvas.current;
    const clearFrame = () => surface?.getContext("2d").clearRect(0, 0, surface.width, surface.height);
    clearFrame();
    if (!enabled) {
      setState({ status: "disconnected", message: "Viewer disconnected." });
      return;
    }
    setState({ status: "connecting", message: "Connecting to video feed..." });
    streamVideoFeed(user, {
      signal: controller.signal,
      onFrame: async blob => {
        let bitmap;
        try {
          bitmap = await createImageBitmap(blob);
        } catch {
          throw new Error("Unable to decode the backend video frame.");
        }
        try {
          if (controller.signal.aborted || !surface) return;
          if (surface.width !== bitmap.width) surface.width = bitmap.width;
          if (surface.height !== bitmap.height) surface.height = bitmap.height;
          surface.getContext("2d").drawImage(bitmap, 0, 0);
          setState(previous => previous.status === "connected" ? previous : { status: "connected" });
        } finally { bitmap.close(); }
      },
    }).catch(error => {
      if (controller.signal.aborted) return;
      clearFrame();
      setState({ status: "offline", message: error.message });
    });
    return () => { controller.abort(); clearFrame(); };
  }, [user, enabled, attempt]);

  const connected = state.status === "connected";
  const active = enabled && ["connected", "connecting"].includes(state.status);
  return (
    <div className={`relative overflow-hidden rounded-lg bg-neutral-900 text-white ${className}`}>
      <canvas ref={canvas} role="img" aria-label="Annotated video from the local detection backend"
        className={`absolute inset-0 h-full w-full object-contain ${connected ? "" : "invisible"}`} />
      {!connected && <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-5 pb-14 pt-3 text-center">
        <Camera size={28} className="shrink-0 text-gray-400" />
        <p role="status" className="text-sm">{state.message}</p>
      </div>}
      {connected && <span role="status" className="absolute left-3 top-3 rounded bg-black/70 px-2 py-1 text-xs font-semibold">VIDEO FEED</span>}
      <div className="absolute bottom-3 right-3 flex gap-2">
        {active ? <button title="Disconnect viewer" aria-label="Disconnect viewer" onClick={() => setEnabled(false)}
          className="flex h-10 w-10 items-center justify-center rounded-md bg-neutral-700"><Square size={18} /></button>
          : <button title="Reconnect video feed" aria-label="Reconnect video feed" onClick={() => { setEnabled(true); setAttempt(n => n + 1); }}
            className="flex h-10 w-10 items-center justify-center rounded-md bg-neutral-700"><RefreshCw size={18} /></button>}
      </div>
    </div>
  );
}
