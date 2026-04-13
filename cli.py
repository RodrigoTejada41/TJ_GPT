from __future__ import annotations

import json
import argparse
import sys
import threading
from pathlib import Path

import requests

from ai import LocalAssistant
from code_summarizer import CodeSummarizer
from database import ChatDatabase
from embeddings import EmbeddingManager
from obsidian_loader import ObsidianLoader
from search import SearchEngine
from source_reader import ReadOptions, SourceReader
from vault_search import SearchOptions, VaultSearcher
from utils import AppTimer, ensure_directory, log, normalize_text
from vector_store import VectorStore


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "assistant.sqlite3"
INDEX_PATH = DATA_DIR / "vector_store"
REINDEX_CHECKPOINT_PATH = DATA_DIR / "reindex_checkpoint.json"
DEFAULT_CONFIG = {
    "modo_llm": "ollama",
    "modo_embedding": "ollama",
    "modelo_llm": "llama3",
    "modelo_embedding": "nomic-embed-text",
    "vault_path": "./obsidian_vault",
    "top_k": 5,
    "max_contexto": 3,
    "similaridade_cache": 0.85,
    "auto_reindex_on_start": True,
    "timeout": 60,
    "ollama_url": "http://localhost:11434",
    "lmstudio_url": "http://localhost:1234",
    "temperature": 0.2,
    "max_context_chars": 2400,
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            merged = DEFAULT_CONFIG.copy()
            merged.update(data)
            return merged
        except Exception:
            with CONFIG_PATH.open("w", encoding="utf-8") as handle:
                json.dump(DEFAULT_CONFIG, handle, indent=2, ensure_ascii=False)
            return DEFAULT_CONFIG.copy()
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(DEFAULT_CONFIG, handle, indent=2, ensure_ascii=False)
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, ensure_ascii=False)


