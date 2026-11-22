from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.user import Token, UserCreate, UserOut
from app.services.rate_limit import login_limiter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: UserCreate, db: DbSession) -> User:
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(
        email=email,
        hashed_password=hash_password(body.password),
        github_username=body.github_username,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession) -> Token:
    """Send form fields `username` (the email) and `password`. Returns a JWT.
    After 5 failed attempts for an email within 5 minutes, logins for it are paused (429)."""
    email = form.username.lower()
    wait = login_limiter.retry_after(email)
    if wait:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Too many failed logins. Try again in {wait} seconds.",
                            headers={"Retry-After": str(wait)})
    user = db.scalar(select(User).where(User.email == email))
    # Same error for "no such user" and "wrong password" so emails can't be probed.
    if user is None or not verify_password(form.password, user.hashed_password):
        login_limiter.failed(email)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    login_limiter.succeeded(email)
    return Token(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    """Return the logged-in user (requires `Authorization: Bearer <token>`)."""
    return user
