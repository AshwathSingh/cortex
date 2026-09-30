"""Custom column types shared by relational models."""

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.security import decrypt_secret, encrypt_secret


class EncryptedString(TypeDecorator[str]):
    """A string stored Fernet-encrypted and decrypted transparently on load.

    Encryption happens at the ORM boundary, so the plaintext never reaches the
    database, its logs or its backups. Fernet output is non-deterministic, so an
    encrypted column cannot be filtered or indexed on -- look rows up by key.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        return None if value is None else encrypt_secret(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        return None if value is None else decrypt_secret(value)
