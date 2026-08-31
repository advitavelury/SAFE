import { C } from "../theme.js";
import { ZONES } from "../data/zones.js";
import { TYPE_META } from "../data/mock.js";
import { fmtTime, relDay } from "../utils/date.js";

export default function AlertCard({ incident, onSelect, compact = false }) {
  const meta = TYPE_META[incident.type];
  const zone = ZONES.find((z) => z.id === incident.zoneId);
  const resolved = incident.status === "resolved";

  return (
    <button
      type="button"
      onClick={() => onSelect?.(incident)}
      className="w-full rounded-xl px-3 py-2 text-left focus:outline-none focus-visible:ring-2"
      style={{
        background: resolved ? C.clearSoft : meta.soft,
        border: `1px solid ${resolved ? "#cfe4cf" : meta.color + "33"}`,
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-[11px]" style={{ color: C.inkSoft }}>
          {fmtTime(incident.ts)} {relDay(incident.ts)}
        </span>
        <span className="text-[11px] font-semibold tabular-nums" style={{ color: C.inkSoft }}>
          {incident.id}
        </span>
      </div>

      <div
        className="text-sm font-bold leading-tight"
        style={{ color: resolved ? "#3d6b40" : meta.color }}
      >
        {resolved ? `Resolved incident ${incident.id}` : meta.label}
      </div>

      {incident.note && !resolved && (
        <div className="text-xs" style={{ color: C.ink }}>{incident.note}</div>
      )}
      {resolved && incident.responder && (
        <div className="text-xs" style={{ color: C.ink }}>{incident.responder} responded</div>
      )}

      {!compact && (
        <div
          className="mt-1.5 pt-1.5 text-xs"
          style={{
            borderTop: `1px solid ${resolved ? "#cfe4cf" : meta.color + "26"}`,
            color: C.inkSoft,
          }}
        >
          {zone?.name}
        </div>
      )}
    </button>
  );
}
