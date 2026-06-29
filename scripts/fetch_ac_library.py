"""登录 XMUOJ，抓取某场比赛里“我自己”已满分(AC)的题目代码，写入 AC 参考代码库。

支持**多账号**：不同账号 AC 的题目不同，逐个登录爬取并合并去重到同一个库，覆盖更广。
账号解析与逐账号抓取逻辑复用 cli.fetch_ac_flow。

环境变量：
    XMUOJ_PILOT_ACCOUNTS         多账号（推荐）。两种写法任选：
                                 1) 每行一个：``用户名:密码``（也支持空格/逗号分隔）
                                 2) JSON 数组：[{"username":"u1","password":"p1"}, ...]
    XMUOJ_PILOT_USERNAME         单账号用户名（会与 ACCOUNTS 合并去重）
    XMUOJ_PILOT_PASSWORD         单账号密码
    XMUOJ_PILOT_CONTEST_ID       比赛 ID（必填）
    XMUOJ_PILOT_CONTEST_PASSWORD 比赛密码（可选，所有账号共用）
    XMUOJ_PILOT_VERIFY_SSL       是否校验 SSL，默认 false
    XMUOJ_PILOT_AC_LIBRARY_DIR   代码库目录，默认 ./ac-library
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

from xmuoj_pilot.cli import AppContext, fetch_ac_flow, parse_accounts  # noqa: E402
from xmuoj_pilot.ui.console import console  # noqa: E402


async def main() -> int:
    contest_id_text = os.getenv("XMUOJ_PILOT_CONTEST_ID")
    if not parse_accounts():
        console.print("[red]未提供账号：请设置 XMUOJ_PILOT_ACCOUNTS 或 XMUOJ_PILOT_USERNAME/PASSWORD。[/red]")
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

    await fetch_ac_flow(ctx, contest_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
