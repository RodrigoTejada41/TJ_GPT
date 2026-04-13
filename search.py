from __future__ import annotations

from typing import Any

from utils import normalize_text


class SearchEngine:
    def __init__(self, db, vector_store, embeddings, config: dict[str, Any]) -> None:
        self.db = db
        self.vector_store = vector_store
        self.embeddings = embeddings
        self.config = config

    def find_cached_answer(
        self,
        question: str,
        normalized: str,
        question_embedding=None,
    ) -> dict[str, Any] | None:
        if question_embedding is None:
            question_embedding = self.embeddings.embed_text(question)
        semantic_hits = self.db.find_semantic_cache(
            question_embedding,
            threshold=float(self.config.get("similaridade_cache", 0.85)),
            limit=3,
        )
        if semantic_hits:
            return {"answer": semantic_hits[0]["answer"], "question_embedding": question_embedding}

        textual_hits = self.db.find_similar_questions(
            normalized,
            threshold=float(self.config.get("similaridade_cache", 0.85)),
            limit=3,
            question_embedding=question_embedding,
        )
        if textual_hits:
            row = textual_hits[0]
            return {
                "answer": row["resposta"],
                "question_embedding": question_embedding,
            }
        return None

    def retrieve(
        self,
        question: str,
        normalized: str,
        top_k: int = 5,
        question_embedding=None,
    ) -> list[Any]:
        query_embedding = question_embedding if question_embedding is not None else self.embeddings.embed_text(question)
        candidates = self.vector_store.query(query_embedding, top_k=top_k)
        return self._rerank(normalized, candidates)

    def _rerank(self, normalized: str, candidates: list[dict[str, Any]]) -> list[Any]:
        question_words = set(normalized.split())
        scored = []
        history_mode = self._looks_historical(normalized)
        concept_mode = self._looks_conceptual(normalized)
        file_counts: dict[str, int] = {}
        for item in candidates:
            path = item.get("path", "")
            file_counts[path] = file_counts.get(path, 0) + 1

        for item in candidates:
            text = normalize_text(item.get("text", ""))
            text_words = set(text.split())
            lexical = len(question_words & text_words)
            score = float(item.get("score", 0.0))
            if lexical:
                score += min(0.12, lexical / max(len(question_words) or 1, 1) * 0.12)

            path = item.get("path", "")
            lowered_path = path.replace("\\", "/").lower()
            if history_mode and "/conversas/" in lowered_path:
                score += 0.08
            if concept_mode and "/livros/" in lowered_path:
                score += 0.08
            if file_counts.get(path, 0) > 1:
                score += 0.03

            item = dict(item)
            item["rerank_score"] = score
            scored.append(item)

        scored.sort(key=lambda entry: entry["rerank_score"], reverse=True)
        return scored

    def _looks_historical(self, normalized: str) -> bool:
        keywords = ["lembra", "falamos", "conversa", "historico", "antes", "anterior"]
        return any(word in normalized for word in keywords)

    def _looks_conceptual(self, normalized: str) -> bool:
        keywords = ["o que e", "defina", "conceito", "explica", "teoria", "como funciona"]
        return any(word in normalized for word in keywords)
