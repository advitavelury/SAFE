import { at } from "../utils/date.js";
import { C } from "../theme.js";

// Box values are percentages of the camera stage.
// state: "normal" | "fall" | "distress"
export const DETECTIONS = {
  A: [
    { id: "a1", conf: 0.94, state: "normal", pose: "sitting",  box: { x: 3,  y: 30, w: 20, h: 58 } },
    { id: "a2", conf: 0.96, state: "normal", pose: "standing", box: { x: 22, y: 6,  w: 15, h: 62 } },
    { id: "a3", conf: 0.93, state: "normal", pose: "standing", box: { x: 40, y: 5,  w: 15, h: 66 } },
    { id: "a4", conf: 0.88, state: "normal", pose: "sitting",  box: { x: 46, y: 25, w: 12, h: 34 } },
    { id: "a5", conf: 0.86, state: "normal", pose: "sitting",  box: { x: 59, y: 27, w: 13, h: 33 } },
    { id: "a6", conf: 0.91, state: "normal", pose: "standing", box: { x: 82, y: 12, w: 16, h: 62 } },
    { id: "a7", conf: 0.97, state: "fall",   pose: "fallen",   box: { x: 34, y: 62, w: 52, h: 30 } },
  ],
  B: [
    { id: "b1", conf: 0.92, state: "normal", pose: "standing", box: { x: 18, y: 14, w: 16, h: 64 } },
    { id: "b2", conf: 0.9,  state: "normal", pose: "sitting",  box: { x: 55, y: 32, w: 18, h: 50 } },
  ],
  C: [{ id: "c1", conf: 0.95, state: "normal", pose: "sitting", box: { x: 30, y: 28, w: 22, h: 56 } }],
  D: [{ id: "d1", conf: 0.89, state: "distress", pose: "sitting", box: { x: 38, y: 24, w: 21, h: 60 } }],
  G: [{ id: "g1", conf: 0.87, state: "normal", pose: "standing", box: { x: 44, y: 12, w: 17, h: 68 } }],
};

// Seeded relative to today so the demo always looks current.
export const INCIDENTS = [
  { id: "F1223", type: "fall",     status: "active",   zoneId: "A", ts: at(0, 9, 41) },
  { id: "F1222", type: "fall",     status: "active",   zoneId: "C", ts: at(0, 9, 37) },
  { id: "D4673", type: "distress", status: "active",   zoneId: "D", ts: at(0, 9, 0),  note: "Prolonged stillness" },
  { id: "F1220", type: "fall",     status: "resolved", zoneId: "G", ts: at(-1, 11, 47), responder: "N. Halim" },
  { id: "D4671", type: "distress", status: "resolved", zoneId: "B", ts: at(-1, 8, 12),  note: "Prolonged stillness", responder: "S. Perera" },
  { id: "X0912", type: "false",    status: "resolved", zoneId: "A", ts: at(-2, 16, 30), note: "Blanket misread as body" },
  { id: "F1217", type: "fall",     status: "resolved", zoneId: "C", ts: at(-4, 22, 5),  responder: "N. Halim" },
  { id: "D4664", type: "distress", status: "resolved", zoneId: "D", ts: at(-6, 14, 20), note: "Prolonged stillness" },
  { id: "F1211", type: "fall",     status: "resolved", zoneId: "G", ts: at(-9, 6, 55),  responder: "J. Okafor" },
  { id: "F1208", type: "fall",     status: "resolved", zoneId: "B", ts: at(-13, 19, 40), responder: "S. Perera" },
];

export const TYPE_META = {
  fall:     { label: "Fall detected", code: "F", color: C.fall,     soft: C.fallSoft },
  distress: { label: "Distress",      code: "D", color: C.distress, soft: C.distressSoft },
  false:    { label: "False alarm",   code: "X", color: C.info,     soft: C.infoSoft },
};
