"""Minimal aria2 JSON-RPC client for queueing image downloads.

The main crawlers run with polite (slow) pacing against each site's own
API/pages, but images live on (mostly) separate CDN hosts and can be
downloaded much faster. `run_crawl.py` starts an aria2c daemon in RPC mode;
each site crawler calls `add_download()` as soon as it discovers an image
URL - non-blocking, queued immediately.
"""

import subprocess
import time
from pathlib import Path

import httpx

RPC_URL = "http://localhost:6800/jsonrpc"
ARIA2C_EXE = "aria2c"  # resolved via PATH
REPO_ROOT = Path(__file__).resolve().parent.parent

# Detach the daemon from this process's console/job object on Windows, so it
# keeps running (and serving already-queued downloads) even if the crawler
# that launched it exits or its parent shell is torn down.
_DETACH_FLAGS = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

_client = httpx.Client(timeout=30)
_id_counter = 0


def _call(method, params=None, retries=3):
    global _id_counter
    _id_counter += 1
    payload = {
        "jsonrpc": "2.0",
        "id": str(_id_counter),
        "method": method,
        "params": params or [],
    }
    for attempt in range(retries):
        try:
            resp = _client.post(RPC_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            return data["result"]
        except httpx.TransportError:
            if attempt == retries - 1:
                raise
            time.sleep(1 + attempt)


def is_running() -> bool:
    try:
        _call("aria2.getVersion")
        return True
    except Exception:
        return False


def start_daemon(download_dir: Path, max_concurrent: int = 10):
    """Start the aria2c RPC daemon if not already running. Returns the Popen
    handle, or None if a daemon was already listening on RPC_URL."""
    if is_running():
        return None

    proc = subprocess.Popen(
        [
            ARIA2C_EXE,
            "--enable-rpc",
            "--rpc-listen-port=6800",
            f"--dir={download_dir}",
            f"--max-concurrent-downloads={max_concurrent}",
            "--continue=true",
            "--auto-file-renaming=false",
            "--quiet=true",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=_DETACH_FLAGS,
    )

    for _ in range(20):
        if is_running():
            break
        time.sleep(0.5)
    return proc


def add_download(url: str, dir: Path, out: str, max_conns: int = 4, headers: dict | None = None):
    """Queue a single-file download via aria2c. Skips (returns None) if the
    destination file already exists, for resumability across runs."""
    dest = Path(dir) / out
    if dest.exists():
        return None

    options = {
        "dir": str(dir),
        "out": out,
        "max-connection-per-server": str(max_conns),
        "continue": "true",
    }
    if headers:
        options["header"] = [f"{k}: {v}" for k, v in headers.items()]

    try:
        return _call("aria2.addUri", [[url], options])
    except httpx.TransportError:
        # Daemon likely died (or never started in this process) - restart and
        # retry once, but don't let a dead daemon crash an hours-long crawl.
        start_daemon(REPO_ROOT)
        try:
            return _call("aria2.addUri", [[url], options])
        except httpx.TransportError as e:
            print(f"  [warning] aria2 unreachable, skipping image queue: {url} ({e})")
            return None


def global_stat():
    return _call("aria2.getGlobalStat")


def active_count() -> int:
    stat = global_stat()
    return int(stat.get("numActive", 0)) + int(stat.get("numWaiting", 0))
