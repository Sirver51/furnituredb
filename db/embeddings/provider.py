"""EmbeddingProvider interface + Gemini implementation.

See docs/db_strategy.md ("Call pattern: sync batchEmbedContents"): each input
(text doc or image) is its own `Content` in the request, so the API returns
one independent vector per input -- no fusion. Text and images share the same
vector space, so `embed_texts` and `embed_images` are interchangeable on the
storage/search side as long as `dim` matches.
"""

from __future__ import annotations

import os
import random
import time
from abc import ABC, abstractmethod

from google import genai
from google.genai import errors
from google.genai.types import Content, EmbedContentConfig, Part

RETRYABLE_CODES = {429, 500, 503}
RATE_LIMIT_WAIT_SECONDS = 60.0  # 429 is a per-minute quota; wait out the window


class EmbeddingProvider(ABC):
    model_id: str
    dim: int
    normalized: bool

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """One 768-dim vector per input string, same order."""

    @abstractmethod
    def embed_images(self, images: list[tuple[bytes, str]]) -> list[list[float]]:
        """One 768-dim vector per (image_bytes, mime_type) input, same order."""


class GeminiEmbeddingProvider(EmbeddingProvider):
    model_id = "gemini-embedding-2-preview"

    def __init__(self, dim: int = 768, batch_size: int = 25, max_retries: int = 8):
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.dim = dim
        self.normalized = True
        self._batch_size = batch_size
        self._max_retries = max_retries

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        contents = [Content(parts=[Part(text=t)]) for t in texts]
        return self._embed(contents)

    def embed_images(self, images: list[tuple[bytes, str]]) -> list[list[float]]:
        contents = [Content(parts=[Part.from_bytes(data=data, mime_type=mime)]) for data, mime in images]
        return self._embed(contents)

    def _embed(self, contents: list[Content]) -> list[list[float]]:
        results: list[list[float]] = []
        for i in range(0, len(contents), self._batch_size):
            chunk = contents[i : i + self._batch_size]
            results.extend(self._embed_chunk(chunk))
        return results

    def _embed_chunk(self, chunk: list[Content]) -> list[list[float]]:
        delay = 1.0
        for attempt in range(self._max_retries):
            try:
                resp = self._client.models.embed_content(
                    model=self.model_id,
                    contents=chunk,
                    config=EmbedContentConfig(output_dimensionality=self.dim),
                )
                return [e.values for e in resp.embeddings]
            except errors.APIError as exc:
                if exc.code not in RETRYABLE_CODES or attempt == self._max_retries - 1:
                    raise
                wait = RATE_LIMIT_WAIT_SECONDS * random.uniform(0.8, 1.3) if exc.code == 429 else delay
                print(f"  [{exc.code}] retrying in {wait:.0f}s (attempt {attempt + 1}/{self._max_retries})")
                time.sleep(wait)
                delay *= 2
        raise RuntimeError("unreachable")
