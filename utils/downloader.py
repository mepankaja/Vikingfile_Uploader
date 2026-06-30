"""
High-speed multithreaded HTTP downloader.
- Probes size via HEAD → Range GET → Content-Length fallback
- Parallel chunk download when size known and server supports Range
- Single-stream fallback for servers without Range support
"""
import aiohttp
import asyncio
import os
import shutil
import time
from typing import Optional, Callable
from config import TEMP_DIR

CHUNK_SIZE   = 1024 * 1024      # 1 MB read chunks (was 512 KB)
NUM_THREADS  = 16               # parallel range workers (was 6)
MIN_MT_SIZE  = 5 * 1024 * 1024 # multithread if >= 5 MB (was 10 MB)
PROG_INTERVAL = 0.5             # progress callback interval seconds (was 1.0)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NXTupBot/3.0)"}


async def _probe(session: aiohttp.ClientSession, url: str):
    """
    Determine file size and Range support.
    Strategy: HEAD first (cheapest), then Range GET, then give up.
    Returns (total_bytes_or_None, range_supported).
    """
    # 1. HEAD request — fastest, no body
    try:
        async with session.head(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status in (200, 206):
                cl = r.headers.get("Content-Length")
                ar = r.headers.get("Accept-Ranges", "")
                if cl:
                    return int(cl), ("bytes" in ar or r.status == 206)
    except Exception:
        pass

    # 2. Range GET bytes=0-0 — reveals total via Content-Range
    try:
        async with session.get(
            url,
            headers={**_HEADERS, "Range": "bytes=0-0"},
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            range_ok = r.status == 206
            cr = r.headers.get("Content-Range", "")
            if cr and "/" in cr:
                try:
                    total = int(cr.split("/")[-1])
                    return total, range_ok
                except ValueError:
                    pass
            cl = r.headers.get("Content-Length")
            if cl:
                return int(cl), range_ok
    except Exception:
        pass

    return None, False


async def _download_chunk(
    session: aiohttp.ClientSession,
    url: str,
    start: int,
    end: int,
    dest_path: str,
    part_index: int,
    progress_arr: list,
    lock: asyncio.Lock,
) -> None:
    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=600)
    async with session.get(
        url,
        headers={**_HEADERS, "Range": f"bytes={start}-{end}"},
        timeout=timeout,
        allow_redirects=True,
    ) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            async for chunk in r.content.iter_chunked(CHUNK_SIZE):
                f.write(chunk)
                async with lock:
                    progress_arr[part_index] += len(chunk)


async def _multithread_download(
    session: aiohttp.ClientSession,
    url: str,
    dest_path: str,
    total: int,
    progress_cb: Optional[Callable],
) -> int:
    chunk_size = (total + NUM_THREADS - 1) // NUM_THREADS
    part_dir   = dest_path + ".parts"
    os.makedirs(part_dir, exist_ok=True)

    ranges = []
    for i in range(NUM_THREADS):
        start = i * chunk_size
        end   = min(start + chunk_size - 1, total - 1)
        if start > total - 1:
            break
        ranges.append((start, end))

    progress_arr = [0] * len(ranges)
    lock         = asyncio.Lock()
    start_time   = time.time()
    last_cb      = [0.0]
    done_flag    = [False]

    async def _progress_loop():
        while not done_flag[0]:
            await asyncio.sleep(PROG_INTERVAL)
            if not progress_cb:
                continue
            now = time.time()
            if now - last_cb[0] < PROG_INTERVAL:
                continue
            last_cb[0] = now
            done    = sum(progress_arr)
            elapsed = now - start_time
            speed   = done / elapsed if elapsed > 0 else 0
            await progress_cb(done, total, speed, elapsed)

    progress_task = asyncio.create_task(_progress_loop())
    try:
        tasks = [
            _download_chunk(
                session, url, start, end,
                os.path.join(part_dir, f"part_{i:04d}"),
                i, progress_arr, lock,
            )
            for i, (start, end) in enumerate(ranges)
        ]
        await asyncio.gather(*tasks)
    finally:
        done_flag[0] = True
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

    with open(dest_path, "wb") as out:
        for i in range(len(ranges)):
            part_path = os.path.join(part_dir, f"part_{i:04d}")
            with open(part_path, "rb") as pf:
                shutil.copyfileobj(pf, out, CHUNK_SIZE)

    shutil.rmtree(part_dir, ignore_errors=True)

    downloaded = sum(progress_arr)
    if progress_cb:
        elapsed = time.time() - start_time
        speed   = downloaded / elapsed if elapsed > 0 else 0
        await progress_cb(downloaded, total, speed, elapsed)

    return downloaded


async def _single_stream_download(
    session: aiohttp.ClientSession,
    url: str,
    dest_path: str,
    total: int,
    progress_cb: Optional[Callable],
) -> int:
    downloaded = 0
    start      = time.time()
    last_cb    = 0.0

    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=600)
    async with session.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True) as r:
        r.raise_for_status()
        if not total:
            cl = r.headers.get("Content-Length")
            total = int(cl) if cl else 0

        with open(dest_path, "wb") as f:
            async for chunk in r.content.iter_chunked(CHUNK_SIZE):
                f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if progress_cb and (now - last_cb) >= PROG_INTERVAL:
                    last_cb = now
                    elapsed = now - start
                    speed   = downloaded / elapsed if elapsed > 0 else 0
                    await progress_cb(downloaded, total, speed, elapsed)

    if progress_cb and downloaded > 0:
        elapsed = time.time() - start
        speed   = downloaded / elapsed if elapsed > 0 else 0
        await progress_cb(downloaded, total, speed, elapsed)

    return downloaded


async def download_file(
    url: str,
    dest_path: str,
    progress_cb: Optional[Callable] = None,
) -> int:
    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)

    # More connections for parallel chunks + DNS cache
    connector = aiohttp.TCPConnector(
        limit=NUM_THREADS + 8,
        limit_per_host=NUM_THREADS + 4,
        ttl_dns_cache=600,
        enable_cleanup_closed=True,
    )
    timeout = aiohttp.ClientTimeout(total=None, connect=30)

    async with aiohttp.ClientSession(
        timeout=timeout, connector=connector, headers=_HEADERS
    ) as session:
        total, range_ok = await _probe(session, url)

        if range_ok and total and total >= MIN_MT_SIZE:
            return await _multithread_download(session, url, dest_path, total, progress_cb)
        else:
            return await _single_stream_download(session, url, dest_path, total or 0, progress_cb)


def get_filename_from_url(url: str) -> str:
    path = url.split("?")[0].rstrip("/")
    name = path.split("/")[-1].split("#")[0]
    return name if name else "file"


def get_temp_path(filename: str, subdir: str = "") -> str:
    base = os.path.join(TEMP_DIR, subdir) if subdir else TEMP_DIR
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, filename)
