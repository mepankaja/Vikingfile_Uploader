"""
MongoDB-backed user storage using Motor (async).

Drop-in replacement for the old JSON file db.py — same public API:
  get_user(user_id)          → dict
  set_user_field(uid, k, v)  → None
  get_hash(user_id)          → str
  get_default_path(user_id)  → str

All functions are async-compatible: they run Motor coroutines via
asyncio.get_event_loop().run_until_complete() when called from sync
context, but handlers should prefer await_get_user / await_set_user_field
for proper async usage.

Since aiogram handlers are all async, we expose both:
  - Sync wrappers (get_user, set_user_field) — kept for compat
  - Async versions (async_get_user, async_set_user_field) — preferred
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import motor.motor_asyncio

from config import MONGO_URI, MONGO_DB

logger = logging.getLogger(__name__)

_client: motor.motor_asyncio.AsyncIOMotorClient | None = None
_col:    motor.motor_asyncio.AsyncIOMotorCollection  | None = None

_DEFAULT_USER = {
    "hash":               "",
    "default_path":       "",
    "notify_on_complete": True,
    "zip_compress_level": 6,
    "auto_delete_temp":   True,
    "known_paths":        [],   # folders this user has uploaded to — VikingFile's
                                  # API has no list-folders endpoint, so we track
                                  # paths ourselves to offer quick navigation
}


def _get_col() -> motor.motor_asyncio.AsyncIOMotorCollection:
    global _client, _col
    if _col is None:
        _client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
        _col    = _client[MONGO_DB]["users"]
    return _col


async def init_db() -> None:
    """Call once at startup to create indexes."""
    col = _get_col()
    await col.create_index("uid", unique=True)
    logger.info("✅ MongoDB connected and indexes ready")


# ── Async API (preferred in handlers) ─────────────────────────────────────────

async def async_get_user(user_id: int) -> dict:
    col = _get_col()
    uid = int(user_id)
    doc = await col.find_one({"uid": uid}, {"_id": 0})
    if doc is None:
        doc = {"uid": uid, **_DEFAULT_USER}
        try:
            await col.insert_one(doc)
        except Exception:
            pass  # race condition — another insert won
        doc = await col.find_one({"uid": uid}, {"_id": 0}) or doc
    # Ensure all default keys exist (handles existing docs missing new fields)
    changed = False
    for k, v in _DEFAULT_USER.items():
        if k not in doc:
            doc[k] = v
            changed = True
    if changed:
        await col.update_one(
            {"uid": uid},
            {"$set": {k: _DEFAULT_USER[k] for k in _DEFAULT_USER if k not in doc}},
        )
    return doc


async def async_set_user_field(user_id: int, key: str, value: Any) -> None:
    col = _get_col()
    uid = int(user_id)
    await col.update_one(
        {"uid": uid},
        {"$set": {key: value}},
        upsert=True,
    )


async def async_get_hash(user_id: int) -> str:
    user = await async_get_user(user_id)
    return user.get("hash", "") or ""


async def async_get_all_user_ids() -> list:
    """Return every known user_id — used by /broadcast."""
    col  = _get_col()
    cur  = col.find({}, {"uid": 1, "_id": 0})
    ids  = [doc["uid"] async for doc in cur]
    return ids


async def async_remember_path(user_id: int, path: str) -> None:
    """Add a folder path to the user's known_paths list (dedup, max 20, no empty)."""
    if not path:
        return
    col  = _get_col()
    uid  = int(user_id)
    user = await async_get_user(uid)
    known = user.get("known_paths", [])
    if path in known:
        known.remove(path)
    known.insert(0, path)
    known = known[:20]
    await col.update_one({"uid": uid}, {"$set": {"known_paths": known}}, upsert=True)


async def async_get_default_path(user_id: int) -> str:
    user = await async_get_user(user_id)
    return user.get("default_path", "") or ""


# ── Sync shims — run the coroutine on the running event loop ──────────────────
# aiogram runs inside asyncio, so we use the running loop directly.

def _run(coro):
    """Run a coroutine from a sync context inside the running event loop."""
    try:
        loop = asyncio.get_running_loop()
        # We're inside an async context — schedule and wait
        import concurrent.futures
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=10)
    except RuntimeError:
        # No running loop — use asyncio.run
        return asyncio.run(coro)


def get_user(user_id: int) -> dict:
    return _run(async_get_user(user_id))


def set_user_field(user_id: int, key: str, value: Any) -> None:
    _run(async_set_user_field(user_id, key, value))


def get_hash(user_id: int) -> str:
    return _run(async_get_hash(user_id))


def get_default_path(user_id: int) -> str:
    return _run(async_get_default_path(user_id))
