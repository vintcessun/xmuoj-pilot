from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xmuoj_pilot.cli import AppContext, api_smoke_test_flow  # noqa: E402
from xmuoj_pilot.ui.console import console  # noqa: E402


async def main() -> int:
    username = os.getenv("XMUOJ_PILOT_USERNAME")
    password = os.getenv("XMUOJ_PILOT_PASSWORD")
    contest_id_text = os.getenv("XMUOJ_PILOT_CONTEST_ID", "361")
    display_problem_id = os.getenv("XMUOJ_PILOT_PROBLEM_ID", "JD001")
    contest_password = os.getenv("XMUOJ_PILOT_CONTEST_PASSWORD")
    submit_file_text = os.getenv("XMUOJ_PILOT_SUBMIT_FILE")
    language = os.getenv("XMUOJ_PILOT_LANG", "C++")

    if not username or not password:
        console.print("[red]缺少 XMUOJ_PILOT_USERNAME 或 XMUOJ_PILOT_PASSWORD。[/red]")
        return 2

    try:
        contest_id = int(contest_id_text)
    except ValueError:
        console.print("[red]XMUOJ_PILOT_CONTEST_ID 必须是数字。[/red]")
        return 2

    ctx = AppContext()
    verify_ssl = os.getenv("XMUOJ_PILOT_VERIFY_SSL", "false").lower() not in {"0", "false", "no"}
    ctx.client.verify_ssl = verify_ssl
    if not verify_ssl:
        console.print("[yellow]本次 API 测试已关闭 SSL 证书校验。[/yellow]")

    try:
        ok = await ctx.auth.login(username, password)
    except RuntimeError as exc:
        console.print(f"[red]登录 API 测试失败：{exc}[/red]")
        return 1

    if not ok:
        console.print("[red]登录 API 返回未通过。[/red]")
        return 1

    console.print("[green]登录 API 通过，session 已保存。[/green]")
    submit_file = Path(submit_file_text) if submit_file_text else None
    await api_smoke_test_flow(
        ctx,
        contest_id,
        display_problem_id,
        submit_file,
        language,
        contest_password=contest_password,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