class AssistantApp:
    def __init__(self) -> None:
        ensure_directory(DATA_DIR)
        self.config = load_config()
        self.db = ChatDatabase(DB_PATH)
        self.embeddings = EmbeddingManager(self.config)
        self.vector_store = VectorStore(INDEX_PATH)
        self._align_vector_manifest()
        self.vector_store.load()
        self.loader = ObsidianLoader(self.config)
        self.search = SearchEngine(self.db, self.vector_store, self.embeddings, self.config)
        self.ai = LocalAssistant(self.config)
        self.summarizer = CodeSummarizer()
        self.reader = SourceReader()
        self.vault_search = VaultSearcher(self.loader)
        self.documents = []
        self.chunks = []
        self.vault_file_count = 0
        self.index_lock = threading.RLock()
        self.index_thread: threading.Thread | None = None
        self.indexing_state = "idle"

    def _vector_manifest(self) -> dict:
        return {
            "modo_embedding": self.config.get("modo_embedding"),
            "modelo_embedding": self.config.get("modelo_embedding"),
            "vault_path": str(Path(self.config["vault_path"]).expanduser()),
            "chunk_min_chars": 400,
            "chunk_max_chars": 900,
            "chunk_overlap": 120,
        }

    def _align_vector_manifest(self) -> None:
        expected = self._vector_manifest()
        if (self.vector_store.metadata or self.vector_store.vectors is not None) and not self.vector_store.manifest_matches(expected):
            self.vector_store.reset()
            self.clear_reindex_checkpoint()
        self.vector_store.set_manifest(expected)

    def _load_reindex_checkpoint(self) -> dict | None:
        if not REINDEX_CHECKPOINT_PATH.exists():
            return None
        try:
            with REINDEX_CHECKPOINT_PATH.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if data.get("manifest") != self._vector_manifest():
                return None
            return data
        except Exception:
            return None

    def _save_reindex_checkpoint(self, data: dict) -> None:
        ensure_directory(DATA_DIR)
        with REINDEX_CHECKPOINT_PATH.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)

    def clear_reindex_checkpoint(self) -> None:
        REINDEX_CHECKPOINT_PATH.unlink(missing_ok=True)

    def refresh_components(self) -> None:
        self.embeddings = EmbeddingManager(self.config)
        self.loader = ObsidianLoader(self.config)
        self.search = SearchEngine(self.db, self.vector_store, self.embeddings, self.config)
        self.ai = LocalAssistant(self.config)
        self._align_vector_manifest()

    def auto_bootstrap(self) -> None:
        vault_path = Path(self.config["vault_path"]).expanduser()
        if not vault_path.exists():
            return
        if not bool(self.config.get("auto_reindex_on_start", True)):
            return
        if self.vector_store.is_loaded() and self.vector_store.manifest_matches(self._vector_manifest()):
            return
        self.start_background_reindex()

    def start_background_reindex(self) -> None:
        if self.index_thread and self.index_thread.is_alive():
            return
        self.indexing_state = "starting"
        self.index_thread = threading.Thread(target=self._background_reindex_worker, daemon=True)
        self.index_thread.start()
        log("Auto mode: indexing vault in background...")

    def _background_reindex_worker(self) -> None:
        try:
            self.indexing_state = "running"
            with self.index_lock:
                self.reload_vault(reindex=True, quiet=False)
            self.indexing_state = "ready"
        except Exception as exc:
            self.indexing_state = f"error: {exc}"
            log(f"Background reindex failed: {exc}")

    def reload_vault(self, reindex: bool = False, quiet: bool = False) -> None:
        vault_path = Path(self.config["vault_path"]).expanduser()
        if not vault_path.exists():
            raise FileNotFoundError(f"Vault path not found: {vault_path}")
        if reindex:
            self.reindex_vault()
        else:
            self.vault_file_count = self.loader.count_markdown_files(vault_path)
            self.documents = []
            self.chunks = []
        if not quiet:
            log(f"Vault scanned: {self.vault_file_count} markdown files")

    def reindex_vault(self, batch_size: int = 64) -> None:
        vault_path = Path(self.config["vault_path"]).expanduser()
        if not vault_path.exists():
            raise FileNotFoundError(f"Vault path not found: {vault_path}")
        checkpoint = self._load_reindex_checkpoint()
        resume_from = int(checkpoint.get("next_file_index", 0)) if checkpoint else 0
        if resume_from <= 0:
            self.vector_store.reset()
        else:
            self.vector_store.load()
        self.vault_file_count = 0
        total_files = self.loader.count_markdown_files(vault_path)
        total_chunks = int(checkpoint.get("chunks_indexed", 0)) if checkpoint else 0
        processed_files = int(checkpoint.get("files_indexed", 0)) if checkpoint else 0
        pending_chunks: list = []

        try:
            for file_index, document in enumerate(self.loader.iter_documents(vault_path, start_index=resume_from), start=resume_from + 1):
                self.vault_file_count = file_index
                chunks = self.loader._chunk_document(document)
                total_chunks += len(chunks)
                pending_chunks.extend(chunks)

                if len(pending_chunks) < batch_size:
                    continue

                texts = [chunk.text for chunk in pending_chunks]
                embeddings = self.embeddings.embed_texts(texts)
                metadata = [self.vector_store._chunk_metadata(chunk) for chunk in pending_chunks]
                with self.index_lock:
                    self.vector_store.append_entries(metadata, embeddings, manifest=self._vector_manifest())
                processed_files = file_index
                self._save_reindex_checkpoint(
                    {
                        "manifest": self._vector_manifest(),
                        "next_file_index": file_index,
                        "files_indexed": processed_files,
                        "chunks_indexed": total_chunks,
                        "total_files": total_files,
                    }
                )
                pct = (processed_files / total_files * 100.0) if total_files else 100.0
                log(f"Indexed {processed_files}/{total_files} files ({pct:.1f}%) / {total_chunks} chunks")
                pending_chunks = []
        except KeyboardInterrupt:
            if pending_chunks:
                texts = [chunk.text for chunk in pending_chunks]
                embeddings = self.embeddings.embed_texts(texts)
                metadata = [self.vector_store._chunk_metadata(chunk) for chunk in pending_chunks]
                self.vector_store.append_entries(metadata, embeddings, manifest=self._vector_manifest())
            self._save_reindex_checkpoint(
                {
                    "manifest": self._vector_manifest(),
                    "next_file_index": self.vault_file_count,
                    "files_indexed": self.vault_file_count,
                    "chunks_indexed": total_chunks,
                    "total_files": total_files,
                    "interrupted": True,
                }
            )
            log("Reindex interrupted. Progress checkpoint saved.")
            raise

        if pending_chunks:
            texts = [chunk.text for chunk in pending_chunks]
            embeddings = self.embeddings.embed_texts(texts)
            metadata = [self.vector_store._chunk_metadata(chunk) for chunk in pending_chunks]
            with self.index_lock:
                self.vector_store.append_entries(metadata, embeddings, manifest=self._vector_manifest())

        self.clear_reindex_checkpoint()
        self.documents = []
        self.chunks = []
        log(f"Reindex complete: {self.vault_file_count}/{total_files} files / {total_chunks} chunks")

    def reindex(self) -> None:
        if not self.chunks:
            self.vector_store.reset()
            return
        texts = [chunk.text for chunk in self.chunks]
        embeddings = self.embeddings.embed_texts(texts)
        self.vector_store.build(self.chunks, embeddings)
        self.vector_store.set_manifest(self._vector_manifest())

    def sync_index(self) -> None:
        if not self.chunks:
            self.vector_store.reset()
            return
        existing_map = self.vector_store.index_map()
        existing_vectors = self.vector_store.vectors
        existing_metadata = self.vector_store.metadata
        pending_chunks = []
        reuse_flags: list[bool] = []

        for chunk in self.chunks:
            existing_idx = existing_map.get(chunk.chunk_id)
            if (
                existing_idx is not None
                and existing_vectors is not None
                and existing_idx < len(existing_metadata)
                and existing_metadata[existing_idx].get("metadata", {}).get("source_hash")
                == chunk.metadata.get("source_hash")
                and existing_metadata[existing_idx].get("metadata", {}).get("chunk_hash")
                == chunk.metadata.get("chunk_hash")
            ):
                reuse_flags.append(True)
            else:
                pending_chunks.append(chunk)
                reuse_flags.append(False)

        pending_map = {}
        if pending_chunks:
            pending_embeddings = self.embeddings.embed_texts([chunk.text for chunk in pending_chunks])
            pending_map = {chunk.chunk_id: emb for chunk, emb in zip(pending_chunks, pending_embeddings)}

        current_metadata: list[dict] = []
        current_vectors: list = []
        for chunk, reuse in zip(self.chunks, reuse_flags):
            if reuse and existing_vectors is not None:
                existing_idx = existing_map[chunk.chunk_id]
                current_metadata.append(existing_metadata[existing_idx])
                current_vectors.append(existing_vectors[existing_idx])
                continue
            current_metadata.append(self.vector_store._chunk_metadata(chunk))
            current_vectors.append(pending_map[chunk.chunk_id])

        self.vector_store.replace_entries(current_metadata, current_vectors, manifest=self._vector_manifest())

    def status(self) -> str:
        history_count = self.db.count_history()
        return (
            f"files={self.vault_file_count} chunks={len(self.chunks)} "
            f"indexed={self.vector_store.is_loaded()} entries={self.vector_store.count_entries()} dim={self.vector_store.dimension} history={history_count} "
            f"llm={self.config['modo_llm']} embedding={self.config['modo_embedding']} auto={bool(self.config.get('auto_reindex_on_start', True))}"
        )

    def diagnostics(self) -> dict:
        python_ok = True
        venv_python = Path(".venv\\Scripts\\python.exe")
        vault_path = Path(self.config["vault_path"]).expanduser()
        ollama_models = self._safe_ollama_models()
        llm_model = str(self.config.get("modelo_llm", ""))
        embedding_model = str(self.config.get("modelo_embedding", ""))
        llm_present = self._model_matches_config(llm_model, ollama_models)
        embedding_present = self._model_matches_config(embedding_model, ollama_models)
        return {
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
            "status": self.status(),
            "vector_manifest": self.vector_store.manifest,
            "vector_index_loaded": self.vector_store.is_loaded() and self.vector_store.count_entries() > 0,
            "vector_needs_reindex": not self.vector_store.manifest_matches(self._vector_manifest()),
            "embedding_provider": type(self.embeddings.provider).__name__,
            "checks": [
                {"item": "Python runtime", "ok": python_ok, "detail": sys.executable},
                {"item": "Virtual env", "ok": venv_python.exists(), "detail": str(venv_python)},
                {"item": "Vault path", "ok": vault_path.exists(), "detail": str(vault_path)},
                {"item": "SQLite db", "ok": DB_PATH.exists(), "detail": str(DB_PATH)},
                {"item": "Vector index", "ok": self.vector_store.is_loaded(), "detail": str(INDEX_PATH)},
                {"item": "Embedding mode", "ok": bool(self.config.get("modo_embedding")), "detail": self.config.get("modo_embedding", "")},
                {"item": "LLM mode", "ok": bool(self.config.get("modo_llm")), "detail": self.config.get("modo_llm", "")},
                {"item": "LLM model present", "ok": llm_present, "detail": llm_model},
                {"item": "Embedding model present", "ok": embedding_present, "detail": embedding_model},
            ],
            "ollama_reachable": self._check_http(self.config.get("ollama_url", ""), "/api/tags"),
            "lmstudio_reachable": self._check_http(self.config.get("lmstudio_url", ""), "/v1/models"),
            "vault_path": str(vault_path),
            "ollama_models": ollama_models,
        }

    def format_diagnostics(self) -> str:
        diag = self.diagnostics()
        lines = [
            "Diagnostics",
            f"Python: {diag['python_version']} ({diag['python_executable']})",
            f"Status: {diag['status']}",
            f"Embedding provider: {diag['embedding_provider']}",
            f"Ollama reachable: {'OK' if diag['ollama_reachable'] else 'FAIL'}",
            f"LM Studio reachable: {'OK' if diag['lmstudio_reachable'] else 'FAIL'}",
            f"Vector index loaded: {'OK' if diag['vector_index_loaded'] else 'FAIL'}",
            f"Vector needs reindex: {'WARN' if diag['vector_needs_reindex'] else 'OK'}",
            "",
            "Checks:",
        ]
        for item in diag["checks"]:
            mark = "OK" if item["ok"] else "FAIL"
            lines.append(f"- [{mark}] {item['item']}: {item['detail']}")
        if diag["ollama_models"]:
            lines.append("")
            lines.append("Ollama models:")
            for model in diag["ollama_models"]:
                lines.append(f"- {model}")
        return "\n".join(lines)

    def _check_http(self, base_url: str, path: str) -> bool:
        if not base_url:
            return False
        try:
            response = requests.get(f"{base_url.rstrip('/')}{path}", timeout=2)
            return response.ok
        except Exception:
            return False

    def _safe_ollama_models(self) -> list[str]:
        try:
            return self.ai.list_ollama_models()
        except Exception:
            return []

    @staticmethod
    def _model_matches_config(config_model: str, installed_models: list[str]) -> bool:
        target = str(config_model or "").strip().lower()
        if not target or not installed_models:
            return False
        normalized = {str(model).strip().lower() for model in installed_models}
        if target in normalized or f"{target}:latest" in normalized:
            return True
        return any(model.split(":", 1)[0] == target for model in normalized)

    def process_question(self, question: str) -> None:
        cleaned = normalize_text(question)
        timer = AppTimer()
        question_embedding = self.embeddings.embed_text(question)

        with self.index_lock:
            cache_hit = self.search.find_cached_answer(question, cleaned, question_embedding)
            if cache_hit:
                elapsed = timer.elapsed()
                print(cache_hit["answer"])
                print(f"\n[source: cache | time: {elapsed:.2f}s | chunks: 0 | files: -]")
                self.db.save_interaction(
                    question=question,
                    answer=cache_hit["answer"],
                    category="cache",
                    origin="cache",
                    question_embedding=cache_hit.get("question_embedding"),
                    reference_response=cache_hit.get("answer"),
                    store_cache=False,
                )
                return

            retrieved = self.search.retrieve(
                question,
                cleaned,
                top_k=self.config["top_k"],
                question_embedding=question_embedding,
            )
        context_chunks = retrieved[: int(self.config["max_contexto"])]
        prompt = self.ai.build_prompt(question, context_chunks)

        try:
            answer = self.ai.generate(prompt)
            origin = "rag_obsidian" if context_chunks else "llm_direto"
        except Exception as exc:
            answer = self.ai.fallback_answer(question, context_chunks)
            origin = "rag_local_fallback" if context_chunks else "llm_direto"

        elapsed = timer.elapsed()
        print(answer)
        file_names = []
        for chunk in context_chunks:
            name = chunk["file_name"]
            if name not in file_names:
                file_names.append(name)
        files = ", ".join(file_names) if file_names else "-"
        print(
            f"\n[source: {origin} | time: {elapsed:.2f}s | chunks: {len(context_chunks)} | files: {files}]"
        )

        self.db.save_interaction(
            question=question,
            answer=answer,
            category=origin,
            origin=origin,
            question_embedding=question_embedding,
            reference_response=answer,
            store_cache=bool(answer.strip()),
        )

    def run(self) -> None:
        self.auto_bootstrap()
        log("Local assistant ready. Type /sair to exit.")
        while True:
            try:
                user_input = input(">> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                self.handle_command(user_input)
                continue

            self.process_question(user_input)

    def handle_command(self, command: str) -> None:
        command_name = command.split(maxsplit=1)[0].lower()
        if command_name == "/sair":
            raise SystemExit
        if command_name == "/listar":
            rows = self.db.list_history(limit=50)
            for row in rows:
                print(
                    f"[{row['data']}] {row['origem']} | {row['pergunta']}\n"
                    f"{row['resposta']}\n"
                )
            return
        if command_name == "/limpar":
            self.db.clear()
            log("Database cleared.")
            return
        if command_name == "/modo":
            log(
                f"LLM={self.config['modo_llm']} ({self.config['modelo_llm']}), "
                f"Embeddings={self.config['modo_embedding']} ({self.config['modelo_embedding']})"
            )
            return
        if command_name in {"/smart", "/resumir"}:
            parts = command.split(maxsplit=1)
            if len(parts) < 2:
                log("Usage: /smart caminho-do-arquivo")
                return
            target = Path(parts[1].strip().strip('"'))
            try:
                print(self.summarizer.format_summary(target))
            except Exception as exc:
                log(f"Failed to summarize file: {exc}")
            return
        if command_name in {"/ler", "/read"}:
            parts = command.split(maxsplit=4)
            if len(parts) < 2:
                log("Usage: /ler caminho [raw|minimal|aggressive] [max_lines|tail N] [numbers]")
                return
            target = Path(parts[1].strip().strip('"'))
            options = ReadOptions()
            extra = parts[2:]
            idx = 0
            while idx < len(extra):
                token = extra[idx].lower()
                if token in {"raw", "none", "minimal", "aggressive"}:
                    options.level = token
                elif token in {"tail", "last"} and idx + 1 < len(extra):
                    try:
                        options.tail_lines = int(extra[idx + 1])
                        idx += 1
                    except ValueError:
                        log("Usage: /ler caminho [raw|minimal|aggressive] [max_lines|tail N] [numbers]")
                        return
                elif token in {"numbers", "-n", "line_numbers"}:
                    options.line_numbers = True
                else:
                    try:
                        value = int(token)
                        if options.tail_lines is None:
                            options.max_lines = value
                        else:
                            options.tail_lines = value
                    except ValueError:
                        log(f"Unknown option: {token}")
                        return
                idx += 1
            try:
                print(self.reader.read_path(target, options))
            except Exception as exc:
                log(f"Failed to read file: {exc}")
            return
        if command_name in {"/buscar", "/grep"}:
            parts = command.split(maxsplit=1)
            if len(parts) < 2:
                log("Usage: /buscar termo")
                return
            query = parts[1].strip().strip('"')
            try:
                vault_path = Path(self.config["vault_path"]).expanduser()
                result = self.vault_search.search(vault_path, query, SearchOptions())
                print(result)
            except Exception as exc:
                log(f"Failed to search vault: {exc}")
            return
        if command_name == "/recarregar":
            self.reload_vault(reindex=False)
            log(f"Reloaded vault: {len(self.documents)} files, {len(self.chunks)} chunks")
            return
        if command_name == "/reindexar":
            try:
                self.reload_vault(reindex=True)
                log("Index rebuilt.")
            except KeyboardInterrupt:
                log("Reindex cancelled safely. Run /reindexar to resume.")
            return
        if command_name == "/cancelar":
            log("Use Ctrl+C while /reindexar is running to cancel safely and save a checkpoint.")
            return
        if command_name == "/status":
            log(self.status())
            return
        if command_name == "/index":
            log(f"Index state: {self.indexing_state}")
            return
        if command_name in {"/diagnostico", "/diag"}:
            print(self.format_diagnostics())
            return
        if command_name == "/config" and command.strip().lower() == "/config":
            print(json.dumps(self.config, indent=2, ensure_ascii=False))
            return
        if command_name == "/config" and command.lower().startswith("/config "):
            parts = command.split(maxsplit=2)
            if len(parts) < 3:
                log("Usage: /config chave valor")
                return
            key = parts[1]
            raw_value = parts[2]
            try:
                value = json.loads(raw_value)
            except Exception:
                value = raw_value
            self.config[key] = value
            save_config(self.config)
            self.refresh_components()
            if key == "vault_path":
                self.reload_vault(reindex=False)
            elif key in {"modo_embedding", "modelo_embedding"}:
                self.reload_vault(reindex=True)
            log(f"Config updated: {key}={value}")
            return
        log(f"Unknown command: {command}")


def main() -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--diag", action="store_true", help="Print diagnostics and exit")
    parser.add_argument("--status", action="store_true", help="Print status and exit")
    args = parser.parse_args()

    app = AssistantApp()
    if args.diag:
        print(app.format_diagnostics())
        return
    if args.status:
        print(app.status())
        return
    app.run()


if __name__ == "__main__":
    main()
