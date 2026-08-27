export const iso = (d) => d.toISOString().slice(0, 10);

export const dayShift = (n) => {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d;
};

export const at = (n, h, m) => {
  const d = dayShift(n);
  d.setHours(h, m, 0, 0);
  return d;
};

export const fmtTime = (d) =>
  d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }).replace(/^0/, "");

export const relDay = (d) => {
  const key = iso(d);
  if (key === iso(new Date())) return "Today";
  if (key === iso(dayShift(-1))) return "Yesterday";
  return d.toLocaleDateString([], { day: "2-digit", month: "2-digit", year: "numeric" });
};
