"""
VikingFile API wrapper.

Official API: https://vikingfile.com/api

Upload flow (legacy, for files under ~5GB):
  1. GET  https://vikingfile.com/api/get-server  →  {"server": "https://upload.vikingfile.com"}
  2. POST <server>  multipart fields in order:
       user  (required, empty string for anonymous)
       path  (optional)
       file  (required, binary)

Remote link upload:
  POST <server>  multipart fields:
       user  (required, empty string for anonymous)
       link  (required)
       name  (optional)
       path  (optional)

Key notes:
  - "user" is REQUIRED by the API — always send it, even as empty string for anonymous
  - Text fields (user, path) MUST come before the file/link binary field
  - Response always contains "url" and "hash" fields on success
  - VikingFile returns HTTP 200 even for errors: check "error" key in response
"""
import aiohttp
import asyncio
import json
import os
import time
from typing import Optional, Callable

VF_API_BASE = "https://vikingfile.com"
HEADERS     = {"User-Agent": "NXTupBot/3.0"}

CONNECT_TIMEOUT = 30
READ_TIMEOUT    = 3600   # 1 hour — remote fetches can be very slow


def make_file_url(file_hash: str) -> str:
    return f"{VF_API_BASE}/f/{file_hash}"


def _extract_url(data: dict) -> str:
    """Extract download URL from response — prefer canonical /f/<hash> form."""
    file_hash = data.get("hash") or data.get("fileHash") or ""
    if file_hash:
        return make_file_url(file_hash)
    for field in ("url", "link", "fileUrl", "downloadUrl", "download_url", "file_url"):
        val = data.get(field, "")
        if val and str(val).startswith("http"):
            return val
    return ""


def _parse_response(raw: str, status: int) -> dict:
    """Parse VikingFile JSON response — strip any junk prefix."""
    text  = raw.strip()
    start = text.find("{")
    if start == -1:
        raise RuntimeError(f"VikingFile non-JSON (HTTP {status}): {text[:300]}")
    try:
        data = json.loads(text[start:])
        for key in ("size", "numberParts", "partSize"):
            if key in data:
                try:
                    data[key] = int(data[key])
                except (ValueError, TypeError):
                    data[key] = 0
        data["_url"] = _extract_url(data)
        return data
    except json.JSONDecodeError as e:
        raise RuntimeError(f"VikingFile bad JSON (HTTP {status}): {text[:300]}") from e


async def _get_upload_server(sess: aiohttp.ClientSession) -> str:
    """Resolve the upload server URL."""
    async with sess.get(f"{VF_API_BASE}/api/get-server", headers=HEADERS) as r:
        if r.status != 200:
            raise RuntimeError(f"VikingFile get-server HTTP {r.status}")
        srv_data = json.loads((await r.text()).strip())
    server_url = srv_data.get("server")
    if not server_url:
        raise RuntimeError(f"get-server gave no server key: {srv_data}")
    return server_url


# ── File upload ────────────────────────────────────────────────────────────────

_UL_CHUNK    = 512 * 1024   # 512 KB upload chunks — sweet spot for aiohttp streaming
_UL_PROG_INT = 0.5          # progress callback interval seconds


async def upload_file(
    file_path: str,
    name: str,
    vf_hash: str = "",
    path: str = "",
    progress_cb: Optional[Callable] = None,
) -> dict:
    """
    Upload a file to VikingFile via multipart/form-data.

    Fields order: user → path → file  (server parses sequentially).
    Progress is tracked by a background task reading fh.tell() against
    the actual file size — reliable and transport-safe.
    """
    file_size = os.path.getsize(file_path)
    start_t   = [time.monotonic()]
    last_cb   = [0.0]
    stop_ev   = asyncio.Event()

    async def _progress_loop(fh):
        """Poll file position every _UL_PROG_INT seconds while upload is running."""
        while not stop_ev.is_set():
            await asyncio.sleep(_UL_PROG_INT)
            try:
                pos = fh.tell()
            except Exception:
                break
            now = time.monotonic()
            if progress_cb and (now - last_cb[0]) >= _UL_PROG_INT:
                last_cb[0] = now
                await progress_cb(pos, file_size)

    connector = aiohttp.TCPConnector(
        limit=4,
        ttl_dns_cache=600,
        enable_cleanup_closed=True,
    )
    timeout = aiohttp.ClientTimeout(total=None, connect=CONNECT_TIMEOUT)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as sess:
        server_url = await _get_upload_server(sess)

        with open(file_path, "rb") as fh:
            form = aiohttp.FormData()
            # user and path MUST be added before file (server parses sequentially)
            form.add_field("user", vf_hash)
            if path:
                form.add_field("path", path)
            form.add_field(
                "file", fh,
                filename=name,
                content_type="application/octet-stream",
            )

            prog_task = asyncio.create_task(_progress_loop(fh))
            try:
                async with sess.post(server_url, data=form, headers=HEADERS) as r:
                    raw    = await r.text()
                    status = r.status
            finally:
                stop_ev.set()
                prog_task.cancel()
                try:
                    await prog_task
                except asyncio.CancelledError:
                    pass

    # Final progress tick
    if progress_cb:
        await progress_cb(file_size, file_size)

    if status not in (200, 201):
        raise RuntimeError(f"VikingFile upload HTTP {status}: {raw[:300]}")

    result = _parse_response(raw, status)

    if "error" in result:
        raise RuntimeError(f"VikingFile error: {result['error']}")

    return result


