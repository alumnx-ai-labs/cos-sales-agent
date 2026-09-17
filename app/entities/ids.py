from pymongo.database import Database

from app.database.repositories import CounterRepository


def next_id(db: Database, prefix: str) -> str:
    seq = CounterRepository(db).increment_and_get(prefix)
    return f"{prefix}{seq:03d}"
