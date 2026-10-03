"""
Team and league logo cache.

Logos are downloaded once, shrunk to at most 160 px (the cards never draw them
larger) and kept in memory and on disk, so a restart does not download them
again. A logo that cannot be loaded is retried after a few hours; until then
the cards draw a coloured badge instead.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import time
from typing import Iterable

from PIL import Image

from uc_intg_sports.espn import EspnClient, SportsDataError

_LOG = logging.getLogger(__name__)

_MAX_SIZE = 160
_RETRY_AFTER = 6 * 3600
_MAX_MEMORY = 400  # logos kept in memory

_cache_dir: str | None = None
_memory: dict[str, Image.Image] = {}
_failed: dict[str, float] = {}
_lock = asyncio.Lock()


def set_cache_dir(path: str) -> None:
    """Use <config dir>/logos for the disk cache."""
    global _cache_dir  # pylint: disable=global-statement
    try:
        os.makedirs(path, exist_ok=True)
        _cache_dir = path
    except OSError as err:
        _LOG.warning("Logo disk cache disabled: %s", err)
        _cache_dir = None


def _file(url: str) -> str | None:
    if not _cache_dir:
        return None
    return os.path.join(_cache_dir, hashlib.sha1(url.encode()).hexdigest()[:20] + ".png")


def _shrink(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as src:
        img = src.convert("RGBA")
    img.thumbnail((_MAX_SIZE, _MAX_SIZE), Image.LANCZOS)
    bbox = img.getchannel("A").getbbox()  # trim transparent borders so logos line up
    return img.crop(bbox) if bbox else img


def _load_disk(url: str) -> Image.Image | None:
    path = _file(url)
    if not path or not os.path.exists(path):
        return None
    try:
        with Image.open(path) as src:
            return src.convert("RGBA")
    except OSError:
        return None


def _save_disk(url: str, img: Image.Image) -> None:
    path = _file(url)
    if not path:
        return
    try:
        img.save(path, format="PNG", optimize=True)
    except OSError as err:
        _LOG.debug("Could not cache logo %s: %s", url, err)


def _remember(url: str, img: Image.Image) -> None:
    if len(_memory) >= _MAX_MEMORY:
        _memory.pop(next(iter(_memory)))
    _memory[url] = img


async def _load(client: EspnClient, url: str) -> Image.Image | None:
    if url in _memory:
        return _memory[url]
    if time.monotonic() - _failed.get(url, -_RETRY_AFTER) < _RETRY_AFTER:
        return None
    img = await asyncio.to_thread(_load_disk, url)
    if img is None:
        try:
            data = await client.fetch_bytes(url)
            img = await asyncio.to_thread(_shrink, data)
            await asyncio.to_thread(_save_disk, url, img)
        except (SportsDataError, OSError, ValueError) as err:
            _LOG.debug("Logo unavailable %s: %s", url, err)
            _failed[url] = time.monotonic()
            return None
    _remember(url, img)
    return img


async def get_logos(client: EspnClient, urls: Iterable[str]) -> dict[str, Image.Image]:
    """Return the loaded logos for the given URLs (missing ones are left out)."""
    wanted = [url for url in dict.fromkeys(urls) if url]
    result: dict[str, Image.Image] = {}
    async with _lock:
        for url in wanted:
            img = await _load(client, url)
            if img is not None:
                result[url] = img
    return result


async def get_team_logo(client: EspnClient, dark: str, default: str) -> tuple[str, Image.Image | None]:
    """Prefer the dark-background logo, fall back to the default one."""
    for url in (dark, default):
        if not url:
            continue
        logos = await get_logos(client, [url])
        if url in logos:
            return url, logos[url]
    return default or dark, None
