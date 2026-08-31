import { ChevronDown } from "lucide-react";
import { C, FONT } from "../theme.js";

export function Panel({ children, className = "", style = {} }) {
  return (
    <div
      className={`rounded-2xl ${className}`}
      style={{ background: C.panel, boxShadow: "0 1px 3px rgba(28,42,66,.12)", ...style }}
    >
      {children}
    </div>
  );
}

export function SectionTitle({ children, right }) {
  return (
    <div
      className="flex items-baseline justify-between pb-1 mb-3"
      style={{ borderBottom: `1px solid ${C.hair}` }}
    >
      <h2 className="text-base font-semibold tracking-tight" style={{ color: C.tealDeep }}>
        {children}
      </h2>
      {right}
    </div>
  );
}

export function Dot({ color, pulse = false }) {
  return (
    <span
      className="inline-block rounded-full shrink-0"
      style={{
        width: 11,
        height: 11,
        background: color,
        boxShadow: pulse ? `0 0 0 4px ${color}33` : "none",
      }}
    />
  );
}

export function Toggle({ on, onChange, label, icon: Icon, tone = C.clear }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      className="flex items-center gap-2 rounded-full px-1 py-1 focus:outline-none focus-visible:ring-2"
      style={{ color: C.ink }}
    >
      <span
        className="relative rounded-full"
        style={{
          width: 46,
          height: 25,
          background: on ? tone : "#cfd8e0",
          transition: "background .18s ease",
        }}
      >
        <span
          className="absolute rounded-full bg-white"
          style={{
            width: 19,
            height: 19,
            top: 3,
            left: on ? 24 : 3,
            transition: "left .18s ease",
            boxShadow: "0 1px 2px rgba(0,0,0,.25)",
          }}
        />
      </span>
      <span className="flex items-center gap-1.5 text-sm font-medium whitespace-nowrap">
        {Icon && <Icon size={15} style={{ color: C.inkSoft }} />}
        {label}
      </span>
    </button>
  );
}

export function Select({ value, onChange, options, className = "", style = {} }) {
  return (
    <div className={`relative ${className}`}>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full appearance-none rounded-xl px-3 py-2 pr-9 text-sm font-semibold focus:outline-none focus-visible:ring-2"
        style={{
          background: C.panel,
          color: C.ink,
          border: `1px solid ${C.hair}`,
          fontFamily: FONT,
          ...style,
        }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown
        size={16}
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2"
        style={{ color: C.inkSoft }}
      />
    </div>
  );
}
