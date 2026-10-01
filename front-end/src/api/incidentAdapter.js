import { demoSeverity, EVENT_TYPES } from '../data/events.js';

export function toAdminEvent(incident) {
  const occurredAt = incident.ts.toISOString();
  const type = incident.type in EVENT_TYPES ? incident.type : 'distress';
  return {
    schemaVersion: 1,
    id: incident.id,
    type,
    severity: demoSeverity(type),
    status: ['active', 'acknowledged', 'resolved'].includes(incident.status) ? incident.status : 'active',
    outcome: ['confirmed', 'false_alarm', 'unconfirmed'].includes(incident.outcome)
      ? incident.outcome : incident.type === 'false' ? 'false_alarm' : 'unconfirmed',
    cameraId: `zone-${incident.zoneId}`,
    trackId: incident.personId || 'Unknown',
    occurredAt,
    updatedAt: incident.updatedAt?.toISOString() || occurredAt,
    source: incident.source || 'safe-backend',
    assignedTo: incident.responder || null,
    notes: incident.note ? [{ text: incident.note, actor: 'Detector', at: occurredAt }] : [],
    history: [{ id: `${incident.id}-created`, action: 'detected', at: occurredAt, actor: 'Detector' }],
  };
}
