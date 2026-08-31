import { useMemo } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { C } from "../theme.js";
import { iso } from "../utils/date.js";
import { Select } from "./ui.jsx";

export default function Calendar({ month, year, onMonth, onYear, selected, onSelect, incidents }) {
  const first = new Date(year, month, 1);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const lead = first.getDay();

  const byDay = useMemo(() => {
    const m = {};
    incidents.forEach((i) => {
      const k = iso(i.ts);
      if (!m[k]) m[k] = [];
      m[k].push(i);
    });
    return m;
  }, [incidents]);

  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  const step = (delta) => {
    let m = month + delta;
    let y = year;
    if (m < 0) { m = 11; y -= 1; }
    if (m > 11) { m = 0; y += 1; }
    onMonth(m);
    onYear(y);
  };

  const months = Array.from({ length: 12 }, (_, i) => ({
    value: String(i),
    label: new Date(2000, i, 1).toLocaleString([], { month: "long" }),
  }));
  const nowY = new Date().getFullYear();
  const years = [nowY - 1, nowY, nowY + 1].map((y) => ({ value: String(y), label: String(y) }));

  return (
    <div>
      <div className="mb-2 flex items-center gap-1">
        <button
          type="button"
          onClick={() => step(-1)}
          aria-label="Previous month"
          className="rounded-lg p-1 focus:outline-none focus-visible:ring-2"
          style={{ color: C.tealDeep }}
        >
          <ChevronLeft size={18} />
        </button>

        <Select
          value={String(month)}
          onChange={(v) => onMonth(Number(v))}
          options={months}
          className="flex-1"
          style={{ padding: "5px 10px", fontSize: 13 }}
        />
        <Select
          value={String(year)}
          onChange={(v) => onYear(Number(v))}
          options={years}
          className="w-24"
          style={{ padding: "5px 10px", fontSize: 13 }}
        />

        <button
          type="button"
          onClick={() => step(1)}
          aria-label="Next month"
          className="rounded-lg p-1 focus:outline-none focus-visible:ring-2"
          style={{ color: C.tealDeep }}
        >
          <ChevronRight size={18} />
        </button>
      </div>

      <div className="grid grid-cols-7 gap-y-1 text-center">
        {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map((d) => (
          <div key={d} className="pb-1 text-[11px] font-semibold" style={{ color: C.inkSoft }}>
            {d}
          </div>
        ))}

        {cells.map((d, i) => {
          if (d === null) return <div key={i} />;
          const date = new Date(year, month, d);
          const key = iso(date);
          const items = byDay[key] || [];
          const hasFall = items.some((x) => x.type === "fall");
          const hasDistress = items.some((x) => x.type === "distress");
          const isSelected = key === selected;
          const isToday = key === iso(new Date());
          const bg = hasFall ? C.fall : hasDistress ? C.distress : "transparent";
          const fg = hasFall || hasDistress ? "#fff" : C.ink;

          return (
            <button
              key={i}
              type="button"
              onClick={() => onSelect(key)}
              aria-label={`${date.toDateString()}${items.length ? `, ${items.length} incidents` : ""}`}
              className="mx-auto flex items-center justify-center rounded-lg text-[13px] font-semibold focus:outline-none focus-visible:ring-2"
              style={{
                width: 30,
                height: 30,
                background: bg,
                color: fg,
                border: isSelected
                  ? `2px solid ${C.fall}`
                  : isToday
                  ? `2px solid ${C.teal}`
                  : "2px solid transparent",
              }}
            >
              {d}
            </button>
          );
        })}
      </div>
    </div>
  );
}
