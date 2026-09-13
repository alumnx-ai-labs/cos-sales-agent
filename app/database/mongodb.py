from pymongo import MongoClient
from pymongo.database import Database

from app.database.indexes import initialize_indexes


def get_client(uri: str) -> MongoClient:
    return MongoClient(uri)


def get_database(client: MongoClient, name: str) -> Database:
    return client[name]


def initialize_database(client: MongoClient, database_name: str) -> Database:
    db = get_database(client, database_name)
    initialize_indexes(db)
    return db
