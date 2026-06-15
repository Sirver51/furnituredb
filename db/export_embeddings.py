"""Snapshot vec_text/vec_image (+ embedding_state hashes) to JSONL files as a
cache/backup -- avoids re-calling the embedding API if the sqlite-vec tables
ever need to be rebuilt (e.g. dimension/model change, DB corruption).

Usage: uv run python -m db.export_embeddings
Output: data/embeddings/{text,image}.jsonl (overwritten each run -- a full
snapshot, not an incremental log) + a {text,image}.meta.json with model/dim/count.

To restore: for each line, base64-decode `vector_b64` to float32 bytes and
INSERT into the corresponding vec0 table (product_id/image_id = ref_id) plus
embedding_state (kind, ref_id, content_hash = hash).
"""

import base64
import json
from pathlib import Path

from db.connection import get_connection

ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / "data" / "embeddings"


def _export(con, kind: str, table: str, id_column: str, out_path: Path) -> int:
    rows = con.execute(
        f"SELECT v.{id_column}, v.embedding, s.content_hash "
        f"FROM {table} v JOIN embedding_state s ON s.kind = ? AND s.ref_id = v.{id_column}",
        (kind,),
    ).fetchall()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for ref_id, embedding, content_hash in rows:
            record = {
                "ref_id": ref_id,
                "hash": content_hash,
                "vector_b64": base64.b64encode(embedding).decode("ascii"),
            }
            f.write(json.dumps(record) + "\n")
    return len(rows)


def main() -> None:
    con = get_connection()

    meta = {row[0]: {"model": row[1], "dim": row[2]} for row in con.execute(
        "SELECT modality, model, dim FROM embedding_meta"
    )}

    n_text = _export(con, "text", "vec_text", "product_id", OUT_DIR / "text.jsonl")
    n_image = _export(con, "image", "vec_image", "image_id", OUT_DIR / "image.jsonl")

    for kind, n in (("text", n_text), ("image", n_image)):
        with open(OUT_DIR / f"{kind}.meta.json", "w", encoding="utf-8") as f:
            json.dump({**meta.get(kind, {}), "count": n}, f, indent=2)

    print(f"text: {n_text} vectors -> {OUT_DIR / 'text.jsonl'}")
    print(f"image: {n_image} vectors -> {OUT_DIR / 'image.jsonl'}")

    con.close()


if __name__ == "__main__":
    main()
