import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .logging_config import logger

_DEV_SECRET_KEY = "dev-secret-key-change-in-production"
APP_ENV = os.environ.get("APP_ENV", "development").lower()
SECRET_KEY = os.environ.get("SECRET_KEY") or _DEV_SECRET_KEY
if APP_ENV in {"production", "prod"} and SECRET_KEY == _DEV_SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set when APP_ENV=production")
if SECRET_KEY == _DEV_SECRET_KEY:
    logger.warning(
        "SECRET_KEY ortam değişkeni ayarlanmamış; geliştirme amaçlı varsayılan anahtar kullanılıyor. "
        "Bu anahtarla üretilen JWT'ler tahmin edilebilir olur - production'a almadan önce "
        "SECRET_KEY ortam değişkenini kendi rastgele değerinizle mutlaka ayarlayın."
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": subject, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    request: Request, token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = token or request.cookies.get("access_token")
    try:
        if not token:
            raise credentials_exception
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credentials_exception
    return user


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_refresh_token(user_id: int, db: Session) -> str:
    raw_token = secrets.token_urlsafe(32)
    db.add(
        models.RefreshToken(
            user_id=user_id,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    db.commit()
    return raw_token


def use_refresh_token(raw_token: str, db: Session) -> models.User:
    """Validates a refresh token (must exist, be unrevoked, and unexpired) and returns its owner."""
    invalid = HTTPException(status_code=401, detail="Invalid or expired refresh token")
    db_token = (
        db.query(models.RefreshToken)
        .filter(models.RefreshToken.token_hash == _hash_token(raw_token))
        .first()
    )
    if db_token is None or db_token.revoked or db_token.expires_at < datetime.utcnow():
        raise invalid

    user = db.query(models.User).filter(models.User.id == db_token.user_id).first()
    if user is None:
        raise invalid
    return user


def revoke_refresh_token(raw_token: str, db: Session) -> None:
    db_token = (
        db.query(models.RefreshToken)
        .filter(models.RefreshToken.token_hash == _hash_token(raw_token))
        .first()
    )
    if db_token is not None:
        db_token.revoked = True
        db.commit()
