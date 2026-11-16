#!/usr/bin/env python3
"""NexLing 入口: python run.py serve|translate|seed"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())