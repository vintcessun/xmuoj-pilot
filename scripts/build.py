"""用 Nuitka 把 xmuoj-pilot 打包成当前平台的单文件可执行程序。

输出到 dist/，文件名形如：
    xmuoj-pilot-linux-x86_64
    xmuoj-pilot-windows-x86_64.exe
    xmuoj-pilot-macos-arm64

本脚本只构建“当前运行平台”的产物；三平台(manylinux/windows/macos)的统一构建
由 .github/workflows/build-release.yml 的 matrix 分别在对应 runner 上调用本脚本完成。

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
    parser.add_argument("--version", default="", help="可选版本号，仅用于日志/产物标识。")
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
        print("[build] Nuitka 构建失败。", file=sys.stderr)
        return result.returncode

    produced = DIST / output_name
    if not produced.exists():
        print(f"[build] 未找到产物：{produced}", file=sys.stderr)
        return 1
    print(f"[build] 完成：{produced}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
