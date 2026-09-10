export const EVENT_TYPES = { fall: 'Fall detected', prolonged_sitting: 'Prolonged sitting', isolation: 'Isolation' };
export const SEVERITIES = { high: 'High alert', medium: 'Medium alert', low: 'Low alert' };
export const demoSeverity = type => type === 'fall' ? 'high' : type === 'prolonged_sitting' ? 'medium' : 'low';
export const STATUSES = { active: 'Needs review', acknowledged: 'Acknowledged', resolved: 'Resolved' };
const timestamp = (days, hour, minute) => { const d = new Date(); d.setDate(d.getDate() - days); d.setHours(hour, minute, 0, 0); return d.toISOString(); };
export function seedEvents() {
  return [
    ['EV-1042', 'fall', 0, 9, 41, 'active', 'unconfirmed'],
    ['EV-1041', 'prolonged_sitting', 0, 9, 12, 'acknowledged', 'unconfirmed'],
    ['EV-1040', 'isolation', 0, 8, 35, 'resolved', 'confirmed'],
    ['EV-1039', 'fall', 1, 16, 20, 'resolved', 'false_alarm'],
    ['EV-1038', 'prolonged_sitting', 1, 11, 5, 'resolved', 'confirmed'],
    ['EV-1037', 'isolation', 2, 10, 15, 'resolved', 'confirmed'],
  ].map(([id, type, days, hour, minute, status, outcome], i) => {
    const occurredAt = timestamp(days, hour, minute);
    return { schemaVersion: 1, id, type, severity: demoSeverity(type), status, outcome,
      cameraId: 'camera-01', trackId: `session-demo:track-${i + 1}`, occurredAt, updatedAt: occurredAt,
      source: 'demo', assignedTo: status === 'active' ? null : 'Demo administrator',
      notes: [], history: [{ id: `${id}-created`, action: 'created', at: occurredAt, actor: 'Demo detector' }] };
  });
}
export function transitionEvent(event, action, actor, note = '', at = new Date().toISOString()) {
  const allowed = action === 'acknowledge' ? event.status === 'active' : ['resolve', 'false_alarm'].includes(action) && event.status !== 'resolved';
  if (!allowed) return event;
  return { ...event, status: action === 'acknowledge' ? 'acknowledged' : 'resolved',
    outcome: action === 'false_alarm' ? 'false_alarm' : action === 'resolve' ? 'confirmed' : event.outcome,
    assignedTo: actor, updatedAt: at,
    notes: note.trim() ? [...event.notes, { text: note.trim(), actor, at }] : event.notes,
    history: [...event.history, { id: `${event.id}-${event.history.length}`, action, actor, at }] };
}
