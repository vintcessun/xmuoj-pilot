"""登录 XMUOJ，抓取某场比赛里“我自己”已满分(AC)的题目代码，写入 AC 参考代码库。

支持**多账号**：不同账号 AC 的题目不同，逐个登录爬取并合并去重到同一个库，覆盖更广。
账号解析与逐账号抓取逻辑复用 cli.fetch_ac_flow。

**弱口令补抓**（可选）：正常抓取完成后，若库里仍有题目缺代码，则从公开提交列表
（`/api/contest_submissions?myself=0&result=0`）取得该题 AC 过的账号，逐个尝试常见弱口令
登录；一旦登录成功就以该账号视角把这题的满分代码抓下来补进库。默认关闭，设
`XMUOJ_PILOT_WEAK_PASSWORD_FALLBACK=true` 开启。

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
    XMUOJ_PILOT_WEAK_PASSWORD_FALLBACK  是否启用弱口令补抓，默认 false
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from xmuoj_pilot.ac_library import ACLibrary  # noqa: E402
from xmuoj_pilot.cli import (  # noqa: E402
    AppContext,
    _extract_internal_problem_id,
    _problem_display_id,
    _problem_internal_id,
    fetch_ac_flow,
    parse_accounts,
    problems_flow,
)
from xmuoj_pilot.services.submission import _item_accepted  # noqa: E402
from xmuoj_pilot.ui.console import console, extract_items, problem_to_markdown, unwrap_data  # noqa: E402


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"", "0", "false", "no"}


def weak_passwords(username: str) -> list[str]:
    """根据学号（用户名）生成候选弱口令，按尝试顺序去重返回。

    规则：``123456`` / ``学号后两位+0603`` / ``学号后三位+xmu`` / ``xmu+学号后三位``。
    """
    digits = "".join(ch for ch in username if ch.isdigit())
    candidates = ["123456"]
    if len(digits) >= 2:
        candidates.append(f"{digits[-2:]}0603")
    if len(digits) >= 3:
        candidates.append(f"{digits[-3:]}xmu")
        candidates.append(f"xmu{digits[-3:]}")

    seen: set[str] = set()
    ordered: list[str] = []
    for pwd in candidates:
        if pwd not in seen:
            seen.add(pwd)
            ordered.append(pwd)
    return ordered


def _submitter_username(item: dict[str, Any]) -> str:
    """从一条提交记录里取出提交者的登录用户名（学号）。"""
    for key in ("username", "user", "author", "user_id", "real_name"):
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("username") or value.get("id") or value.get("name")
        if value:
            return str(value).strip()
    return ""


async def _list_ac_submitters(ctx: AppContext, contest_id: int, display_id: str) -> list[str]:
    """从公开提交列表取该题 AC 过的账号（去重，保序）。

    直接命中 ``/api/contest_submissions?myself=0&result=0``，再用 _item_accepted 兜底过滤。
    """
    usernames: list[str] = []
    seen: set[str] = set()
    page_size = 12
    for page in range(5):  # 最多翻 5 页，足够找到几个可尝试的账号
        try:
            resp = await ctx.client.get(
                "/api/contest_submissions",
                params={
                    "myself": 0,
                    "result": 0,
                    "username": "",
                    "contest_id": contest_id,
                    "problem_id": display_id,
                    "limit": page_size,
                    "offset": page * page_size,
                },
            )
        except RuntimeError:
            break
        items = extract_items(resp.data, preferred_keys=("submissions", "data"))
        if not items:
            break
        for item in items:
            if not _item_accepted(item):
                continue
            name = _submitter_username(item)
            if name and name not in seen:
                seen.add(name)
                usernames.append(name)
        if len(items) < page_size:
            break
    return usernames


async def _enter_contest(ctx: AppContext, contest_id: int, contest_password: str | None) -> None:
    if contest_password:
        try:
            await ctx.contests.submit_password(contest_id, contest_password)
        except RuntimeError:
            pass


async def _fetch_problem_as_user(
    ctx: AppContext,
    contest_id: int,
    contest_password: str | None,
    username: str,
    password: str,
    display_id: str,
) -> dict[str, Any] | None:
    """以指定账号登录后抓取该题“我自己”的满分代码，失败返回 None。"""
    ctx.session_storage.clear()
    try:
        logged_in = await ctx.auth.login(username, password)
    except RuntimeError:
        return None
    if not logged_in:
        return None
    await _enter_contest(ctx, contest_id, contest_password)
    try:
        return await ctx.submissions.fetch_accepted_code(contest_id, display_id)
    except RuntimeError:
        return None


async def supplement_via_weak_passwords(ctx: AppContext, contest_id: int) -> None:
    """对库里仍缺代码的题目，用弱口令登录 AC 账号补抓。

    AC 账号完全从公开提交列表 API 获取，不使用环境变量里的账号；题目列表 / 提交列表沿用
    正常抓取阶段留下的登录态（并再提交一次比赛密码以确保有比赛访问权限）。
    """
    library = ACLibrary(remote_base_url=ctx.config_storage.config.ac_library_url)
    contest_password = os.getenv("XMUOJ_PILOT_CONTEST_PASSWORD") or ctx.get_contest_password(contest_id)

    # 阶段一：沿用当前登录态，查题目列表 + 每个缺失题目 AC 过的账号（直接从 API 取）。
    await _enter_contest(ctx, contest_id, contest_password)
    problems_data = await problems_flow(ctx, contest_id)
    items = extract_items(problems_data, preferred_keys=("problems",)) if problems_data is not None else []
    if not items:
        console.print("[yellow]弱口令补抓：题目列表为空，跳过。[/yellow]")
        return

    missing: list[tuple[str, int, str, list[str]]] = []
    for item in items:
        display_id = _problem_display_id(item)
        if not display_id:
            continue
        internal_id = _problem_internal_id(item) or _extract_internal_problem_id(item)
        if internal_id is None:
            continue
        existing = library.load_local(internal_id)
        if existing and existing.get("code"):
            continue
        title = str(item.get("title") or item.get("name") or "")
        submitters = await _list_ac_submitters(ctx, contest_id, display_id)
        if submitters:
            missing.append((display_id, internal_id, title, submitters))

    if not missing:
        console.print("[green]弱口令补抓：没有需要补抓的题目。[/green]")
        return
    console.print(
        f"[cyan]弱口令补抓：{len(missing)} 题缺代码，尝试从 AC 账号弱口令登录抓取。[/cyan]"
    )

    # 阶段二：对每个缺失题目，逐个 AC 账号尝试弱口令登录并抓码。
    # 缓存每个账号的口令探测结果，避免跨题重复爆破：命中存密码，全败存 None。
    cracked: dict[str, str | None] = {}
    total_saved = 0
    for display_id, internal_id, title, submitters in missing:
        saved = False
        for username in submitters:
            if username in cracked and cracked[username] is None:
                continue  # 已知这个账号弱口令全败
            record: dict[str, Any] | None = None
            known_password = cracked.get(username)
            if known_password:
                record = await _fetch_problem_as_user(
                    ctx, contest_id, contest_password, username, known_password, display_id
                )
            else:
                for pwd in weak_passwords(username):
                    record = await _fetch_problem_as_user(
                        ctx, contest_id, contest_password, username, pwd, display_id
                    )
                    # 登录失败与登录成功但无代码都返回 None；能抓到代码即视为口令命中。
                    if record and record.get("code"):
                        cracked[username] = pwd
                        console.print(f"[green]弱口令命中：{username} → {display_id}[/green]")
                        break
                else:
                    if username not in cracked:
                        cracked[username] = None
            if record and record.get("code"):
                statement = ""
                try:
                    detail = unwrap_data(await ctx.problems.get_problem(contest_id, display_id))
                    if isinstance(detail, dict):
                        statement = problem_to_markdown(detail)
                except RuntimeError:
                    pass
                path = library.save_record(
                    internal_id,
                    code=record["code"],
                    display_id=display_id,
                    title=title,
                    language=record.get("language", ""),
                    score=record.get("score"),
                    submission_id=record.get("submission_id", ""),
                    contest_id=contest_id,
                    statement=statement,
                )
                console.print(
                    f"[green]弱口令补抓：内部ID {internal_id}（{display_id}）← {username} → {path}[/green]"
                )
                total_saved += 1
                saved = True
                break
        if not saved:
            console.print(f"[dim]{display_id}：弱口令补抓未成功。[/dim]")

    if total_saved:
        library.build_index()
    console.print(f"[green]弱口令补抓完成：新增 {total_saved} 题。[/green]")


async def report_status(ctx: AppContext, contest_id: int) -> tuple[int, int, int, list[str]]:
    """统计该比赛当前入库情况，返回 (题目总数, 已入库, 仍缺, 缺代码题号列表)。

    为拿到完整题目列表，用基础账号重新登录并进入比赛后再列题。
    """
    library = ACLibrary(remote_base_url=ctx.config_storage.config.ac_library_url)
    contest_password = os.getenv("XMUOJ_PILOT_CONTEST_PASSWORD") or ctx.get_contest_password(contest_id)
    accounts = parse_accounts()
    if accounts:
        username, password = accounts[0]
        ctx.session_storage.clear()
        try:
            await ctx.auth.login(username, password)
        except RuntimeError:
            pass
        await _enter_contest(ctx, contest_id, contest_password)

    try:
        data = await ctx.problems.list_problems(contest_id)
    except RuntimeError:
        data = None
    items = extract_items(data, preferred_keys=("problems",)) if data is not None else []

    total = 0
    in_library = 0
    missing_ids: list[str] = []
    for item in items:
        internal_id = _problem_internal_id(item) or _extract_internal_problem_id(item)
        if internal_id is None:
            continue
        total += 1
        existing = library.load_local(internal_id)
        if existing and existing.get("code"):
            in_library += 1
        else:
            missing_ids.append(_problem_display_id(item) or str(internal_id))
    return total, in_library, len(missing_ids), missing_ids


def emit_status(contest_id: int, total: int, in_library: int, missing: int, missing_ids: list[str]) -> None:
    """把某场比赛的入库状态打到日志，并（若配置了）追加到汇总文件供 workflow 输出。"""
    console.print(
        f"[bold cyan]比赛 {contest_id} 状态：题目总数 {total}，已入库(已爬) {in_library}，"
        f"仍缺 {missing}。[/bold cyan]"
    )
    if missing_ids:
        console.print(f"[yellow]仍缺代码题号：{', '.join(missing_ids)}[/yellow]")

    summary_path = os.getenv("XMUOJ_PILOT_SUMMARY_FILE")
    if not summary_path:
        return
    lines = [
        f"### 比赛 {contest_id}",
        "",
        f"- 题目总数：**{total}**",
        f"- 已入库（成功爬到代码）：**{in_library}**",
        f"- 仍缺代码（暂未进入 library）：**{missing}**",
    ]
    if missing_ids:
        lines.append(f"- 仍缺题号：{', '.join(missing_ids)}")
    lines.append("")
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


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

    if _env_flag("XMUOJ_PILOT_WEAK_PASSWORD_FALLBACK"):
        console.print("[cyan]== 启用弱口令补抓 ==[/cyan]")
        await supplement_via_weak_passwords(ctx, contest_id)

    total, in_library, missing, missing_ids = await report_status(ctx, contest_id)
    emit_status(contest_id, total, in_library, missing, missing_ids)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
