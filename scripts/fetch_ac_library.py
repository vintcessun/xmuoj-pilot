"""登录 XMUOJ，抓取某场比赛里“我自己”已满分(AC)的题目代码，写入 AC 参考代码库。

支持**多账号**：不同账号 AC 的题目不同，逐个登录爬取并合并去重到同一个库，
覆盖面更广。

环境变量：
    XMUOJ_PILOT_ACCOUNTS         多账号（推荐）。三种写法任选：
                                 1) 每行一个：``用户名:密码``（也支持空格或逗号分隔）
                                 2) JSON 数组：[{"username":"u1","password":"p1"}, ...]
    XMUOJ_PILOT_USERNAME         单账号用户名（未设置 ACCOUNTS 时使用）
    XMUOJ_PILOT_PASSWORD         单账号密码
    XMUOJ_PILOT_CONTEST_ID       比赛 ID（必填）
    XMUOJ_PILOT_CONTEST_PASSWORD 比赛密码（可选，所有账号共用）
    XMUOJ_PILOT_VERIFY_SSL       是否校验 SSL，默认 false
    XMUOJ_PILOT_AC_LIBRARY_DIR   代码库目录，默认 ./ac-library

生成结果：ac-library/<内部ID>.json + 索引页 index.html/json。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xmuoj_pilot.ac_library import ACLibrary  # noqa: E402
from xmuoj_pilot.cli import AppContext, fetch_ac_for_contest  # noqa: E402
from xmuoj_pilot.ui.console import console  # noqa: E402


def parse_accounts() -> list[tuple[str, str]]:
    """解析多账号；解析不到再回退到单账号环境变量。"""
    raw = (os.getenv("XMUOJ_PILOT_ACCOUNTS") or "").strip()
    accounts: list[tuple[str, str]] = []
    if raw:
        if raw.startswith("["):
            try:
                for entry in json.loads(raw):
                    username = str(entry.get("username", "")).strip()
                    password = str(entry.get("password", ""))
                    if username and password:
                        accounts.append((username, password))
            except (ValueError, AttributeError):
                console.print("[red]XMUOJ_PILOT_ACCOUNTS 不是合法 JSON 数组。[/red]")
        else:
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = re.split(r"[:\s,]+", line, maxsplit=1)
                if len(parts) == 2 and parts[0] and parts[1]:
                    accounts.append((parts[0], parts[1]))
    if not accounts:
        username = os.getenv("XMUOJ_PILOT_USERNAME")
        password = os.getenv("XMUOJ_PILOT_PASSWORD")
        if username and password:
            accounts.append((username, password))
    # 去重（按用户名）
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for username, password in accounts:
        if username not in seen:
            seen.add(username)
            unique.append((username, password))
    return unique


async def main() -> int:
    contest_id_text = os.getenv("XMUOJ_PILOT_CONTEST_ID")
    contest_password = os.getenv("XMUOJ_PILOT_CONTEST_PASSWORD")

    accounts = parse_accounts()
    if not accounts:
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

    verify_ssl = os.getenv("XMUOJ_PILOT_VERIFY_SSL", "false").lower() not in {"0", "false", "no"}
    ctx = AppContext()
    ctx.client.verify_ssl = verify_ssl
    if not verify_ssl:
        console.print("[yellow]本次抓取已关闭 SSL 证书校验。[/yellow]")

    console.print(f"[cyan]共 {len(accounts)} 个账号，开始逐个抓取比赛 {contest_id}。[/cyan]")
    library = ACLibrary()
    total_saved = 0
    ok_accounts = 0
    for index, (username, password) in enumerate(accounts, start=1):
        console.print(f"[cyan]== 账号 {index}/{len(accounts)}：{username} ==[/cyan]")
        # 每个账号用全新会话，避免 cookie 串号
        ctx.session_storage.clear()
        try:
            ok = await ctx.auth.login(username, password)
        except RuntimeError as exc:
            console.print(f"[red]{username} 登录失败：{exc}[/red]")
            continue
        if not ok:
            console.print(f"[red]{username} 登录未通过，跳过。[/red]")
            continue
        ok_accounts += 1

        if contest_password:
            try:
                await ctx.contests.submit_password(contest_id, contest_password)
            except RuntimeError as exc:
                console.print(f"[yellow]{username} 提交比赛密码失败（继续抓取）：{exc}[/yellow]")

        saved, skipped = await fetch_ac_for_contest(ctx, contest_id, library, skip_existing=True)
        total_saved += saved
        console.print(f"[green]{username}：新增 {saved} 题，跳过 {skipped} 题。[/green]")

    library.build_index()
    console.print(
        f"[green]全部完成：{ok_accounts}/{len(accounts)} 个账号成功，"
        f"共新增 {total_saved} 题。索引页：{library.root / 'index.html'}[/green]"
    )
    return 0 if ok_accounts > 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
