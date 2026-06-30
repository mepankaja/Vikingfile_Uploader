"""
Global registry of running asyncio tasks per user.
Allows cancel buttons to actually kill the background task.
"""
import asyncio
from typing import Dict, Optional

_tasks: Dict[str, asyncio.Task] = {}


def register(key: str, task: asyncio.Task):
    """Register a task under a key (e.g. 'upload_123456' or 'zip_123456')."""
    # Cancel any existing task for this key first
    cancel(key)
    _tasks[key] = task


def cancel(key: str) -> bool:
    """Cancel the task for key. Returns True if a task was found and cancelled."""
    task = _tasks.pop(key, None)
    if task and not task.done():
        task.cancel()
        return True
    return False


def done(key: str):
    """Remove a completed task from the registry."""
    _tasks.pop(key, None)


def cancel_all_for_user(user_id: int):
    """Cancel all tasks belonging to a user."""
    keys = [k for k in list(_tasks.keys()) if k.endswith(f"_{user_id}")]
    for k in keys:
        cancel(k)
