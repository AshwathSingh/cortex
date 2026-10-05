"""Password, session-token and at-rest encryption primitives."""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, MultiFernet

from app.config import settings

_password_hasher = PasswordHasher()


class EncryptionKeyError(RuntimeError):
    """A token encryption key is missing or malformed. Never carries the key."""


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _fernet(env_name: str, key: str) -> Fernet:
    try:
        return Fernet(key)
    except (ValueError, TypeError):
        # `from None`: the chained error is harmless today, but nothing about a
        # bad key should reach a traceback or log line.
        raise EncryptionKeyError(
            f"{env_name} is not a valid Fernet key (32 url-safe base64-encoded "
            "bytes). Generate one with: python -c \"from cryptography.fernet "
            'import Fernet; print(Fernet.generate_key().decode())"'
        ) from None


def _token_cipher() -> MultiFernet:
    """Encrypts with TOKEN_ENCRYPTION_KEY; decrypts with it or any previous key.

    Read on every call, not cached at import, so tests can swap keys.
    """
    if settings.token_encryption_key is None:
        raise EncryptionKeyError(
            "TOKEN_ENCRYPTION_KEY is not set; it is required to store OAuth tokens"
        )
    keys = [_fernet("TOKEN_ENCRYPTION_KEY", settings.token_encryption_key.get_secret_value())]
    keys += [
        _fernet("TOKEN_ENCRYPTION_PREVIOUS_KEYS", key)
        for key in settings.token_encryption_previous_key_list
    ]
    return MultiFernet(keys)


def validate_encryption_keys() -> None:
    """Startup check, so a malformed key fails boot rather than the first sign-in.

    Unset keys are allowed -- GitHub sign-in then answers 503 -- but previous keys
    without a current one are a misconfiguration.
    """
    if settings.token_encryption_key is not None:
        _token_cipher()
    elif settings.token_encryption_previous_key_list:
        raise EncryptionKeyError(
            "TOKEN_ENCRYPTION_PREVIOUS_KEYS is set but TOKEN_ENCRYPTION_KEY is not"
        )


def encrypt_secret(plaintext: str) -> str:
    return _token_cipher().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """Raises ``cryptography.fernet.InvalidToken`` if no configured key fits."""
    return _token_cipher().decrypt(ciphertext.encode("ascii")).decode("utf-8")


def rotate_secret(ciphertext: str) -> str:
    """Re-encrypt under the current key. Raises ``InvalidToken`` like decrypt."""
    return _token_cipher().rotate(ciphertext.encode("ascii")).decode("ascii")
