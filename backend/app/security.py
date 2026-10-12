import hashlib
import hmac
import secrets


def token() -> str:
    return secrets.token_urlsafe(32)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(value: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.scrypt(value.encode(), salt=salt.encode(), n=16384, r=8, p=1)
    return f"scrypt${salt}${hashed.hex()}"


def verify_password(value: str, stored: str) -> bool:
    try:
        algorithm, salt, expected = stored.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(value.encode(), salt=salt.encode(), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False
