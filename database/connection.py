"""
MongoDB connection manager.

Reads credentials from environment variables (loaded via .env):
    MONGO_HOST        — default: 127.0.0.1
    MONGO_PORT        — default: 27018
    MONGO_USER        — required
    MONGO_PASSWORD    — required
    MONGO_AUTH_SOURCE — default: admin
    MONGO_DB          — default: deco_crips_chat_history

Or set MONGO_URI directly to override everything.

Usage:
    from database.connection import get_db
    db = get_db()
    col = db["deco_chat"]
"""

import os
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.database import Database

# Load .env from the project root (parent of this file's directory)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

_client: MongoClient | None = None


def _build_uri() -> str:
    if uri := os.getenv("MONGO_URI"):
        return uri

    user     = urllib.parse.quote_plus(os.environ["MONGO_USER"])
    password = urllib.parse.quote_plus(os.environ["MONGO_PASSWORD"])
    host     = os.getenv("MONGO_HOST", "127.0.0.1")
    port     = os.getenv("MONGO_PORT", "27018")
    auth_src = os.getenv("MONGO_AUTH_SOURCE", "admin")

    return f"mongodb://{user}:{password}@{host}:{port}/?authSource={auth_src}"


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(_build_uri(), serverSelectionTimeoutMS=10_000)
    return _client


def get_db(name: str | None = None) -> Database:
    db_name = name or os.getenv("MONGO_DB", "deco_crips_chat_history")
    return get_client()[db_name]


def close():
    global _client
    if _client is not None:
        _client.close()
        _client = None
