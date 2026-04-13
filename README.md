# Local Obsidian Assistant

## Overview
Terminal assistant with:

- local SQLite memory
- Obsidian Markdown vault loading
- chunking with overlap
- semantic search using embeddings
- persistent local vector store
- Ollama and LM Studio support
- automatic startup indexing when the vault index is missing or incompatible
- token saving through cache and RAG

## Files

- `cli.py`
- `database.py`
- `ai.py`
- `search.py`
- `embeddings.py`
- `obsidian_loader.py`
- `vector_store.py`
- `utils.py`
- `config.json`
- `requirements.txt`
- `requirements-optional.txt`
- `setup.ps1`
- `run.ps1`
- `setup.bat`
- `run.bat`
- `smoke_test.py`
- `healthcheck.ps1`
- `healthcheck.bat`

## Install

Requirements:

- Python 3.10+
- Ollama or LM Studio running locally for live generation

Base install:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Optional packages:

```powershell
python -m pip install -r requirements-optional.txt
```

Optional packages provide better semantic search:

- `sentence-transformers`
- `faiss-cpu`

If they are unavailable, the app still runs with fallback logic.

## Run

```powershell
python cli.py
```

Quick start on Windows:

```powershell
.\setup.ps1
.\run.ps1
```

Or:

```bat
setup.bat
run.bat
healthcheck.bat
```

Safe update flow:

```powershell
.\update.ps1
```

The update script creates a backup branch and tag before pulling remote changes, so you can recover the exact pre-update state if something goes wrong.

Diagnostics without chat:

```powershell
python cli.py --diag
python cli.py --status
```

## Commands

- `/sair`
- `/listar`
- `/limpar`
- `/modo`
- `/recarregar`
- `/reindexar`
- `/status`
- `/diagnostico`
- `/config`
- `/config chave valor`
- `/cancelar`

## Notes

- The vault path must exist and point to your real Obsidian vault.
- `/recarregar` performs incremental sync.
- `/reindexar` rebuilds the full index.
- `auto_reindex_on_start` can rebuild the index automatically on startup.
- `smoke_test.py` validates startup without entering chat.
