import { useEventFeed } from './feeds.js';
import { useStaffSession } from './StaffSession.jsx';
import { canEditEvents } from './staffAccess.js';

export function useAdminEvents() {
  const feed = useEventFeed();
  const session = useStaffSession();
  return { ...feed, canUpdate: canEditEvents(session?.user, session?.profile) };
}
