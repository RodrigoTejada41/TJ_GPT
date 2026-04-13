from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from embeddings import cosine_similarity
from utils import normalize_text


class ChatDatabase:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS historico (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pergunta TEXT NOT NULL,
                    pergunta_normalizada TEXT NOT NULL,
                    resposta TEXT NOT NULL,
                    categoria TEXT DEFAULT 'geral',
                    data TEXT DEFAULT (datetime('now')),
                    origem TEXT DEFAULT 'llm_direto',
                    pergunta_embedding BLOB,
                    referencia_resposta TEXT
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_semantico (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pergunta TEXT NOT NULL,
                    pergunta_normalizada TEXT NOT NULL UNIQUE,
                    embedding BLOB NOT NULL,
                    referencia_resposta TEXT,
                    data TEXT DEFAULT (datetime('now'))
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hist_norm ON historico(pergunta_normalizada)"
            )

    def close(self) -> None:
        self.conn.close()

    def save_interaction(
        self,
        question: str,
        answer: str,
        category: str = "geral",
        origin: str = "llm_direto",
        question_embedding: np.ndarray | None = None,
        reference_response: str | None = None,
        store_cache: bool = True,
    ) -> None:
        normalized = normalize_text(question)
        blob = self._to_blob(question_embedding) if question_embedding is not None else None
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO historico
                (pergunta, pergunta_normalizada, resposta, categoria, origem, pergunta_embedding, referencia_resposta)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (question, normalized, answer, category, origin, blob, reference_response),
            )
            if blob is not None and store_cache:
                self.conn.execute(
                    """
                    INSERT INTO cache_semantico
                    (pergunta, pergunta_normalizada, embedding, referencia_resposta)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(pergunta_normalizada) DO UPDATE SET
                        pergunta=excluded.pergunta,
                        embedding=excluded.embedding,
                        referencia_resposta=excluded.referencia_resposta,
                        data=datetime('now')
                    """,
                    (question, normalized, blob, reference_response or answer),
                )

    def list_history(self, limit: int = 100) -> list[dict[str, Any]]:
        cursor = self.conn.execute(
            """
            SELECT id, pergunta, resposta, categoria, data, origem
            FROM historico
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def clear(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM historico")
            self.conn.execute("DELETE FROM cache_semantico")

    def count_history(self) -> int:
        cursor = self.conn.execute("SELECT COUNT(*) FROM historico")
        return int(cursor.fetchone()[0])

    def find_similar_questions(
        self,
        question: str,
        threshold: float = 0.85,
        limit: int = 5,
        question_embedding: np.ndarray | None = None,
    ) -> list[dict[str, Any]]:
        normalized = normalize_text(question)
        candidates = self.conn.execute(
            """
            SELECT id, pergunta, pergunta_normalizada, resposta, referencia_resposta, pergunta_embedding
            FROM historico
            WHERE pergunta_normalizada LIKE ?
            ORDER BY id DESC
            LIMIT 100
            """,
            (f"%{normalized[:32]}%",),
        ).fetchall()
        if not candidates:
            candidates = self.conn.execute(
                """
                SELECT id, pergunta, pergunta_normalizada, resposta, referencia_resposta, pergunta_embedding
                FROM historico
                ORDER BY id DESC
                LIMIT 200
                """
            ).fetchall()
        if not candidates:
            return []
        if question_embedding is None:
            return [
                dict(row)
                for row in candidates[:limit]
                if self._text_similarity(normalized, row["pergunta_normalizada"]) >= threshold
            ]
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in candidates:
            stored_blob = row["pergunta_embedding"]
            if not stored_blob:
                continue
            stored = self._from_blob(stored_blob)
            score = cosine_similarity(question_embedding, stored)
            if score >= threshold:
                scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [dict(row) for _, row in scored[:limit]]

    def find_semantic_cache(
        self,
        question_embedding: np.ndarray,
        threshold: float = 0.85,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT pergunta, referencia_resposta, embedding
            FROM cache_semantico
            ORDER BY id DESC
            LIMIT 300
            """
        ).fetchall()
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            score = cosine_similarity(question_embedding, self._from_blob(row["embedding"]))
            if score >= threshold:
                scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "question": row["pergunta"],
                "answer": row["referencia_resposta"] or "",
                "score": score,
            }
            for score, row in scored[:limit]
        ]

    def _to_blob(self, values: Iterable[float] | None) -> bytes | None:
        if values is None:
            return None
        return np.asarray([float(value) for value in values], dtype=np.float32).tobytes()

    def _from_blob(self, blob: bytes) -> np.ndarray:
        try:
            return np.frombuffer(blob, dtype=np.float32)
        except Exception:
            return np.asarray([], dtype=np.float32)

    def _text_similarity(self, left: str, right: str) -> float:
        left_words = set(left.split())
        right_words = set(right.split())
        if not left_words or not right_words:
            return 0.0
        return len(left_words & right_words) / max(len(left_words), len(right_words))
