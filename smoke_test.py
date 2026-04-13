from __future__ import annotations

import json
from pathlib import Path

from cli import AssistantApp


def main() -> None:
    app = AssistantApp()
    print(json.dumps(
        {
            "status": app.status(),
            "config_keys": sorted(app.config.keys()),
            "documents": len(app.documents),
            "chunks": len(app.chunks),
        },
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
