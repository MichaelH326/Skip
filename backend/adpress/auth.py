"""Email + password accounts with bearer tokens, scoped to one workspace per user."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AuthToken, User

PBKDF2_ITERATIONS = int(os.environ.get("ADPRESS_PBKDF2_ITERATIONS", "600000"))
ROLES = ("Owner", "Editor", "Viewer")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
    return hmac.compare_digest(digest.hex(), digest_hex)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(token_hash=_token_hash(token), user_id=user.id,
                     expires_at=datetime.now(timezone.utc) + timedelta(days=settings.token_ttl_days)))
    db.commit()
    return token


def revoke_token(db: Session, token: str) -> None:
    db.query(AuthToken).filter(AuthToken.token_hash == _token_hash(token)).delete()
    db.commit()


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in to continue.")
    return authorization[7:].strip()


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    token = _bearer(authorization)
    row = db.get(AuthToken, _token_hash(token))
    if row is None:
        raise HTTPException(401, "Your session has ended. Sign in again.")
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        raise HTTPException(401, "Your session has ended. Sign in again.")
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(401, "Sign in to continue.")
    return user


def editor(user: User = Depends(current_user)) -> User:
    if user.role not in ("Owner", "Editor"):
        raise HTTPException(403, "Viewers can't make changes. Ask an owner for editor access.")
    return user


def owner(user: User = Depends(current_user)) -> User:
    if user.role != "Owner":
        raise HTTPException(403, "Only workspace owners can do this.")
    return user
