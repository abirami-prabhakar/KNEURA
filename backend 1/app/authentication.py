import base64
import hashlib
import hmac
import json
import os
import secrets
import time


ALGORITHM = "HS256"
PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 310_000
TOKEN_EXPIRE_SECONDS = 3600
SECRET_KEY = os.getenv("KNEE_AI_AUTH_SECRET", "local-development-only-change-me")


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password cannot be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return "$".join(
        (
            PASSWORD_SCHEME,
            str(PASSWORD_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, encoded_salt, encoded_digest = encoded.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        expected = base64.urlsafe_b64decode(encoded_digest.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError, base64.binascii.Error):
        return False


def _encode_part(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_part(value: str) -> object:
    padding = "=" * (-len(value) % 4)
    return json.loads(base64.urlsafe_b64decode((value + padding).encode("ascii")))


def create_access_token(user_id: int, role: str) -> str:
    header = _encode_part({"alg": ALGORITHM, "typ": "JWT"})
    payload = _encode_part(
        {
            "sub": str(user_id),
            "role": role,
            "exp": int(time.time()) + TOKEN_EXPIRE_SECONDS,
        }
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"


def decode_access_token(token: str) -> dict:
    try:
        header, payload, signature = token.split(".", 2)
        if _decode_part(header).get("alg") != ALGORITHM:
            raise ValueError("Unsupported token algorithm")
        expected = hmac.new(
            SECRET_KEY.encode("utf-8"),
            f"{header}.{payload}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        actual = base64.urlsafe_b64decode((signature + "=" * (-len(signature) % 4)).encode("ascii"))
        if not hmac.compare_digest(actual, expected):
            raise ValueError("Invalid token signature")
        claims = _decode_part(payload)
        if not isinstance(claims, dict) or int(claims["exp"]) <= int(time.time()):
            raise ValueError("Expired token")
        return claims
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, base64.binascii.Error) as exc:
        raise ValueError("Invalid access token") from exc
