#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""启动后端 API。

    python scripts/run_api.py            # 默认 127.0.0.1:8000
    python scripts/run_api.py --port 9000 --reload
"""
import os
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()

    import uvicorn
    uvicorn.run("backend.app.api.app:app", host=args.host, port=args.port,
                reload=args.reload, factory=False)


if __name__ == "__main__":
    main()
