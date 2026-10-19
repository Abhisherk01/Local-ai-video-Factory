"""Standalone server entrypoint: python -m laf.server

Used by the Tauri shell (which passes --port / --data-dir and sets the
LAF_TOKEN env var) and by developers (scripts/run-backend-dev.ps1).

SECURITY notes:
- Binds to 127.0.0.1 only; never exposes the API to the network.
- The session token travels via the LAF_TOKEN environment variable when
  launched by the shell, and is NEVER written to logs. In standalone dev
  mode (token generated here) it is written to runtime.json inside the
  user's own data dir so tooling can reach it - an accepted local-only
  trade-off documented in ADR-008.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import sys
import time

import uvicorn

from laf import __version__
from laf.api.main import create_app
from laf.config import resolve_runtime
from laf.logging_setup import setup_logging

logger = logging.getLogger("laf.server")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m laf.server",
        description="Local AI Video Factory backend (local-only FastAPI).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8756)
    parser.add_argument("--token", default=None, help="session token (else LAF_TOKEN env, else generated)")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--models-dir", default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    env_token = os.environ.get("LAF_TOKEN")
    token = args.token or env_token or secrets.token_hex(16)
    token_supplied_externally = bool(args.token or env_token)

    setup_logging(args.log_level)
    runtime = resolve_runtime(args.data_dir, args.models_dir)
    runtime.ensure_dirs()

    app = create_app(
        data_dir=runtime.data_dir,
        models_dir=runtime.models_dir,
        token=token,
    )

    handshake: dict[str, object] = {
        "pid": os.getpid(),
        "port": args.port,
        "host": args.host,
        "data_dir": str(runtime.data_dir),
        "version": __version__,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if not token_supplied_externally:
        # Dev-only convenience: expose the generated token to local tooling.
        handshake["token"] = token
    runtime.runtime_file.write_text(json.dumps(handshake, indent=2), encoding="utf-8")

    # SECURITY: log the port, never the token.
    logger.info("backend listening", extra={"host": args.host, "port": args.port})

    exit_code = 0
    try:
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level=args.log_level.lower(),
            access_log=False,
        )
    except OSError as exc:
        logger.error("server failed to start", extra={"error": str(exc)})
        exit_code = 1
    finally:
        try:
            runtime.runtime_file.unlink(missing_ok=True)
        except OSError:
            pass
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
