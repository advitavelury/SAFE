const types = {
  fall: 'fall',
  'sitting distress': 'prolonged_sitting',
  'isolation distress': 'isolation',
  'wandering distress': 'wandering',
};

function timestamp(value) {
  if (value == null) return null;
  try {
    const date = typeof value.toDate === 'function' ? value.toDate()
      : value instanceof Date ? value
      : typeof value === 'string' || typeof value === 'number' ? new Date(value) : null;
    return date && Number.isFinite(date.getTime()) ? date.toISOString() : null;
  } catch {
    return null;
  }
}

export function toDashboardEvent(id, data) {
  return {
    id,
    type: Object.hasOwn(types, data.event_type) ? types[data.event_type] : 'unknown',
    severity: data.alert_level === 'red' ? 'high' : data.alert_level === 'amber' ? 'medium' : 'unknown',
    status: ['open', 'closed'].includes(data.status) ? data.status : 'unknown',
    trackId: data.person_id ?? 'Unknown',
    occurredAt: timestamp(data.timestamp),
    completedAt: timestamp(data.completed_at),
    completedBy: typeof data.completed_by === 'string' ? data.completed_by : null,
    imagePath: typeof data.image_path === 'string' ? data.image_path : null,
  };
}
