import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException

from backend.frame_authorizer import FrameAuthorizer


class FrameAuthorizerTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.wall = 1000.0
        self.base = Mock()
        self.base.verify.return_value = SimpleNamespace(uid="admin", role="admin", expires_at=2000.0)
        self.cache = FrameAuthorizer(self.base, clock=lambda: self.now, wall_clock=lambda: self.wall)

    def test_same_verified_token_is_reused_for_less_than_one_second(self):
        first = self.cache.verify("token")
        for now in (0.1, 0.5, 0.999):
            self.now = now
            self.assertIs(self.cache.verify("token"), first)
        self.assertEqual(self.base.verify.call_count, 1)
        self.now = 1.0
        self.cache.verify("token")
        self.assertEqual(self.base.verify.call_count, 2)

    def test_token_expiry_ends_reuse_even_inside_cache_window(self):
        self.base.verify.return_value.expires_at = 1000.2
        self.cache.verify("token")
        self.wall = 1000.2
        self.base.verify.side_effect = HTTPException(401, "Expired")
        with self.assertRaises(HTTPException):
            self.cache.verify("token")
        self.assertIsNone(self.cache.entry)

    def test_revocation_and_profile_changes_are_checked_at_deadline(self):
        self.cache.verify("token")
        self.now = 1.0
        self.base.verify.side_effect = HTTPException(403, "Access revoked")
        with self.assertRaises(HTTPException):
            self.cache.verify("token")
        with self.assertRaises(HTTPException):
            self.cache.verify("token")
        self.assertEqual(self.base.verify.call_count, 3)

    def test_changed_token_never_inherits_another_tokens_approval(self):
        self.cache.verify("approved")
        self.base.verify.side_effect = HTTPException(401, "Invalid")
        with self.assertRaises(HTTPException):
            self.cache.verify("different")
        self.assertIsNone(self.cache.entry)

    def test_non_admin_and_missing_expiry_are_not_cached(self):
        for role, expiry in (("operator", 2000), ("admin", 0), ("admin", None), ("admin", float("nan"))):
            self.base.verify.return_value = SimpleNamespace(role=role, expires_at=expiry)
            self.cache.verify("token")
            self.assertIsNone(self.cache.entry)

    def test_slow_verification_does_not_extend_one_second_window(self):
        def slow_verify(token):
            self.now += 1.1
            return SimpleNamespace(role="admin", expires_at=2000)
        self.base.verify.side_effect = slow_verify
        self.cache.verify("token")
        self.assertIsNone(self.cache.entry)


if __name__ == "__main__":
    unittest.main()
