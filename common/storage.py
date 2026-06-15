"""Shared storage helpers: sharded product paths, JSON I/O, resumable crawl state."""

import json
from pathlib import Path


def product_path(raw_dir: Path, key) -> Path:
    """raw/products/<key[:2]>/<key>.json - sharded by first 2 chars of the key."""
    key = str(key)
    shard = key[:2] if len(key) >= 2 else f"_{key}"
    return Path(raw_dir) / "products" / shard / f"{key}.json"


def product_exists(raw_dir: Path, key) -> bool:
    return product_path(raw_dir, key).exists()


def save_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, record) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


class CrawlState:
    """Tracks which category keys have been fully processed, for resumable crawls.

    Stored as JSON: {"categories_done": ["<key>", ...]}. Call `mark_done(key)`
    after a category's listing + detail + image-queue work is complete; a
    re-run of the crawl script will skip categories where `is_done(key)`.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = load_json(self.path, {"categories_done": []})
        self.data.setdefault("categories_done", [])

    def is_done(self, key) -> bool:
        return str(key) in self.data["categories_done"]

    def mark_done(self, key) -> None:
        key = str(key)
        if key not in self.data["categories_done"]:
            self.data["categories_done"].append(key)
        self.save()

    def save(self) -> None:
        save_json(self.path, self.data)
