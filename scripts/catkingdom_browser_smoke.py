#!/usr/bin/env python3
"""catkingdom.html 浏览器冒烟检查（离线静态版）。"""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "catkingdom.html"


def has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE | re.MULTILINE) is not None


def main() -> int:
    if not TARGET.exists():
        print("FAIL: 未找到 catkingdom.html")
        return 1

    text = TARGET.read_text(encoding="utf-8", errors="ignore")

    checks = {
        "html": has(r"<html", text),
        "style": has(r"<style", text),
        "script": has(r"<script", text),
        "game_surface": has(r"id\s*=\s*[\"']game_surface[\"']", text)
        or has(r"\bboard\b", text),
        "score": has(r"id\s*=\s*[\"']score[\"']", text) or has(r"分数", text),
        "controls": has(r"id\s*=\s*[\"']controls[\"']", text)
        and (has(r"keydown", text) or has(r"wasd", text) or has(r"方向键", text)),
        "restart": has(r"restart", text) or has(r"重新开始", text),
        "turn_loop": has(r"MAX_TURNS\s*=\s*12", text)
        and has(r"runTurn\s*\(", text)
        and has(r"settleTurn\s*\(", text)
        and has(r"checkEnding\s*\(", text),
    }

    failed = [name for name, ok in checks.items() if not ok]
    summary = ", ".join(f"{name}={'OK' if ok else 'MISS'}" for name, ok in checks.items())
    print(f"catkingdom_browser_smoke: {summary}")

    if failed:
        print("FAIL: " + ", ".join(failed))
        return 1

    print("PASS: catkingdom 页面核心冒烟检查通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
