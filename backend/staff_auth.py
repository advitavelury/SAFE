"""Firebase ID-token verification and server-side staff approval."""
from dataclasses import dataclass, field

from fastapi import HTTPException
from firebase_admin import auth


@dataclass(frozen=True)
class StaffPrincipal:
    uid: str
    role: str
    token: str = field(repr=False)


class StaffAuthorizer:
    def __init__(self, db=None, verify_token=None):
        self.db = db
        self.verify_token = verify_token or auth.verify_id_token

    def verify(self, token):
        if self.db is None:
            try:
                from .firebase_config import production_db
                self.db = production_db
            except Exception:
                raise HTTPException(503, "Unable to verify staff access.") from None
        try:
            claims = self.verify_token(token, check_revoked=True)
        except (auth.InvalidIdTokenError, auth.RevokedIdTokenError,
                auth.UserDisabledError, auth.UserNotFoundError, ValueError):
            raise HTTPException(401, "Sign in again to access SAFE.",
                                headers={"WWW-Authenticate": "Bearer"}) from None
        except Exception:
            raise HTTPException(503, "Unable to verify staff access.") from None

        uid = claims.get("uid")
        if not isinstance(uid, str) or not uid:
            raise HTTPException(401, "Invalid sign-in token.")
        if claims.get("firebase", {}).get("sign_in_provider") == "anonymous":
            raise HTTPException(403, "Staff access not approved.")
        try:
            snapshot = self.db.collection("users").document(uid).get(timeout=5)
            profile = snapshot.to_dict() if snapshot.exists else {}
            profile = profile or {}
        except Exception:
            raise HTTPException(503, "Unable to verify staff access.") from None
        if profile.get("active") is not True or profile.get("role") not in ("admin", "operator"):
            raise HTTPException(403, "Staff access not approved.")
        return StaffPrincipal(uid=uid, role=profile["role"], token=token)
