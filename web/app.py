"""FastAPI app: search UI + JSON API over the (read-only) furniture.db.

Run with: uv run uvicorn web.app:app --reload
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from web import repo
from web.db import get_connection
from web.images import resolve_image_path
from web.search import SearchService

load_dotenv()

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Furniture DB Search")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@contextmanager
def db():
    con = get_connection()
    try:
        yield con
    finally:
        con.close()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/meta")
def get_meta():
    with db() as con:
        sites = [r[0] for r in con.execute("SELECT DISTINCT site FROM product ORDER BY site")]
        price_min, price_max = con.execute(
            "SELECT MIN(price), MAX(price) FROM product WHERE price IS NOT NULL"
        ).fetchone()
        product_count = con.execute("SELECT COUNT(*) FROM product").fetchone()[0]
        embeddings = SearchService(con).embeddings_available()

    return {
        "sites": sites,
        "price_min": price_min,
        "price_max": price_max,
        "product_count": product_count,
        "embeddings": embeddings,
    }


@app.post("/api/search")
def search(
    q: str | None = Form(None),
    image: UploadFile | None = File(None),
    site: str | None = Form(None),
    price_min: float | None = Form(None),
    price_max: float | None = Form(None),
    k: int = Form(40),
):
    q = (q or "").strip() or None
    has_image = image is not None and image.filename
    if q is None and not has_image:
        raise HTTPException(400, "Provide q and/or image")

    with db() as con:
        service = SearchService(con)
        # v1: an uploaded image takes priority over q (search_image already
        # covers cross-modal semantic matching). Combining both is a later
        # fusion-tuning task.
        if has_image:
            data = image.file.read()
            mime = image.content_type or "image/jpeg"
            ids, info, similarities = service.search_image(data, mime, k=k)
        else:
            ids, info, similarities = service.search_text(q, k=k)

        cards = repo.get_cards(
            con, ids, site=site or None, price_min=price_min, price_max=price_max, similarities=similarities
        )

    return {"results": cards, "info": info}


@app.get("/api/product/{product_id}")
def get_product(product_id: int):
    with db() as con:
        product = repo.get_product(con, product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    return product


@app.get("/api/product/{product_id}/neighbors")
def get_neighbors(product_id: int, mode: str = "semantic", k: int = 12):
    if mode not in ("semantic", "visual"):
        raise HTTPException(400, "mode must be 'semantic' or 'visual'")
    with db() as con:
        return repo.neighbors(con, product_id, mode, k)


@app.get("/img/{image_id}")
def get_image(image_id: int):
    with db() as con:
        path = resolve_image_path(con, image_id)
    if path is None:
        raise HTTPException(404, "Image not found")
    return FileResponse(path)
