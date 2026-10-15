import { useEffect, useRef, useState } from "react";
import { Camera, Film, Play, Square, RotateCcw, RefreshCw } from "lucide-react";
import { useStaffSession } from "../api/StaffSession.jsx";
import { streamVideoFeed } from "../api/videoFeed.js";
import { getVideoSource, selectVideoSource, stopVideoSource } from "../api/videoSource.js";

export default function LiveCameraStage({ className = "" }) {
  const { user } = useStaffSession() ?? {};
  const canvas = useRef(null);
  const action = useRef(null);
  const epoch = useRef(0);
  const [source, setSource] = useState(null);
  const [selected, setSelected] = useState("video");
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [stream, setStream] = useState({ status: "idle" });

  useEffect(() => () => { epoch.current += 1; action.current?.abort(); }, [user]);

  useEffect(() => {
    if (busy) return;
    const controller = new AbortController();
    const version = epoch.current;
    let timer;
    async function poll() {
      try {
        const next = await getVideoSource(user, controller.signal);
        if (controller.signal.aborted || version !== epoch.current) return;
        setSource(next);
        if (next.mode) setSelected(next.mode);
        setError("");
      } catch (failure) {
        if (controller.signal.aborted || version !== epoch.current) return;
        setSource(null);
        setError(failure.message);
      } finally {
        if (!controller.signal.aborted && version === epoch.current) timer = setTimeout(poll, 1000);
      }
    }
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [user, busy, attempt]);

  async function changeSource(mode) {
    epoch.current += 1;
    action.current?.abort();
    const controller = new AbortController();
    action.current = controller;
    setBusy(true);
    setSource(null);
    setError("");
    if (mode) setSelected(mode);
    try {
      const next = mode ? await selectVideoSource(user, mode, controller.signal)
        : await stopVideoSource(user, controller.signal);
      if (!controller.signal.aborted) setSource(next);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure.message);
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  const generation = source?.generation;
  const sourceState = source?.state;
  useEffect(() => {
    const controller = new AbortController();
    const surface = canvas.current;
    const clear = () => surface?.getContext("2d").clearRect(0, 0, surface.width, surface.height);
    clear();
    setStream({ status: "idle" });
    if (sourceState !== "running") return;
    setStream({ status: "connecting" });
    streamVideoFeed(user, {
      generation, signal: controller.signal,
      onFrame: async blob => {
        const bitmap = await createImageBitmap(blob);
        try {
          if (controller.signal.aborted || !surface) return;
          if (surface.width !== bitmap.width) surface.width = bitmap.width;
          if (surface.height !== bitmap.height) surface.height = bitmap.height;
          surface.getContext("2d").drawImage(bitmap, 0, 0);
          setStream(previous => previous.status === "connected" ? previous : { status: "connected" });
        } finally { bitmap.close(); }
      },
    }).catch(failure => {
      if (controller.signal.aborted) return;
      clear();
      setStream({ status: "error", message: failure.message });
    });
    return () => { controller.abort(); clear(); };
  }, [user, generation, sourceState, attempt]);

  const connected = sourceState === "running" && stream.status === "connected" && !busy;
  const active = ["starting", "switching", "running"].includes(sourceState);
  const message = error || (busy ? "Changing source..." : sourceState === "running"
    ? stream.message || "Connecting to detection frames..."
    : source?.message || "Connecting to backend...");
  const iconButton = "flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-neutral-700 disabled:opacity-40";
  return (
    <div className="overflow-hidden rounded-lg bg-neutral-900 text-white">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-neutral-700 p-2">
        <div role="group" aria-label="Detection source" className="flex gap-1">
          {[["live", "Live", Camera], ["video", "Video", Film]].map(([mode, label, Icon]) => (
            <button key={mode} aria-pressed={selected === mode} disabled={busy}
              onClick={() => changeSource(mode)}
              className={`flex h-10 items-center gap-2 rounded px-3 text-sm disabled:opacity-40 ${selected === mode ? "bg-white text-neutral-900" : "bg-neutral-800"}`}>
              <Icon size={17} />{label}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          {!active && <button title={sourceState === "ended" ? "Replay video" : "Start detection"}
            aria-label={sourceState === "ended" ? "Replay video" : "Start detection"} disabled={busy}
            onClick={() => changeSource(selected)} className={iconButton}>
            {sourceState === "ended" ? <RotateCcw size={18} /> : <Play size={18} />}
          </button>}
          {active && <button title="Stop detection" aria-label="Stop detection" disabled={busy}
            onClick={() => changeSource(null)} className={iconButton}><Square size={18} /></button>}
          {(error || stream.status === "error") && <button title="Reconnect viewer" aria-label="Reconnect viewer"
            disabled={busy} onClick={() => setAttempt(n => n + 1)} className={iconButton}><RefreshCw size={18} /></button>}
        </div>
      </div>
      <div className="flex h-7 items-center border-b border-neutral-700 px-3 text-xs font-semibold">
        <span role="status">{connected ? (source.mode === "live" ? "LIVE" : "VIDEO / fall.mp4")
          : selected === "live" ? "Live camera" : "fall.mp4"}</span>
      </div>
      <div className={`relative ${className}`}>
        <canvas ref={canvas} role="img" aria-label="Annotated video from the local detection backend"
          className={`absolute inset-0 h-full w-full object-contain ${connected ? "" : "invisible"}`} />
        {!connected && <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 overflow-auto px-5 py-3 text-center">
          {selected === "live" ? <Camera size={28} className="shrink-0 text-gray-400" /> : <Film size={28} className="shrink-0 text-gray-400" />}
          <p role="status" className="text-sm">{message}</p>
        </div>}
      </div>
    </div>
  );
}
