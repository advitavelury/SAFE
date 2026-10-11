"""Bounded reuse of a fully verified token during sequential webcam uploads."""
import hashlib
import math
import time
from threading import Lock


class FrameAuthorizer:
    def __init__(self, authorizer, clock=time.monotonic, wall_clock=time.time):
        self.authorizer = authorizer
        self.clock = clock
        self.wall_clock = wall_clock
        self.lock = Lock()
        self.entry = None

    def verify(self, token):
        key = hashlib.sha256(token.encode()).digest()
        with self.lock:
            now = self.clock()
            if self.entry:
                cached_key, deadline, principal = self.entry
                if key == cached_key and now < deadline and self.wall_clock() < principal.expires_at:
                    return principal
            # Never retain a previous success after a failed or changed-token check.
            self.entry = None
            principal = self.authorizer.verify(token)
            expiry = getattr(principal, "expires_at", 0)
            if (principal.role in ("admin", "operator") and isinstance(expiry, (int, float))
                    and math.isfinite(expiry) and expiry > self.wall_clock()
                    and self.clock() < now + 1.0):
                self.entry = (key, now + 1.0, principal)
            return principal
