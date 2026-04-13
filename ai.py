from __future__ import annotations

import json
import re
from typing import Any

import requests


class LocalAssistant:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def build_prompt(self, question: str, context_chunks: list[Any]) -> str:
        context_limit = int(self.config.get("max_context_chars", 2400))
        context_lines = ["Contexto recuperado:"]
        current_chars = len(context_lines[0]) + 1
        for chunk in context_chunks[: int(self.config.get("max_contexto", 3))]:
            header = f"[{chunk['file_name']} | chunk {chunk['chunk_index']}]"
            block = "\n".join([header, chunk["text"], ""])
            if current_chars + len(block) > context_limit:
                break
            context_lines.append(header)
            context_lines.append(chunk["text"])
            context_lines.append("")
            current_chars += len(block)
        context_lines.append("Pergunta do usuario:")
        context_lines.append(question)
        context_lines.append("")
        context_lines.append("Instrucoes:")
        context_lines.append("responda usando prioritariamente o contexto fornecido")
        context_lines.append("se o contexto for insuficiente, deixe isso claro")
        context_lines.append("seja objetivo e tecnico quando necessario")
        return "\n".join(context_lines)

    def generate(self, prompt: str) -> str:
        mode = self.config.get("modo_llm", "ollama")
        if mode == "ollama":
            return self._call_ollama(prompt)
        if mode == "lmstudio":
            return self._call_lmstudio(prompt)
        raise ValueError(f"Unsupported llm mode: {mode}")

    def fallback_answer(self, question: str, context_chunks: list[Any]) -> str:
        if not context_chunks:
            return (
                "Nao encontrei contexto local suficiente para responder com confianca. "
                "Adicione notas ao vault ou verifique se o indice foi carregado."
            )
        question_terms = {term for term in re.split(r"\W+", question.lower()) if len(term) > 2}
        lines = ["Resposta local baseada no contexto recuperado:"]
        used = 0
        for chunk in context_chunks[: int(self.config.get("max_contexto", 3))]:
            sentences = re.split(r"(?<=[.!?])\s+", chunk["text"].strip())
            picked = []
            for sentence in sentences:
                sentence_terms = {term for term in re.split(r"\W+", sentence.lower()) if len(term) > 2}
                if question_terms and sentence_terms.intersection(question_terms):
                    picked.append(sentence.strip())
                if len(" ".join(picked)) > 400:
                    break
            if not picked and sentences:
                picked = [sentences[0].strip()]
            if picked:
                lines.append(f"- {chunk['file_name']}: {' '.join(picked[:2])}")
                used += 1
            if used >= 3:
                break
        if len(lines) == 1:
            return (
                "Encontrei contexto, mas nao consegui extrair uma resposta direta. "
                "Veja as notas recuperadas e refine a pergunta."
            )
        return "\n".join(lines)

    def _call_ollama(self, prompt: str) -> str:
        url = self.config.get("ollama_url", "http://localhost:11434").rstrip("/")
        response = requests.post(
            f"{url}/api/generate",
            json={
                "model": self.config.get("modelo_llm", "llama3"),
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": float(self.config.get("temperature", 0.2))},
            },
            timeout=int(self.config.get("timeout", 60)),
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError("Ollama is unavailable or timed out") from exc
        payload = response.json()
        return str(payload.get("response", "")).strip()

    def _call_lmstudio(self, prompt: str) -> str:
        url = self.config.get("lmstudio_url", "http://localhost:1234").rstrip("/")
        response = requests.post(
            f"{url}/v1/chat/completions",
            json={
                "model": self.config.get("modelo_llm", "llama3"),
                "messages": [
                    {"role": "system", "content": "You are a local assistant."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": float(self.config.get("temperature", 0.2)),
                "stream": False,
            },
            timeout=int(self.config.get("timeout", 60)),
        )
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError("LM Studio is unavailable or timed out") from exc
        payload = response.json()
        choices = payload.get("choices", [])
        if not choices:
            return ""
        return str(choices[0]["message"]["content"]).strip()

    def list_ollama_models(self) -> list[str]:
        url = self.config.get("ollama_url", "http://localhost:11434").rstrip("/")
        response = requests.get(f"{url}/api/tags", timeout=3)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models", [])
        return [str(item.get("name", "")) for item in models if item.get("name")]
