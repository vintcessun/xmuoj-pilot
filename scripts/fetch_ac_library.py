"""登录 XMUOJ，抓取某场比赛里“我自己”已满分(AC)的题目代码，写入 AC 参考代码库。

环境变量：
    XMUOJ_PILOT_USERNAME         账号（必填）
    XMUOJ_PILOT_PASSWORD         密码（必填）
    XMUOJ_PILOT_CONTEST_ID       比赛 ID（必填）
    XMUOJ_PILOT_CONTEST_PASSWORD 比赛密码（可选）
    XMUOJ_PILOT_VERIFY_SSL       是否校验 SSL，默认 false
    XMUOJ_PILOT_AC_LIBRARY_DIR   代码库目录，默认 ./ac-library

生成结果：ac-library/contest-<id>/<display_id>.json + 索引页 index.html/json。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xmuoj_pilot.cli import AppContext, fetch_ac_flow  # noqa: E402
from xmuoj_pilot.ui.console import console  # noqa: E402


async def main() -> int:
    username = os.getenv("XMUOJ_PILOT_USERNAME")
    password = os.getenv("XMUOJ_PILOT_PASSWORD")
    contest_id_text = os.getenv("XMUOJ_PILOT_CONTEST_ID")
    contest_password = os.getenv("XMUOJ_PILOT_CONTEST_PASSWORD")

    if not username or not password:
        console.print("[red]缺少 XMUOJ_PILOT_USERNAME 或 XMUOJ_PILOT_PASSWORD。[/red]")
        return 2
    if not contest_id_text:
        console.print("[red]缺少 XMUOJ_PILOT_CONTEST_ID。[/red]")
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
        console.print("[yellow]本次抓取已关闭 SSL 证书校验。[/yellow]")

    try:
        ok = await ctx.auth.login(username, password)
    except RuntimeError as exc:
        console.print(f"[red]登录失败：{exc}[/red]")
        return 1
    if not ok:
        console.print("[red]登录 API 返回未通过，请检查账号密码。[/red]")
        return 1
    console.print("[green]登录成功。[/green]")

    if contest_password:
        try:
            await ctx.contests.submit_password(contest_id, contest_password)
            ctx.save_contest_password(contest_id, contest_password)
            console.print("[green]已提交比赛密码。[/green]")
        except RuntimeError as exc:
            console.print(f"[yellow]提交比赛密码失败（继续尝试抓取）：{exc}[/yellow]")

    await fetch_ac_flow(ctx, contest_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
