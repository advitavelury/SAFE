import { useMemo, useState } from "react";
import {
  AlertTriangle, ChevronDown, MessageSquare, Volume2,
  Layers, ScanFace, PersonStanding,
} from "lucide-react";

import { C, FONT } from "./theme.js";
import { ZONES } from "./data/zones.js";
import { useIncidentFeed } from "./api/feeds.js";
import { useClock } from "./hooks/index.js";
import { iso } from "./utils/date.js";
import { Panel, SectionTitle, Dot, Toggle, Select } from "./components/ui.jsx";
import Calendar from "./components/Calendar.jsx";
import AlertCard from "./components/AlertCard.jsx";
import CameraStage from "./components/CameraStage.jsx";

export default function App() {
  const incidents = useIncidentFeed();
  const now = useClock();

  const [view, setView] = useState("monitor");
  const [zoneId, setZoneId] = useState("A");
  const [selectedDay, setSelectedDay] = useState(() => iso(new Date()));
  const [month, setMonth] = useState(() => new Date().getMonth());
  const [year, setYear] = useState(() => new Date().getFullYear());
  const [showOlder, setShowOlder] = useState(false);
  const [toggles, setToggles] = useState({
    skeleton: false, multiZone: false, faceBlur: false, sms: true, audio: true,
  });

  const setToggle = (k) => (v) => setToggles((t) => ({ ...t, [k]: v }));

  const dayIncidents = useMemo(
    () => incidents.filter((i) => iso(i.ts) === selectedDay).sort((a, b) => b.ts - a.ts),
    [incidents, selectedDay]
  );

  const recent = useMemo(() => [...incidents].sort((a, b) => b.ts - a.ts), [incidents]);
  const visibleRecent = showOlder ? recent : recent.slice(0, 4);

  const summary = useMemo(() => ({
    falls: dayIncidents.filter((i) => i.type === "fall").length,
    distress: dayIncidents.filter((i) => i.type === "distress").length,
    resolutions: dayIncidents.filter((i) => i.status === "resolved").length,
    falseAlarms: dayIncidents.filter((i) => i.type === "false").length,
  }), [dayIncidents]);

  const activeFalls = incidents.filter((i) => i.type === "fall" && i.status === "active");
  const otherZoneFall = activeFalls.find((i) => i.zoneId !== zoneId);

  const zoneStatus = (id) => {
    const active = incidents.filter((i) => i.status === "active" && i.zoneId === id);
    if (active.some((i) => i.type === "fall")) return "fall";
    if (active.length) return "monitor";
    return "clear";
  };

  const selectedDayLabel = new Date(selectedDay + "T00:00:00").toLocaleDateString([], {
    day: "numeric", month: "long", year: "numeric",
  });

  const jumpTo = (incident) => {
    setZoneId(incident.zoneId);
    setSelectedDay(iso(incident.ts));
    setMonth(incident.ts.getMonth());
    setYear(incident.ts.getFullYear());
  };

  return (
    <div
      className="min-h-screen w-full p-3 sm:p-5"
      style={{
        fontFamily: FONT,
        color: C.ink,
        background: `linear-gradient(160deg, ${C.pageTop}, ${C.pageBottom})`,
      }}
    >
      <div className="mx-auto flex max-w-[1500px] flex-col gap-4 lg:flex-row lg:items-start">

        <aside className="flex w-full shrink-0 flex-col gap-4 lg:w-[300px]">
          <Panel className="p-3">
            <Select
              value={view}
              onChange={setView}
              options={[
                { value: "monitor", label: "Monitor" },
                { value: "review", label: "Review" },
                { value: "settings", label: "Settings" },
              ]}
              style={{ fontSize: 16, padding: "9px 12px" }}
            />
          </Panel>

          <Panel className="p-4">
            <SectionTitle>Calendar</SectionTitle>
            <Calendar
              month={month} year={year}
              onMonth={setMonth} onYear={setYear}
              selected={selectedDay} onSelect={setSelectedDay}
              incidents={incidents}
            />
          </Panel>

          <Panel className="p-4">
            <SectionTitle>{selectedDayLabel}</SectionTitle>
            <div className="flex flex-col gap-2">
              {dayIncidents.length === 0 && (
                <p className="py-4 text-center text-sm" style={{ color: C.inkSoft }}>
                  No incidents recorded on this day.
                </p>
              )}
              {dayIncidents.map((i) => (
                <AlertCard key={i.id} incident={i} onSelect={jumpTo} />
              ))}
            </div>
          </Panel>

          <Panel className="p-4">
            <SectionTitle>Incident codes</SectionTitle>
            <dl className="flex flex-col gap-1.5 text-sm">
              {[["F", "Fall", C.fall], ["D", "Distress", C.distress], ["X", "False alarm", C.info]].map(
                ([code, label, color]) => (
                  <div key={code} className="flex items-center gap-2">
                    <dt className="w-4 font-bold" style={{ color }}>{code}</dt>
                    <span style={{ color: C.inkSoft }}>—</span>
                    <dd>{label}</dd>
                  </div>
                )
              )}
            </dl>
          </Panel>
        </aside>

        <main className="flex min-w-0 flex-1 flex-col gap-3">
          <div
            className="rounded-2xl py-3 text-center"
            style={{ background: C.teal, boxShadow: "0 1px 3px rgba(28,42,66,.12)" }}
          >
            <h1 className="text-xl font-bold tracking-tight text-white sm:text-2xl">
              Smart Assisted Fall Emergency
            </h1>
          </div>

          <Panel className="p-3">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <Select
                value={zoneId}
                onChange={setZoneId}
                options={ZONES.map((z) => ({ value: z.id, label: z.name }))}
                className="w-full sm:w-72"
                style={{ fontSize: 15, padding: "8px 12px" }}
              />

              {otherZoneFall ? (
                <button
                  type="button"
                  onClick={() => jumpTo(otherZoneFall)}
                  className="flex items-center gap-2 rounded-lg px-2 py-1 text-sm font-semibold focus:outline-none focus-visible:ring-2"
                  style={{ color: C.fall }}
                >
                  Fall detected in {ZONES.find((z) => z.id === otherZoneFall.zoneId)?.name}
                  <AlertTriangle size={18} />
                </button>
              ) : (
                <span className="flex items-center gap-2 text-sm" style={{ color: C.inkSoft }}>
                  <Dot color={C.clear} /> All other zones clear
                </span>
              )}
            </div>

            {toggles.multiZone ? (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {ZONES.slice(0, 4).map((z) => (
                  <div key={z.id} className="relative">
                    <CameraStage zoneId={z.id} toggles={toggles} scale={0.6} className="aspect-video w-full" />
                    <button
                      type="button"
                      onClick={() => { setZoneId(z.id); setToggle("multiZone")(false); }}
                      className="absolute bottom-2 left-2 rounded-md bg-black/50 px-2 py-1 text-[11px] font-semibold text-white focus:outline-none focus-visible:ring-2"
                    >
                      {z.name}
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <CameraStage zoneId={zoneId} toggles={toggles} className="aspect-video w-full" />
            )}
          </Panel>

          <Panel className="p-3">
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
              <Toggle on={toggles.skeleton} onChange={setToggle("skeleton")} label="Skeleton overlay" icon={PersonStanding} tone={C.tealDeep} />
              <Toggle on={toggles.multiZone} onChange={setToggle("multiZone")} label="Multi-zone viewing" icon={Layers} tone={C.tealDeep} />
              <Toggle on={toggles.faceBlur} onChange={setToggle("faceBlur")} label="Face blur" icon={ScanFace} tone={C.tealDeep} />
              <Toggle on={toggles.sms} onChange={setToggle("sms")} label="SMS alert" icon={MessageSquare} />
              <Toggle on={toggles.audio} onChange={setToggle("audio")} label="Audio alert" icon={Volume2} />
              <span className="ml-auto text-sm tabular-nums" style={{ color: C.inkSoft }}>
                {now.toLocaleTimeString()}
              </span>
            </div>
          </Panel>
        </main>

        <aside className="flex w-full shrink-0 flex-col gap-4 lg:w-[280px]">
          <Panel className="p-4">
            <SectionTitle>Status</SectionTitle>
            <ul className="flex flex-col gap-2 text-sm">
              {[["clear", "Clear", C.clear], ["monitor", "Monitor", C.distress], ["fall", "Fall detected", C.fall]].map(
                ([key, label, color]) => {
                  const count = ZONES.filter((z) => zoneStatus(z.id) === key).length;
                  return (
                    <li key={key} className="flex items-center gap-2.5">
                      <Dot color={color} pulse={key === "fall" && count > 0} />
                      <span className="font-medium">{label}</span>
                      <span className="ml-auto tabular-nums" style={{ color: C.inkSoft }}>
                        {count} {count === 1 ? "zone" : "zones"}
                      </span>
                    </li>
                  );
                }
              )}
            </ul>
          </Panel>

          <Panel className="p-4">
            <SectionTitle>Recent alerts</SectionTitle>
            <div className="flex flex-col gap-2">
              {visibleRecent.map((i) => (
                <AlertCard key={i.id} incident={i} onSelect={jumpTo} />
              ))}
            </div>
            <button
              type="button"
              onClick={() => setShowOlder((v) => !v)}
              className="mx-auto mt-3 flex flex-col items-center gap-0.5 focus:outline-none focus-visible:ring-2"
              style={{ color: C.inkSoft }}
            >
              <ChevronDown
                size={18}
                style={{ transform: showOlder ? "rotate(180deg)" : "none", transition: "transform .18s" }}
              />
              <span className="text-[11px]">{showOlder ? "Show fewer" : "View older incidents"}</span>
            </button>
          </Panel>

          <Panel className="p-4">
            <SectionTitle>Today&rsquo;s summary</SectionTitle>
            <div className="grid grid-cols-2 gap-2">
              {[
                ["Falls", summary.falls, C.fall],
                ["Distress", summary.distress, C.distress],
                ["Resolutions", summary.resolutions, C.clear],
                ["False alarms", summary.falseAlarms, C.info],
              ].map(([label, value, color]) => (
                <div
                  key={label}
                  className="flex items-center gap-2 rounded-xl px-3 py-2"
                  style={{ background: C.panelMuted, border: `1px solid ${C.hair}` }}
                >
                  <Dot color={color} />
                  <div className="min-w-0">
                    <div className="text-2xl font-bold leading-none tabular-nums">{value}</div>
                    <div className="truncate text-[11px]" style={{ color: C.inkSoft }}>{label}</div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </aside>
      </div>
    </div>
  );
}
