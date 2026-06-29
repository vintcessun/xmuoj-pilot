"""Build xmuoj-pilot into a single-file executable with Nuitka.

输出到 dist/，文件名形如：
    xmuoj-pilot-linux-x86_64
    xmuoj-pilot-windows-x86_64.exe
    xmuoj-pilot-macos-arm64

This script only builds the current platform artifact. The GitHub Actions
matrix in .github/workflows/build-release.yml runs it on Linux, Windows, and
macOS separately.

用法：
    python scripts/build.py [--version X.Y.Z]
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "src" / "xmuoj_pilot" / "main.py"
DIST = ROOT / "dist"


def target_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(machine, machine)
    if system == "windows":
        return f"xmuoj-pilot-windows-{arch}.exe"
    if system == "darwin":
        return f"xmuoj-pilot-macos-{arch}"
    return f"xmuoj-pilot-linux-{arch}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build xmuoj-pilot single-file binary via Nuitka.")
    parser.add_argument("--version", default="", help="Optional version, used for build logs only.")
    args = parser.parse_args()

    DIST.mkdir(parents=True, exist_ok=True)
    output_name = target_name()
    if args.version:
        print(f"[build] version: {args.version}")
    print(f"[build] platform: {platform.system()} {platform.machine()} -> {output_name}")

    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--onefile",
        "--assume-yes-for-downloads",
        f"--output-dir={DIST}",
        f"--output-filename={output_name}",
        str(ENTRY),
    ]
    print("[build] running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("[build] Nuitka build failed.", file=sys.stderr)
        return result.returncode

    produced = DIST / output_name
    if not produced.exists():
        print(f"[build] artifact not found: {produced}", file=sys.stderr)
        return 1
    print(f"[build] done: {produced}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