async def upload_file_legacy(file_path, name, user_hash="", path="", progress_cb=None):
    return await upload_file(file_path, name, user_hash, path, progress_cb)


async def upload_file_multipart(file_path, name, user_hash="", path="", progress_cb=None):
    return await upload_file(file_path, name, user_hash, path, progress_cb)


# ── Remote link upload ─────────────────────────────────────────────────────────

async def upload_remote_link(
    link: str,
    user_hash: str = "",
    name: str = "",
    path: str = "",
    progress_cb=None,   # optional async callable(current, total, pct_str, filename)
) -> dict:
    """
    Tell VikingFile to fetch a URL on their servers.

    Per API spec: user is REQUIRED (empty string = anonymous).
    Field order: user → link → name → path.
    Uses a long read timeout — VikingFile may take minutes to fetch large files.
    """
    # Use a generous read timeout — VikingFile fetches the file on their end
    timeout = aiohttp.ClientTimeout(
        total=None,
        connect=CONNECT_TIMEOUT,
        sock_read=READ_TIMEOUT,
    )

    async with aiohttp.ClientSession(timeout=timeout) as sess:
        server_url = await _get_upload_server(sess)

        form = aiohttp.FormData()
        # user REQUIRED per API, always send (empty = anonymous)
        # user BEFORE link — same sequential parsing rule
        form.add_field("user", user_hash)
        form.add_field("link", link)
        if name:
            form.add_field("name", name)
        if path:
            form.add_field("path", path)

        async with sess.post(server_url, data=form, headers=HEADERS) as r:
            status = r.status
            # VikingFile streams NDJSON progress lines then a final result line.
            # Read line by line and keep only the last valid JSON object.
            raw_lines = []
            async for raw_line in r.content:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                raw_lines.append(line)
                if progress_cb:
                    try:
                        pd = json.loads(line)
                        if "progress" in pd and "current" in pd and "total" in pd:
                            await progress_cb(
                                int(pd["current"]),
                                int(pd["total"]),
                                str(pd.get("progress", "")),
                                str(pd.get("name", "")),
                            )
                    except Exception:
                        pass

    if status not in (200, 201):
        raise RuntimeError(f"VikingFile remote upload HTTP {status}: {raw_lines[-1][:300] if raw_lines else 'no response'}")

    if not raw_lines:
        raise RuntimeError("VikingFile remote upload: empty response")

    # Progress lines look like: {"progress":"0.1%","current":...,"total":...,"name":...}
    # Final result line has "hash" and/or "url" — find it by scanning from the end
    result = None
    for line in reversed(raw_lines):
        try:
            data = json.loads(line)
            # Skip pure progress lines (no hash/url/error, only progress/current/total/name)
            if "progress" in data and "hash" not in data and "url" not in data and "error" not in data:
                continue
            result = data
            break
        except json.JSONDecodeError:
            continue

    if result is None:
        # Fall back to last line
        result = _parse_response(raw_lines[-1], status)

    # Normalise numeric fields that VikingFile may return as strings
    for key in ("size", "current", "total", "numberParts", "partSize"):
        if key in result:
            try:
                result[key] = int(result[key])
            except (ValueError, TypeError):
                result[key] = 0

    result["_url"] = _extract_url(result)

    if "error" in result:
        raise RuntimeError(f"VikingFile error: {result['error']}")

    return result


# ── List / manage files ────────────────────────────────────────────────────────

async def list_files(user_hash: str, page: int = 1, path: str = "") -> dict:
    timeout = aiohttp.ClientTimeout(total=None, connect=CONNECT_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        form = {"user": user_hash, "page": str(page)}
        if path:
            form["path"] = path
        async with sess.post(
            f"{VF_API_BASE}/api/list-files", data=form, headers=HEADERS
        ) as r:
            raw    = await r.text()
            status = r.status
    data = _parse_response(raw, status)
    for f in data.get("files", []):
        if "hash" in f and not f.get("_url"):
            f["_url"] = make_file_url(f["hash"])
    return data


async def delete_file(file_hash: str, user_hash: str) -> dict:
    timeout = aiohttp.ClientTimeout(total=None, connect=CONNECT_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        async with sess.post(
            f"{VF_API_BASE}/api/delete-file",
            data={"hash": file_hash, "user": user_hash},
            headers=HEADERS,
        ) as r:
            return _parse_response(await r.text(), r.status)


async def rename_file(file_hash: str, user_hash: str, new_name: str) -> dict:
    timeout = aiohttp.ClientTimeout(total=None, connect=CONNECT_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        async with sess.post(
            f"{VF_API_BASE}/api/rename-file",
            data={"hash": file_hash, "user": user_hash, "filename": new_name},
            headers=HEADERS,
        ) as r:
            return _parse_response(await r.text(), r.status)


async def check_file(file_hash: str) -> dict:
    timeout = aiohttp.ClientTimeout(total=None, connect=CONNECT_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        async with sess.post(
            f"{VF_API_BASE}/api/check-file",
            data={"hash": file_hash},
            headers=HEADERS,
        ) as r:
            return _parse_response(await r.text(), r.status)
