from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import requests

from utils import normalize_text


def cosine_similarity(left: np.ndarray | list[float], right: np.ndarray | list[float]) -> float:
    left_arr = np.asarray(left, dtype=np.float32)
    right_arr = np.asarray(right, dtype=np.float32)
    if left_arr.size == 0 or right_arr.size == 0:
        return 0.0
    length = min(left_arr.shape[0], right_arr.shape[0])
    left_arr = left_arr[:length]
    right_arr = right_arr[:length]
    denom = float(np.linalg.norm(left_arr) * np.linalg.norm(right_arr))
    if denom == 0.0:
        return 0.0
    return float(np.dot(left_arr, right_arr) / denom)


class BaseEmbeddingProvider:
    dimension: int = 384

    def embed_text(self, text: str) -> np.ndarray:
        raise NotImplementedError

    def embed_texts(self, texts: list[str]) -> list[np.ndarray]:
        return [self.embed_text(text) for text in texts]


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, base_url: str, model: str, timeout: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def embed_text(self, text: str) -> np.ndarray:
        response = requests.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model, "prompt": text},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        vector = np.asarray(payload["embedding"], dtype=np.float32)
        self.dimension = int(vector.shape[0]) or self.dimension
        return vector


class SentenceTransformerEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        if hasattr(self.model, "get_embedding_dimension"):
            self.dimension = int(self.model.get_embedding_dimension())
        else:
            self.dimension = int(self.model.get_sentence_embedding_dimension())

    def embed_text(self, text: str) -> np.ndarray:
        vector = self.model.encode([text], normalize_embeddings=True)[0]
        return np.asarray(vector, dtype=np.float32)


class HashEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension

    def embed_text(self, text: str) -> np.ndarray:
        normalized = normalize_text(text)
        vector = np.zeros(self.dimension, dtype=np.float32)
        if not normalized:
            return vector
        for token in normalized.split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = float(np.linalg.norm(vector))
        if norm:
            vector /= norm
        return vector


class EmbeddingManager:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.provider = self._build_provider()

    def _build_provider(self) -> BaseEmbeddingProvider:
        mode = self.config.get("modo_embedding", "ollama")
        if mode == "ollama":
            try:
                return OllamaEmbeddingProvider(
                    self.config.get("ollama_url", "http://localhost:11434"),
                    self.config.get("modelo_embedding", "nomic-embed-text"),
                    int(self.config.get("timeout", 60)),
                )
            except Exception:
                return HashEmbeddingProvider()
        if mode == "sentence-transformers":
            try:
                return SentenceTransformerEmbeddingProvider(
                    self.config.get("modelo_embedding", "all-MiniLM-L6-v2")
                )
            except Exception:
                return HashEmbeddingProvider()
        return HashEmbeddingProvider()

    def embed_text(self, text: str) -> np.ndarray:
        try:
            return self.provider.embed_text(text)
        except Exception:
            self.provider = HashEmbeddingProvider()
            return self.provider.embed_text(text)

    def embed_texts(self, texts: list[str]) -> list[np.ndarray]:
        try:
            return self.provider.embed_texts(texts)
        except Exception:
            self.provider = HashEmbeddingProvider()
            return self.provider.embed_texts(texts)
