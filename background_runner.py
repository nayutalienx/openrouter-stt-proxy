from __future__ import annotations

import os
import sys
from pathlib import Path


def configure_background_stdio() -> None:
    root = Path(__file__).resolve().parent
    log_dir = root / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "proxy.log"
    log_stream = log_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = log_stream
    sys.stderr = log_stream
    os.chdir(root)


def main() -> None:
    configure_background_stdio()

    import uvicorn

    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=8787,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
