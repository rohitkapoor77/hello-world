#!/usr/bin/env python3
"""Launch the AI Shopping Readiness Auditor web UI.

    python run.py                # http://127.0.0.1:8000
    python run.py --port 9000
    python run.py --host 0.0.0.0 --port 8080
"""
import argparse
import webbrowser

from aiaudit.server import serve


def main():
    ap = argparse.ArgumentParser(description="AI Shopping Readiness Auditor — web UI")
    ap.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8000, help="Bind port (default 8000)")
    ap.add_argument("--open", action="store_true", help="Open the UI in a browser")
    args = ap.parse_args()

    if args.open:
        try:
            webbrowser.open(f"http://{args.host}:{args.port}/")
        except Exception:
            pass
    serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
