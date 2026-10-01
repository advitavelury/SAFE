import { useState } from 'react';
import { seedEvents, transitionEvent, demoSeverity } from '../data/events.js';
const KEY = 'safe-admin-demo-v1';
export function useAdminEvents() {
  const [events, setEvents] = useState(() => {
    try {
      const value = JSON.parse(localStorage.getItem(KEY));
      if (Array.isArray(value) && value.length && value.every(e =>
        e.schemaVersion === 1 && Array.isArray(e.history) && Array.isArray(e.notes)
      )) return value.map(e => ({ ...e, severity: ['high', 'medium', 'low'].includes(e.severity) ? e.severity : demoSeverity(e.type) }));
    } catch { /* Use sample data if browser storage is unavailable. */ }
    return seedEvents();
  });
  const [storageError, setStorageError] = useState('');
  const update = (id, action, note) => {
    const next = events.map(e => e.id === id
      ? transitionEvent(e, action, 'Demo administrator', note) : e);
    setEvents(next);
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
      setStorageError('');
    } catch {
      setStorageError('Changes are in memory only. Browser storage is unavailable.');
    }
  };
  return { events, update, storageError };
}
