from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for relational models stored in Postgres."""
