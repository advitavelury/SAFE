import { AlertTriangle } from "lucide-react";
import { C } from "../theme.js";
import { POSES, BONES } from "../data/poses.js";
import { useDetectionFeed } from "../api/feeds.js";
import { Dot } from "./ui.jsx";

function Skeleton({ det, color }) {
  const p = POSES[det.pose] || POSES.standing;
  const pt = (k) => p[k] || [0.5, 0.5];

  return (
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      className="absolute inset-0 h-full w-full"
      aria-hidden="true"
    >
      {BONES.map(([a, b], i) => (
        <line
          key={i}
          x1={pt(a)[0] * 100} y1={pt(a)[1] * 100}
          x2={pt(b)[0] * 100} y2={pt(b)[1] * 100}
          stroke={color}
          strokeWidth="1.6"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
          opacity="0.95"
        />
      ))}
      {Object.values(p).map(([x, y], i) => (
        <circle key={i} cx={x * 100} cy={y * 100} r="1.4" fill="#fff" stroke={color} strokeWidth="0.8" />
      ))}
    </svg>
  );
}

function DetectionBox({ det, toggles, scale = 1 }) {
  const isFall = det.state === "fall";
  const isDistress = det.state === "distress";
  const color = isFall ? C.boxFall : isDistress ? C.distress : C.boxOk;
  const head = (POSES[det.pose] || POSES.standing).head;

  return (
    <div
      className="absolute"
      style={{
        left: `${det.box.x}%`,
        top: `${det.box.y}%`,
        width: `${det.box.w}%`,
        height: `${det.box.h}%`,
        border: `${2 * scale}px solid ${color}`,
        borderRadius: 3,
        boxShadow: isFall ? `0 0 0 ${3 * scale}px ${color}33` : "none",
        transition: "left .9s linear, top .9s linear",
      }}
    >
      {toggles.skeleton && <Skeleton det={det} color={color} />}

      {toggles.faceBlur && (
        <span
          className="absolute rounded-full"
          style={{
            left: `${head[0] * 100}%`,
            top: `${head[1] * 100}%`,
            width: `${28 * scale}%`,
            height: `${16 * scale}%`,
            minWidth: 14,
            minHeight: 14,
            transform: "translate(-50%,-50%)",
            backdropFilter: "blur(7px)",
            WebkitBackdropFilter: "blur(7px)",
            background: "rgba(255,255,255,.18)",
          }}
        />
      )}

      {scale === 1 && (
        <span
          className="absolute whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-bold text-white"
          style={{ background: color, top: -18, left: -2 }}
        >
          {isFall ? "FALL" : isDistress ? "STILLNESS" : "PERSON"} {det.conf.toFixed(2)}
        </span>
      )}

      {isFall && scale === 1 && (
        <AlertTriangle
          size={18}
          className="absolute"
          style={{ right: 4, bottom: 4, color: "#fff", filter: "drop-shadow(0 1px 2px rgba(0,0,0,.6))" }}
        />
      )}
    </div>
  );
}

/* Placeholder backdrop — replace with <video> or an MJPEG <img> for a real stream. */
function StageBackdrop({ zoneId }) {
  return (
    <div className="absolute inset-0" aria-hidden="true">
      <div className="absolute inset-x-0 top-0" style={{ height: "62%", background: "linear-gradient(180deg,#5d6472,#454b57)" }} />
      <div className="absolute inset-x-0 bottom-0" style={{ height: "38%", background: "linear-gradient(180deg,#6a6157,#544d45)" }} />
      <div className="absolute" style={{ left: "8%", top: "14%", width: "16%", height: "24%", background: "rgba(255,255,255,.07)", border: "1px solid rgba(255,255,255,.12)" }} />
      <div className="absolute" style={{ right: "6%", top: "10%", width: "22%", height: "40%", background: "rgba(190,214,236,.12)", border: "1px solid rgba(255,255,255,.14)" }} />
      <span
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-center text-xs font-medium"
        style={{ color: "rgba(255,255,255,.42)" }}
      >
        Camera {zoneId} · simulated feed
        <br />
        <span className="text-[11px]">Connect a stream to replace this view</span>
      </span>
    </div>
  );
}

export default function CameraStage({ zoneId, toggles, live = true, scale = 1, className = "" }) {
  const detections = useDetectionFeed(zoneId, live);

  return (
    <div className={`relative overflow-hidden ${className}`} style={{ background: "#3c4250", borderRadius: 8 }}>
      <StageBackdrop zoneId={zoneId} />
      {detections.map((d) => (
        <DetectionBox key={d.id} det={d} toggles={toggles} scale={scale} />
      ))}
      {live && scale === 1 && (
        <div className="absolute left-3 top-3 flex items-center gap-1.5 rounded-md bg-black/45 px-2 py-1">
          <Dot color={C.fall} pulse />
          <span className="text-[11px] font-bold tracking-wide text-white">LIVE</span>
        </div>
      )}
    </div>
  );
}
