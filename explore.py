"""
Automated exploration helper (no manual interaction required).

Loads a URL headlessly, optionally scrolls/clicks, captures all XHR/fetch
request+response pairs, and saves a screenshot so we can visually inspect
the page.

Usage:
    uv run python explore.py <url> <label> [--scroll N] [--filter SUBSTRING] [--outdir DIR]

    --outdir DIR  Where to write <label>.json / <label>.png (default: captures/,
                   relative to the current directory). Use this to save into a
                   per-site folder, e.g. --outdir sites/homecentre/captures
"""

import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

from playwright.async_api import async_playwright


async def main(url: str, label: str, scroll: int, url_filter: str | None, outdir: Path) -> None:
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
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        page.on("response", on_response)

        try:
            await page.goto(url, wait_until="networkidle", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(4000)

        for i in range(scroll):
            await page.mouse.wheel(0, 1800)
            await page.wait_for_timeout(1200)

        await asyncio.gather(*tasks)

        await page.screenshot(path=str(OUTPUT_DIR / f"{label}.png"), full_page=False)

    (OUTPUT_DIR / f"{label}.json").write_text(json.dumps(entries, indent=2))
    print(f"\nSaved {len(entries)} entries to {OUTPUT_DIR / f'{label}.json'}")
    print(f"Saved screenshot to {OUTPUT_DIR / f'{label}.png'}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: uv run python explore.py <url> <label> [--scroll N] [--filter SUBSTRING] [--outdir DIR]")
        sys.exit(1)

    url_arg = sys.argv[1]
    label_arg = sys.argv[2]

    scroll_arg = 0
    if "--scroll" in sys.argv:
        scroll_arg = int(sys.argv[sys.argv.index("--scroll") + 1])

    filter_arg = None
    if "--filter" in sys.argv:
        filter_arg = sys.argv[sys.argv.index("--filter") + 1]

    outdir_arg = Path("captures")
    if "--outdir" in sys.argv:
        outdir_arg = Path(sys.argv[sys.argv.index("--outdir") + 1])

    asyncio.run(main(url_arg, label_arg, scroll_arg, filter_arg, outdir_arg))
