"""Re-encrypt stored GitHub tokens under the current TOKEN_ENCRYPTION_KEY.

Usage: python -m scripts.rotate_token_key [--purge-unreadable]

Rotation:
  1. Generate a new key. Set it as TOKEN_ENCRYPTION_KEY and move the old one to
     TOKEN_ENCRYPTION_PREVIOUS_KEYS. Restart the API -- both keys now decrypt.
  2. Run this script. Every row is rewritten under the new key.
  3. Remove the old key from TOKEN_ENCRYPTION_PREVIOUS_KEYS and restart.

Recovery (a key was lost): rows no configured key can decrypt are reported. Pass
--purge-unreadable to delete them; those users get a new token the next time they
sign in with GitHub, which works even before the purge.

Reads and writes ciphertext through untyped columns so the ORM's
EncryptedString never decrypts a row it cannot read. Every row is locked
(SELECT ... FOR UPDATE) for the whole run, which is one transaction: a sign-in
or token refresh touching the same user waits until rotation commits, so neither
side overwrites the other. Safe to re-run.
"""

import argparse
from dataclasses import dataclass

from cryptography.fernet import InvalidToken
from sqlalchemy import Connection, column, select, table, text

from app.db.postgres import dispose_engine, get_engine
from app.security import rotate_secret, validate_encryption_keys

_ENCRYPTED = ("access_token", "refresh_token")

# Untyped on purpose: the raw ciphertext, not the ORM's decrypted value.
_credentials = table(
    "github_credentials",
    column("user_id"),
    column("access_token"),
    column("refresh_token"),
)


def locked_credentials_query():
    """Every credential row, locked until the caller's transaction ends.

    Ordered so concurrent lockers always take rows in the same order. SQLite
    (the test database) has no row locks and its dialect omits FOR UPDATE.
    """
    return (
        select(_credentials)
        .order_by(_credentials.c.user_id)
        .with_for_update()
    )


@dataclass
class RotationReport:
    rotated: int = 0
    unreadable: int = 0
    purged: int = 0


def rotate(connection: Connection, *, purge_unreadable: bool = False) -> RotationReport:
    """Rotate every github_credentials row. Does not commit: the caller's
    transaction holds the row locks until it does."""
    report = RotationReport()
    rows = connection.execute(locked_credentials_query()).all()

    for row in rows:
        try:
            values = {
                name: None if row._mapping[name] is None
                else rotate_secret(row._mapping[name])
                for name in _ENCRYPTED
            }
        except InvalidToken:
            report.unreadable += 1
            if purge_unreadable:
                connection.execute(
                    text("DELETE FROM github_credentials WHERE user_id = :user_id"),
                    {"user_id": row.user_id},
                )
                report.purged += 1
            continue

        connection.execute(
            text(
                "UPDATE github_credentials SET access_token = :access_token, "
                "refresh_token = :refresh_token WHERE user_id = :user_id"
            ),
            {**values, "user_id": row.user_id},
        )
        report.rotated += 1
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--purge-unreadable",
        action="store_true",
        help="delete credentials no configured key can decrypt",
    )
    args = parser.parse_args()

    validate_encryption_keys()
    try:
        with get_engine().begin() as connection:
            report = rotate(connection, purge_unreadable=args.purge_unreadable)
    finally:
        dispose_engine()

    print(f"Rotated {report.rotated} credential(s).")
    if report.unreadable:
        action = "Purged" if args.purge_unreadable else "Left in place (re-run with --purge-unreadable)"
        print(f"{report.unreadable} unreadable under every configured key. {action}.")


if __name__ == "__main__":
    main()
