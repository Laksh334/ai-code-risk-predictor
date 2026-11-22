"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Repository, Scan, User

# tokenUrl makes the "Authorize" button in /docs work.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(db: DbSession, token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    """Protects a route: requires header `Authorization: Bearer <token>`."""
    user_id = decode_access_token(token)
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# --- Ownership checks ---------------------------------------------------------
# Another user's repo/scan returns 404 (not 403) so IDs of other users' data can't be probed.


def get_owned_repo(repo_id: int, db: DbSession, user: CurrentUser) -> Repository:
    repo = db.get(Repository, repo_id)
    if repo is None or repo.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repository not found")
    return repo


def get_owned_scan(scan_id: int, db: DbSession, user: CurrentUser) -> Scan:
    scan = db.get(Scan, scan_id)
    if scan is None or scan.repository.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    return scan


OwnedRepo = Annotated[Repository, Depends(get_owned_repo)]
OwnedScan = Annotated[Scan, Depends(get_owned_scan)]
