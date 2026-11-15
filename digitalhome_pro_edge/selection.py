# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D-LAB-5
"""selection.py — what the page has open (a workspace, an item), for the chat."""

from __future__ import annotations

import threading
from typing import Dict

_lock = threading.Lock()
_current: Dict[str, str] = {}


def set(workspace: str = "", item: str = "") -> Dict[str, str]:  # noqa: A001 — module API
    with _lock:
        _current.clear()
        if workspace:
            _current["workspace"] = workspace
        if item:
            _current["item"] = item
        return dict(_current)


def get() -> Dict[str, str]:
    with _lock:
        return dict(_current)


def key():
    got = get()
    return f"{got.get('workspace', '')}/{got.get('item', '')}" if got else None
