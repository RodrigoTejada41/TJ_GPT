from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from embeddings import cosine_similarity

try:
    import faiss  # type: ignore

    HAS_FAISS = True
except Exception:
    HAS_FAISS = False


class VectorStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.directory / "metadata.json"
        self.vectors_path = self.directory / "vectors.npy"
        self.manifest_path = self.directory / "manifest.json"
        self.faiss_path = self.directory / "index.faiss"
        self.metadata: list[dict[str, Any]] = []
        self.vectors: np.ndarray | None = None
        self.dimension = 0
        self.manifest: dict[str, Any] = {}
        self.index = None
        self.load()

    def is_loaded(self) -> bool:
        return bool(self.metadata)

    def reset(self) -> None:
        self.metadata = []
        self.vectors = None
        self.dimension = 0
        self.index = None
        for path in (self.metadata_path, self.vectors_path, self.manifest_path, self.faiss_path):
            path.unlink(missing_ok=True)
        self.save()

    def count_entries(self) -> int:
        return len(self.metadata)

    def index_map(self) -> dict[str, int]:
        return {
            item.get("chunk_id", ""): idx
            for idx, item in enumerate(self.metadata)
            if item.get("chunk_id")
        }

    def build(self, chunks: list[Any], embeddings: list[np.ndarray]) -> None:
        usable = min(len(chunks), len(embeddings))
        self.metadata = [self._chunk_metadata(chunk) for chunk in chunks[:usable]]
        self.vectors = np.vstack([np.asarray(vec, dtype=np.float32) for vec in embeddings[:usable]]) if usable else None
        self.dimension = int(self.vectors.shape[1]) if self.vectors is not None and self.vectors.size else 0
        self._rebuild_index()
        self.save()

    def replace_entries(
        self,
        metadata: list[dict[str, Any]],
        vectors: list[np.ndarray],
        manifest: dict[str, Any] | None = None,
    ) -> None:
        self.metadata = metadata
        self.vectors = np.vstack([np.asarray(vec, dtype=np.float32) for vec in vectors]) if vectors else None
        self.dimension = int(self.vectors.shape[1]) if self.vectors is not None and self.vectors.size else 0
        if manifest is not None:
            self.manifest = dict(manifest)
        self._rebuild_index()
        self.save()

    def append_entries(
        self,
        metadata: list[dict[str, Any]],
        vectors: list[np.ndarray],
        manifest: dict[str, Any] | None = None,
    ) -> None:
        if not metadata or not vectors:
            if manifest is not None:
                self.manifest = dict(manifest)
                self.save()
            return
        new_vectors = np.vstack([np.asarray(vec, dtype=np.float32) for vec in vectors])
        if self.vectors is None or not self.vectors.size:
            self.metadata = list(metadata)
            self.vectors = new_vectors
        else:
            self.metadata.extend(metadata)
            self.vectors = np.vstack([self.vectors, new_vectors])
        self.dimension = int(self.vectors.shape[1]) if self.vectors is not None and self.vectors.size else 0
        if manifest is not None:
            self.manifest = dict(manifest)
        self._rebuild_index()
        self.save()

    def query(self, embedding: np.ndarray, top_k: int = 5) -> list[dict[str, Any]]:
        if not self.metadata:
            return []
        query = self._match_dimension(np.asarray(embedding, dtype=np.float32))
        if HAS_FAISS and self.index is not None:
            scores, indices = self.index.search(query.reshape(1, -1), top_k)
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx < 0 or idx >= len(self.metadata):
                    continue
                item = dict(self.metadata[idx])
                item["score"] = float(score)
                results.append(item)
            return results

        if self.vectors is None:
            return []

        matrix = self._normalized_vectors()
        query_norm = query / max(np.linalg.norm(query), 1e-8)
        scores = matrix @ query_norm
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            item = dict(self.metadata[int(idx)])
            item["score"] = float(scores[int(idx)])
            results.append(item)
        return results

    def load(self) -> None:
        if self.metadata_path.exists():
            with self.metadata_path.open("r", encoding="utf-8") as handle:
                self.metadata = json.load(handle)
        if self.vectors_path.exists():
            self.vectors = np.load(self.vectors_path)
            self.dimension = int(self.vectors.shape[1]) if self.vectors.ndim == 2 and self.vectors.size else 0
        if self.manifest_path.exists():
            with self.manifest_path.open("r", encoding="utf-8") as handle:
                self.manifest = json.load(handle)
        if HAS_FAISS and self.faiss_path.exists():
            self.index = faiss.read_index(str(self.faiss_path))
            if self.dimension == 0:
                self.dimension = int(getattr(self.index, "d", 0))
        elif self.vectors is not None and self.vectors.size:
            self._rebuild_index()

    def save(self) -> None:
        with self.metadata_path.open("w", encoding="utf-8") as handle:
            json.dump(self.metadata, handle, indent=2, ensure_ascii=False)
        if self.vectors is not None:
            np.save(self.vectors_path, self.vectors)
        with self.manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(self.manifest, handle, indent=2, ensure_ascii=False)
        if HAS_FAISS and self.index is not None:
            faiss.write_index(self.index, str(self.faiss_path))

    def set_manifest(self, manifest: dict[str, Any]) -> None:
        self.manifest = dict(manifest)
        self.save()

    def manifest_matches(self, manifest: dict[str, Any]) -> bool:
        return all(self.manifest.get(key) == value for key, value in manifest.items())

    def _rebuild_index(self) -> None:
        self.index = None
        if self.vectors is None or not self.vectors.size:
            return
        normalized = self._normalized_vectors()
        if HAS_FAISS:
            self.index = faiss.IndexFlatIP(int(normalized.shape[1]))
            self.index.add(normalized.astype(np.float32))
        self.vectors = normalized.astype(np.float32)

    def _normalized_vectors(self) -> np.ndarray:
        if self.vectors is None or not self.vectors.size:
            return np.zeros((0, 0), dtype=np.float32)
        vectors = self.vectors.astype(np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return vectors / norms

    def _match_dimension(self, query: np.ndarray) -> np.ndarray:
        target_dim = self.dimension
        if target_dim == 0 and self.index is not None:
            target_dim = int(getattr(self.index, "d", 0))
        if target_dim == 0:
            return query
        current_dim = int(query.shape[0])
        if current_dim == target_dim:
            return query
        if current_dim > target_dim:
            return query[:target_dim]
        padded = np.zeros(target_dim, dtype=np.float32)
        padded[:current_dim] = query
        return padded

    def _chunk_metadata(self, chunk: Any) -> dict[str, Any]:
        if hasattr(chunk, "__dict__"):
            return {
                "chunk_id": getattr(chunk, "chunk_id", ""),
                "file_name": getattr(chunk, "file_name", ""),
                "path": getattr(chunk, "path", ""),
                "text": getattr(chunk, "text", ""),
                "chunk_index": int(getattr(chunk, "chunk_index", 0)),
                "metadata": getattr(chunk, "metadata", {}),
            }
        return dict(chunk)
