import base64
import hashlib
import hmac
import os

_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return base64.b64encode(salt + digest).decode()


def verify_password(password: str, hashed: str) -> bool:
    raw = base64.b64decode(hashed.encode())
    salt, digest = raw[:16], raw[16:]
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return hmac.compare_digest(digest, candidate)
