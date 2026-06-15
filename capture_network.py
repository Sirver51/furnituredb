"""
Reverse-engineering helper: opens a real browser, lets you interact with a
site by hand (search, scroll, paginate, open product pages, etc.), and logs
every XHR/fetch request + response to a JSON file for later analysis.

Usage:
    uv run python capture_network.py <url> <label> [--filter SUBSTRING] [--outdir DIR]

    <url>     Page to open first.
    <label>   Used for the output filename: <outdir>/<label>.json
    --filter  Only record requests whose URL contains SUBSTRING
              (e.g. "/api/" or "graphql"). Omit to capture everything.
    --outdir  Where to write <label>.json (default: captures/, relative to
              the current directory). Use this to save into a per-site
              folder, e.g. --outdir sites/homecentre/captures

While the browser is open, interact with the site as a normal user.
Press Enter in the terminal when you're done to stop recording and save.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Use the Chromium binaries downloaded into .venv (see .local-browsers)
# instead of playwright's default global cache.
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

from playwright.async_api import async_playwright


async def main(url: str, label: str, url_filter: str | None, outdir: Path) -> None:
    OUTPUT_DIR = outdir
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    tasks = []

    async def record(response):
        request = response.request
        if request.resource_type not in ("xhr", "fetch"):
            return
        if url_filter and url_filter not in request.url:
            return

        try:
            post_data = request.post_data
        except Exception:
            post_data = None

        entry = {
            "method": request.method,
            "url": request.url,
            "request_headers": await request.all_headers(),
            "post_data": post_data,
            "status": response.status,
            "response_headers": await response.all_headers(),
        }
        content_type = entry["response_headers"].get("content-type", "")
        if "json" in content_type or "text" in content_type:
            try:
                entry["body"] = await response.text()
            except Exception as e:
                entry["body_error"] = str(e)

        entries.append(entry)
        print(f"[{response.status}] {request.method} {request.url}")

    def on_response(response):
        tasks.append(asyncio.create_task(record(response)))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        page.on("response", on_response)

        await page.goto(url)

        print("\nBrowser is open. Interact with the site (search, scroll, "
              "paginate, click into items, etc).")
        print("Press Enter here when you're done to stop recording and save.\n")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, input)

        if tasks:
            await asyncio.gather(*tasks)

        await browser.close()

    out_path = OUTPUT_DIR / f"{label}.json"
    out_path.write_text(json.dumps(entries, indent=2))
    print(f"\nSaved {len(entries)} request/response entries to {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: uv run python capture_network.py <url> <label> [--filter SUBSTRING] [--outdir DIR]")
        sys.exit(1)

    url_arg = sys.argv[1]
    label_arg = sys.argv[2]
    filter_arg = None
    if "--filter" in sys.argv:
        filter_arg = sys.argv[sys.argv.index("--filter") + 1]

    outdir_arg = Path("captures")
    if "--outdir" in sys.argv:
        outdir_arg = Path(sys.argv[sys.argv.index("--outdir") + 1])

    asyncio.run(main(url_arg, label_arg, filter_arg, outdir_arg))
