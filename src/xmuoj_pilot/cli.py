from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from xmuoj_pilot.ac_library import ACLibrary
from xmuoj_pilot.ai import AIProvider
from xmuoj_pilot.client import APIResponse, XMUOJClient
from xmuoj_pilot.config import AIConfig
from xmuoj_pilot.services import AuthService, ContestService, ProblemService, SubmissionService
from xmuoj_pilot.storage import ConfigStorage, SessionStorage
from xmuoj_pilot.ui.console import (
    console,
    extract_items,
    preview_file,
    print_banner,
    print_json,
    problem_to_markdown,
    render_contests,
    render_problem_detail,
    render_problems,
    safe_text,
    unwrap_data,
)
from xmuoj_pilot.ui.prompt import masked_prompt
from xmuoj_pilot.ui.select import SelectOption, select_one, wait_for_key

app = typer.Typer(help="XMUOJ Pilot 命令行工具", no_args_is_help=False)


class AppContext:
    def __init__(self) -> None:
        self.config_storage = ConfigStorage()
        self.session_storage = SessionStorage()
        config = self.config_storage.config
        self.client = XMUOJClient(
            base_url=config.base_url,
            storage=self.session_storage,
            debug=config.debug,
            verify_ssl=config.verify_ssl,
        )
        self.auth = AuthService(self.client, self.session_storage)
        self.contests = ContestService(self.client)
        self.problems = ProblemService(self.client)
        self.submissions = SubmissionService(self.client)

    def get_contest_password(self, contest_id: int) -> str | None:
        return self.config_storage.config.contest_passwords.get(str(contest_id))

    def save_contest_password(self, contest_id: int, password: str) -> None:
        passwords = dict(self.config_storage.config.contest_passwords)
        passwords[str(contest_id)] = password
        self.config_storage.update(contest_passwords=passwords)

    @property
    def current_contest_id(self) -> int | None:
        return self.config_storage.config.current_contest_id

    @property
    def current_contest_title(self) -> str:
        return self.config_storage.config.current_contest_title

    def set_current_contest(self, contest_id: int, title: str = "") -> None:
        self.config_storage.update(current_contest_id=contest_id, current_contest_title=title)


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        asyncio.run(interactive_main())


@app.command()
def login() -> None:
    """登录或切换账号。"""
    asyncio.run(login_flow(AppContext()))


@app.command()
def contests(offset: int = 0, limit: int = 15) -> None:
    """获取比赛列表。"""
    asyncio.run(contests_flow(AppContext(), offset=offset, limit=limit))


@app.command()
def contest(contest_id: int) -> None:
    """查看比赛详情和访问权限。"""
    asyncio.run(contest_flow(AppContext(), contest_id))


@app.command()
def problems(contest_id: int) -> None:
    """获取比赛题目列表。"""
    asyncio.run(problems_flow(AppContext(), contest_id))


@app.command()
def problem(contest_id: int, display_problem_id: str) -> None:
    """查看题目详情。"""
    asyncio.run(problem_flow(AppContext(), contest_id, display_problem_id))


@app.command()
def submit(
    contest_id: int,
    display_problem_id: str,
    code_file: Path,
    lang: str = typer.Option("C++", "--lang", "-l", help="提交到 XMUOJ 的语言名称。"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="提交后是否轮询判题结果。"),
) -> None:
    """二次确认后提交本地代码文件。"""
    asyncio.run(submit_flow(AppContext(), contest_id, display_problem_id, code_file, lang, wait))


@app.command("configure-ai")
def configure_ai() -> None:
    """配置 DeepSeek 或 OpenAI-compatible API。"""
    configure_ai_flow(AppContext())


@app.command("debug-api")
def debug_api() -> None:
    """手动发送一个 API 请求用于调试。"""
    asyncio.run(debug_api_flow(AppContext()))


@app.command("test-api")
def test_api(
    contest_id: int | None = typer.Option(None, "--contest-id", "-c", help="要测试的比赛 ID。"),
    display_problem_id: str | None = typer.Option(None, "--problem-id", "-p", help="要测试的显示题号，例如 JD001。"),
    contest_password: str | None = typer.Option(None, "--contest-password", help="可选：比赛密码。"),
    submit_file: Path | None = typer.Option(None, "--submit-file", help="可选：真实测试提交代码文件。"),
    lang: str = typer.Option("C++", "--lang", "-l", help="真实测试提交时使用的语言。"),
) -> None:
    """按登录态逐项测试 XMUOJ API；真实提交仍需输入 yes。"""
    asyncio.run(
        api_smoke_test_flow(
            AppContext(),
            contest_id,
            display_problem_id,
            submit_file,
            lang,
            contest_password=contest_password,
        )
    )


@app.command("study")
def study(
    contest_id: int | None = typer.Option(None, "--contest-id", "-c", help="比赛 ID；不传则使用当前比赛。"),
) -> None:
    """拉取题面并为每题生成 DeepSeek 学习笔记。"""
    ctx = AppContext()
    target = contest_id or ctx.current_contest_id
    if target is None:
        console.print("[red]请先在交互界面选择比赛，或传入 --contest-id。[/red]")
        raise typer.Exit(1)
    asyncio.run(study_task_flow(ctx, target))


@app.command("assist")
def assist(
    contest_id: int | None = typer.Option(None, "--contest-id", "-c", help="比赛 ID；不传则使用当前比赛。"),
    mode: str = typer.Option("semi", "--mode", help="semi=每题人工确认提交；rehearsal=全自动演练到待提交。"),
    limit: int | None = typer.Option(None, "--limit", help="最多处理多少题。"),
) -> None:
    """AI 做题辅助流水线：拉题、生成草稿、编译、样例测试、日志。"""
    if mode not in {"semi", "rehearsal"}:
        console.print("[red]--mode 只能是 semi 或 rehearsal。[/red]")
        raise typer.Exit(1)
    ctx = AppContext()
    target = contest_id or ctx.current_contest_id
    if target is None:
        console.print("[red]请先在交互界面选择比赛，或传入 --contest-id。[/red]")
        raise typer.Exit(1)
    asyncio.run(assist_task_flow(ctx, target, mode=mode, limit=limit))


@app.command("assist-problem")
def assist_problem(
    contest_id: int | None = typer.Option(None, "--contest-id", "-c", help="比赛 ID；不传则使用当前比赛。"),
    display_problem_id: str = typer.Argument(..., help="要测试的显示题号，例如 JD001。"),
    mode: str = typer.Option("semi", "--mode", help="semi=人工确认提交；rehearsal=全自动演练到待提交。"),
) -> None:
    """与 assist 相同的自动做题流程，但只针对手动选定的单题，用于流程测试。"""
    if mode not in {"semi", "rehearsal"}:
        console.print("[red]--mode 只能是 semi 或 rehearsal。[/red]")
        raise typer.Exit(1)
    ctx = AppContext()
    target = contest_id or ctx.current_contest_id
    if target is None:
        console.print("[red]请先在交互界面选择比赛，或传入 --contest-id。[/red]")
        raise typer.Exit(1)
    asyncio.run(assist_single_problem_flow(ctx, target, display_problem_id, mode=mode))


@app.command("fetch-ac")
def fetch_ac(
    contest_id: int | None = typer.Option(None, "--contest-id", "-c", help="比赛 ID；不传则使用当前比赛。"),
) -> None:
    """抓取本账号在该比赛已满分(AC)题目的代码，写入本地 AC 参考代码库并生成索引页。"""
    ctx = AppContext()
    target = contest_id or ctx.current_contest_id
    if target is None:
        console.print("[red]请先在交互界面选择比赛，或传入 --contest-id。[/red]")
        raise typer.Exit(1)
    asyncio.run(fetch_ac_flow(ctx, target))


async def interactive_main() -> None:
    ctx = AppContext()
    print_banner()
    if not await ctx.auth.ensure_login():
        console.print("[yellow]未检测到可用登录状态，请先登录。[/yellow]")
        await login_flow(ctx)

    while True:
        current = (
            f"{ctx.current_contest_id} {ctx.current_contest_title}".strip()
            if ctx.current_contest_id
            else "未选择"
        )
        action = select_one(
            f"主菜单 | 当前比赛：{current}",
            [
                SelectOption("选择比赛", "select-contest", "查看比赛列表并进入比赛"),
                SelectOption("查看当前比赛题目", "problems", "展示当前比赛题目列表"),
                SelectOption("开始学习任务", "study", "批量拉题面、写日志、调用 DeepSeek 生成学习笔记"),
                SelectOption("开始半自动做题", "assist-semi", "生成代码草稿、编译样例、提交前人工确认"),
                SelectOption("全自动演练", "assist-rehearsal", "自动生成和本地验证并提交"),
                SelectOption("测试单题自动做题", "assist-test", "自己选定一题，走与批量任务相同的自动做题流程"),
                SelectOption("登录 / 切换账号", "login"),
                SelectOption("配置 AI Provider", "configure-ai"),
                SelectOption("调试 API 请求", "debug-api"),
                SelectOption("测试 XMUOJ API", "test-api"),
                SelectOption("退出", "exit"),
            ],
        )
        if action in (None, "exit"):
            return
        if action == "login":
            await login_flow(ctx)
        elif action == "select-contest":
            await choose_contest_flow(ctx)
        elif action == "problems":
            if ctx.current_contest_id is None:
                await choose_contest_flow(ctx)
            else:
                await choose_problem_flow(ctx, ctx.current_contest_id)
        elif action == "study":
            if ctx.current_contest_id is None:
                await choose_contest_flow(ctx)
            if ctx.current_contest_id is not None:
                await study_task_flow(ctx, ctx.current_contest_id)
        elif action == "assist-semi":
            if ctx.current_contest_id is None:
                await choose_contest_flow(ctx)
            if ctx.current_contest_id is not None:
                await assist_task_flow(ctx, ctx.current_contest_id, mode="semi")
        elif action == "assist-rehearsal":
            if ctx.current_contest_id is None:
                await choose_contest_flow(ctx)
            if ctx.current_contest_id is not None:
                await assist_task_flow(ctx, ctx.current_contest_id, mode="rehearsal")
        elif action == "assist-test":
            if ctx.current_contest_id is None:
                await choose_contest_flow(ctx)
            if ctx.current_contest_id is not None:
                await choose_problem_for_assist_flow(ctx, ctx.current_contest_id)
        elif action == "configure-ai":
            configure_ai_flow(ctx)
        elif action == "debug-api":
            await debug_api_flow(ctx)
        elif action == "test-api":
            await api_smoke_test_flow(ctx, ctx.current_contest_id, None, None, "C++")


async def login_flow(ctx: AppContext) -> None:
    username = Prompt.ask("用户名")
    password = masked_prompt("密码")
    try:
        ok = await ctx.auth.login(username, password)
    except RuntimeError as exc:
        console.print(f"[red]登录失败：{exc}[/red]")
        return

    if ok:
        console.print("[green]登录成功，session 已保存。[/green]")
        await contests_flow(ctx, offset=0, limit=15)
    else:
        console.print("[red]登录失败，请检查账号密码或 API 返回。[/red]")


async def contests_flow(ctx: AppContext, offset: int = 0, limit: int = 15) -> Any:
    try:
        data = await ctx.contests.list_contests(offset=offset, limit=limit)
    except RuntimeError as exc:
        console.print(f"[red]获取比赛列表失败：{exc}[/red]")
        return None
    render_contests(data)
    return data


async def choose_contest_flow(ctx: AppContext) -> int | None:
    data = await contests_flow(ctx)
    items = extract_items(data, preferred_keys=("contests",)) if data is not None else []
    options: list[SelectOption[tuple[int, str]]] = []
    for item in items:
        contest_id = item.get("id") or item.get("contest_id") or item.get("pk")
        if contest_id is None or not str(contest_id).isdigit():
            continue
        title = str(item.get("title") or item.get("name") or "")
        options.append(SelectOption(f"{contest_id}  {title}", (int(contest_id), title)))

    selected = select_one("选择比赛", options)
    if selected is None:
        return None
    contest_id, title = selected
    ctx.set_current_contest(contest_id, title)
    console.print(f"[green]已选择比赛：{contest_id} {safe_text(title)}[/green]")
    return contest_id


async def contest_flow(ctx: AppContext, contest_id: int) -> tuple[Any, Any] | None:
    try:
        detail = await ctx.contests.get_contest(contest_id)
        access = await ctx.contests.check_access(contest_id)
    except RuntimeError as exc:
        console.print(f"[red]获取比赛信息失败：{exc}[/red]")
        return None

    console.print(
        Panel(escape(safe_text(json.dumps(detail, ensure_ascii=False, indent=2))), title=f"比赛 {contest_id}")
    )
    console.print(Panel(escape(safe_text(json.dumps(access, ensure_ascii=False, indent=2))), title="访问权限"))

    if _looks_password_required(access):
        console.print("[yellow]比赛可能需要密码。[/yellow]")
        password = ctx.get_contest_password(contest_id)
        if password:
            console.print("[dim]正在使用已保存的比赛密码。[/dim]")
        elif Confirm.ask("现在提交比赛密码？", default=True):
            password = masked_prompt("比赛密码")
            ctx.save_contest_password(contest_id, password)
            console.print("[green]比赛密码已保存。[/green]")
        if password:
            try:
                result = await ctx.contests.submit_password(contest_id, password)
                console.print("[green]比赛密码已提交。[/green]")
                print_json(result)
            except RuntimeError as exc:
                console.print(f"[red]提交比赛密码失败：{exc}[/red]")
    return detail, access


async def enter_contest_flow(ctx: AppContext, contest_id: int) -> None:
    await contest_flow(ctx, contest_id)
    await choose_problem_flow(ctx, contest_id)


async def choose_problem_flow(ctx: AppContext, contest_id: int) -> str | None:
    data = await problems_flow(ctx, contest_id)
    items = extract_items(data, preferred_keys=("problems",)) if data is not None else []
    options: list[SelectOption[str]] = []
    for item in items:
        display_id = _problem_display_id(item)
        if not display_id:
            continue
        title = str(item.get("title") or item.get("name") or "")
        internal_id = item.get("id") or item.get("problem_id") or ""
        options.append(SelectOption(f"{display_id}  {title}", display_id, f"内部 ID: {internal_id}"))
    selected = select_one("选择题目", options, page_size=16)
    if selected:
        await problem_flow(ctx, contest_id, selected)
        wait_for_key("按任意键返回主菜单...")
    return selected


async def choose_problem_for_assist_flow(ctx: AppContext, contest_id: int) -> None:
    data = await problems_flow(ctx, contest_id)
    items = extract_items(data, preferred_keys=("problems",)) if data is not None else []
    options: list[SelectOption[str]] = []
    for item in items:
        display_id = _problem_display_id(item)
        if not display_id:
            continue
        title = str(item.get("title") or item.get("name") or "")
        internal_id = item.get("id") or item.get("problem_id") or ""
        options.append(SelectOption(f"{display_id}  {title}", display_id, f"内部 ID: {internal_id}"))
    selected = select_one("选择要测试自动做题流程的题目", options, page_size=16)
    if selected is None:
        return
    mode = Prompt.ask("模式", choices=["semi", "rehearsal"], default="semi")
    await assist_single_problem_flow(ctx, contest_id, selected, mode=mode)


async def problems_flow(ctx: AppContext, contest_id: int) -> Any:
    try:
        data = await ctx.problems.list_problems(contest_id)
    except RuntimeError as exc:
        console.print(f"[red]获取题目列表失败：{exc}[/red]")
        return None
    if _is_wrong_password_response(data) and await ensure_contest_password(ctx, contest_id):
        try:
            data = await ctx.problems.list_problems(contest_id)
        except RuntimeError as exc:
            console.print(f"[red]重新获取题目列表失败：{exc}[/red]")
            return None
    render_problems(data)
    return data


async def problem_flow(ctx: AppContext, contest_id: int, display_problem_id: str) -> Any:
    try:
        data = await ctx.problems.get_problem(contest_id, display_problem_id)
    except RuntimeError as exc:
        console.print(f"[red]获取题目详情失败：{exc}[/red]")
        return None
    if _is_wrong_password_response(data) and await ensure_contest_password(ctx, contest_id):
        try:
            data = await ctx.problems.get_problem(contest_id, display_problem_id)
        except RuntimeError as exc:
            console.print(f"[red]重新获取题目详情失败：{exc}[/red]")
            return None
    render_problem_detail(data)
    return data


async def ensure_contest_password(ctx: AppContext, contest_id: int) -> bool:
    password = ctx.get_contest_password(contest_id)
    if password:
        console.print("[dim]访问比赛需要密码，正在使用已保存的比赛密码。[/dim]")
    elif console.is_interactive:
        console.print("[yellow]访问比赛需要密码。[/yellow]")
        password = masked_prompt("比赛密码")
        ctx.save_contest_password(contest_id, password)
        console.print("[green]比赛密码已保存。[/green]")
    else:
        console.print("[yellow]访问比赛需要密码，但当前是非交互环境且没有已保存密码。[/yellow]")
        return False

    try:
        result = await ctx.contests.submit_password(contest_id, password)
    except RuntimeError as exc:
        console.print(f"[red]提交比赛密码失败：{exc}[/red]")
        return False
    if _is_wrong_password_response(result):
        console.print("[red]比赛密码错误或已过期。[/red]")
        return False
    console.print("[green]比赛密码验证通过。[/green]")
    return True


async def submit_flow(
    ctx: AppContext,
    contest_id: int,
    display_problem_id: str,
    code_file: Path,
    language: str,
    wait: bool,
) -> None:
    if not code_file.exists() or not code_file.is_file():
        console.print(f"[red]代码文件不存在：{code_file}[/red]")
        return

    detail = await problem_flow(ctx, contest_id, display_problem_id)
    if detail is None:
        return
    internal_id = _extract_internal_problem_id(detail)
    if internal_id is None:
        manual = Prompt.ask("未能解析内部 problem_id，请手动输入")
        try:
            internal_id = int(manual)
        except ValueError:
            console.print("[red]内部 problem_id 必须是数字，已取消提交。[/red]")
            return

    try:
        exists = await ctx.submissions.submission_exists(contest_id, internal_id)
    except RuntimeError as exc:
        console.print(f"[yellow]检查历史提交失败：{exc}[/yellow]")
        exists = None

    if exists and _truthy_response(exists):
        console.print("[yellow]检测到该题可能已有提交记录。[/yellow]")
        if not Confirm.ask("继续进入提交预览？", default=False):
            return

    await submit_code_with_confirmation(ctx, contest_id, display_problem_id, internal_id, code_file, language, wait)


async def submit_code_with_confirmation(
    ctx: AppContext,
    contest_id: int,
    display_problem_id: str,
    internal_id: int,
    code_file: Path,
    language: str,
    wait: bool,
) -> Any:
    code = code_file.read_text(encoding="utf-8", errors="replace")
    preview = preview_file(code_file)
    console.print(
        Panel(
            escape(safe_text(
                f"比赛 ID: {contest_id}\n"
                f"显示题号: {display_problem_id}\n"
                f"内部题号: {internal_id}\n"
                f"语言: {language}\n"
                f"代码文件: {code_file.resolve()}\n\n"
                f"{preview}"
            )),
            title="提交预览",
            border_style="yellow",
        )
    )

    try:
        result = await ctx.submissions.submit_code(contest_id, internal_id, language, code)
    except RuntimeError as exc:
        console.print(f"[red]提交失败：{exc}[/red]")
        return None

    console.print("[green]提交请求已发送。[/green]")
    submission_id = _extract_submission_id(result)
    if submission_id:
        console.print(f"[green]submission id:[/green] {submission_id}")
    else:
        console.print("[yellow]未从响应中解析到 submission id。[/yellow]")

    if not submission_id or not wait:
        return result

    with console.status("[cyan]正在等待判题结果...[/cyan]", spinner="dots"):
        final_result = await ctx.submissions.wait_for_result(submission_id)
    render_submission_summary(final_result)
    return final_result


async def study_task_flow(ctx: AppContext, contest_id: int) -> None:
    config = ctx.config_storage.config
    if config.ai is None or not config.ai.api_key:
        console.print("[yellow]还没有配置 AI Provider，请先配置。[/yellow]")
        configure_ai_flow(ctx)
        config = ctx.config_storage.config
        if config.ai is None or not config.ai.api_key:
            return

    problems_data = await problems_flow(ctx, contest_id)
    items = extract_items(problems_data, preferred_keys=("problems",)) if problems_data is not None else []
    if not items:
        return

    output_dir = Path("logs") / f"contest-{contest_id}" / datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    provider = AIProvider(config.ai)
    console.print(f"[green]学习任务日志目录：{output_dir}[/green]")

    for item in items:
        display_id = _problem_display_id(item)
        if not display_id:
            continue
        title = str(item.get("title") or item.get("name") or "")
        console.print(f"[cyan]获取题面：{display_id} {safe_text(title)}[/cyan]")
        detail_data = await ctx.problems.get_problem(contest_id, display_id)
        detail = unwrap_data(detail_data)
        if not isinstance(detail, dict):
            (output_dir / f"{display_id}.error.txt").write_text(str(detail_data), encoding="utf-8")
            continue

        statement = problem_to_markdown(detail)
        problem_dir = output_dir / display_id
        problem_dir.mkdir(parents=True, exist_ok=True)
        (problem_dir / "statement.md").write_text(statement, encoding="utf-8")

        console.print(f"[cyan]调用 DeepSeek：{display_id}[/cyan]")
        try:
            note = await provider.study_problem(statement)
        except Exception as exc:
            (problem_dir / "ai-error.txt").write_text(str(exc), encoding="utf-8")
            console.print(f"[red]AI 调用失败：{display_id}: {exc}[/red]")
            continue
        (problem_dir / "deepseek-note.md").write_text(note, encoding="utf-8")
        console.print(f"[green]已保存：{problem_dir}[/green]")

        if not Confirm.ask("继续下一题？", default=True):
            break


async def assist_task_flow(
    ctx: AppContext,
    contest_id: int,
    *,
    mode: str,
    limit: int | None = None,
) -> None:
    config = ctx.config_storage.config
    if config.ai is None or not config.ai.api_key:
        console.print("[yellow]还没有配置 AI Provider，请先配置。[/yellow]")
        configure_ai_flow(ctx)
        config = ctx.config_storage.config
        if config.ai is None or not config.ai.api_key:
            return

    compiler = shutil.which("g++") or shutil.which("gcc")
    if compiler:
        console.print(f"[green]检测到编译器：{compiler}[/green]")
    else:
        console.print("[yellow]未检测到 g++/gcc，将跳过本地编译。[/yellow]")

    problems_data = await problems_flow(ctx, contest_id)
    items = extract_items(problems_data, preferred_keys=("problems",)) if problems_data is not None else []
    if limit is not None:
        items = items[:limit]
    if not items:
        return

    provider = AIProvider(config.ai)
    run_dir = Path("logs") / f"assist-contest-{contest_id}" / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]辅助任务日志目录：{run_dir}[/green]")

    for item in items:
        await _assist_one_problem(ctx, contest_id, item, mode=mode, compiler=compiler, provider=provider, run_dir=run_dir)


async def assist_single_problem_flow(
    ctx: AppContext,
    contest_id: int,
    display_problem_id: str,
    *,
    mode: str = "semi",
) -> None:
    """选定单题后走与批量任务相同的自动做题流程，用于单题测试。"""
    config = ctx.config_storage.config
    if config.ai is None or not config.ai.api_key:
        console.print("[yellow]还没有配置 AI Provider，请先配置。[/yellow]")
        configure_ai_flow(ctx)
        config = ctx.config_storage.config
        if config.ai is None or not config.ai.api_key:
            return

    compiler = shutil.which("g++") or shutil.which("gcc")
    if compiler:
        console.print(f"[green]检测到编译器：{compiler}[/green]")
    else:
        console.print("[yellow]未检测到 g++/gcc，将跳过本地编译。[/yellow]")

    problems_data = await problems_flow(ctx, contest_id)
    items = extract_items(problems_data, preferred_keys=("problems",)) if problems_data is not None else []
    item = next((candidate for candidate in items if _problem_display_id(candidate) == display_problem_id), None)
    if item is None:
        console.print(f"[red]在题目列表中没有找到 {display_problem_id}。[/red]")
        return

    provider = AIProvider(config.ai)
    run_dir = Path("logs") / f"assist-test-contest-{contest_id}" / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]单题测试日志目录：{run_dir}[/green]")

    await _assist_one_problem(
        ctx,
        contest_id,
        item,
        mode=mode,
        compiler=compiler,
        provider=provider,
        run_dir=run_dir,
        skip_full_score_check=True,
    )


async def fetch_ac_flow(ctx: AppContext, contest_id: int) -> None:
    """抓取该比赛已满分题目的代码到本地 AC 参考代码库，并刷新索引页。"""
    if not await ctx.auth.ensure_login():
        console.print("[yellow]未检测到可用登录状态，请先登录。[/yellow]")
        await login_flow(ctx)

    problems_data = await problems_flow(ctx, contest_id)
    items = extract_items(problems_data, preferred_keys=("problems",)) if problems_data is not None else []
    if not items:
        console.print("[red]题目列表为空或无法解析。[/red]")
        return

    library = ACLibrary(remote_base_url=ctx.config_storage.config.ac_library_url)
    saved = 0
    skipped = 0
    for item in items:
        display_id = _problem_display_id(item)
        if not display_id:
            continue
        internal_id = _problem_internal_id(item) or _extract_internal_problem_id(item)
        if internal_id is None:
            console.print(f"[yellow]{display_id} 无法解析内部 ID，跳过。[/yellow]")
            skipped += 1
            continue
        title = str(item.get("title") or item.get("name") or "")
        try:
            record = await ctx.submissions.fetch_accepted_code(contest_id, display_id)
        except RuntimeError as exc:
            console.print(f"[yellow]{display_id} 抓取提交失败：{exc}[/yellow]")
            record = None
        if not record:
            console.print(f"[dim]{display_id} 未找到满分提交，跳过。[/dim]")
            skipped += 1
            continue

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
        console.print(f"[green]已保存 内部ID {internal_id}（{display_id} 分数 {record.get('score')}）→ {path}[/green]")
        saved += 1

    library.build_index()
    console.print(
        f"[green]完成：保存 {saved} 题，跳过 {skipped} 题。索引页：{library.root / 'index.html'}[/green]"
    )


async def _load_reference_code(
    ctx: AppContext,
    internal_id: int | None,
    problem_dir: Path,
) -> str:
    """按内部 ID 从 AC 参考代码库（本地优先，其次远程）取一份已 AC 代码，拼成提示片段。

    取不到返回空字符串。命中时会把记录落盘到 problem_dir 便于复查。
    """
    if internal_id is None:
        return ""
    library = ACLibrary(remote_base_url=ctx.config_storage.config.ac_library_url)
    try:
        record = await library.get_reference(internal_id)
    except Exception:  # 参考代码是可选增强，任何异常都不应中断做题
        return ""
    if not record or not record.get("code"):
        return ""
    code = str(record["code"])
    _write(
        problem_dir / "reference-ac.json",
        json.dumps(record, ensure_ascii=False, indent=2),
    )
    _append_log(problem_dir, f"已加载该题的一份 AC 参考代码（分数 {record.get('score')}）。")
    return (
        "\n\n---\n以下是该题的一份【已 AC（满分）参考代码】，来自历史提交，"
        "可重点借鉴其输入输出格式与核心逻辑；但请结合题面独立判断，不要原样照抄注释或多余内容：\n"
        f"```c++\n{code}\n```\n"
    )


async def _assist_one_problem(
    ctx: AppContext,
    contest_id: int,
    item: dict[str, Any],
    *,
    mode: str,
    compiler: str | None,
    provider: AIProvider,
    run_dir: Path,
    skip_full_score_check: bool = False,
) -> None:
    display_id = _problem_display_id(item)
    if not display_id:
        return
    title = str(item.get("title") or item.get("name") or "")
    problem_dir = run_dir / display_id
    problem_dir.mkdir(parents=True, exist_ok=True)
    _append_log(problem_dir, f"开始处理 {display_id} {title}")

    item_internal_id = _problem_internal_id(item)
    if not skip_full_score_check:
        if _problem_item_full_score(item):
            _append_log(problem_dir, "题目列表显示已满分，跳过。")
            return
        if item_internal_id is not None and await _already_full_score(ctx, contest_id, item_internal_id, problem_dir):
            _append_log(problem_dir, "检测到已有满分提交，跳过。")
            return

    detail_data = await ctx.problems.get_problem(contest_id, display_id)
    detail = unwrap_data(detail_data)
    if not isinstance(detail, dict):
        _write(problem_dir / "fetch-error.txt", str(detail_data))
        return

    statement = problem_to_markdown(detail)
    _write(problem_dir / "statement.md", statement)
    internal_id = _extract_internal_problem_id(detail_data) or item_internal_id

    user_content = statement
    reference = await _load_reference_code(ctx, internal_id, problem_dir)
    if reference:
        user_content = statement + reference

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": """你是严谨的 C++17 竞赛算法助教。你的目标是在 OJ 上通过题目，而不是生成看起来合理但可能格式错误的代码。

用户会提供【题面】【输入】【输出】【样例】【提示】【数据范围】【OJ反馈】【旧代码】中的一部分或全部。你必须综合这些信息判断真实题意、真实输入格式和真实输出格式。

解题时请在内部充分分析，但最终回答要简洁。

你必须特别注意以下问题：

1. 输入格式裁决：

   * 是单组输入、给定 T 组输入，还是读到 EOF；
   * 题面说“一行”时，通常不要擅自写 while(cin >> ...)；
   * 只有当题面、样例或来源明显暗示多组数据时，才使用循环读入；
   * 如果输入已经保证有序，不要依赖这个保证导致错误；可以排序增强鲁棒性，但不能改变题意。

2. 输出格式裁决：

   * 判断输出是“只输出一种结果”，还是“输出所有满足的结果”；
   * 如果输出词来自多个分类体系，例如类型、性质、状态、等级、原因等，不能直接假设它们互斥；
   * 如果题面说“输出类型/结果/一个字符串”，倾向于单一输出；
   * 如果题面说“若满足……输出……；若还满足……输出……”或样例存在多行，则考虑多行输出；
   * 如果题面列出多个可能输出词，但描述和提示只强调其中一类判断，优先服从题面主任务、样例和 OJ 反馈；
   * 不要因为输出列表里出现某个词，就强行输出它；只有题面明确要求对应条件时才输出。

3. 分类优先级裁决：

   * 如果一个输入可能同时满足多个标签，必须判断题目是否要求多标签输出；
   * 如果只能输出一个标签，必须根据题面顺序、条件包含关系、样例和 OJ 反馈推断优先级；
   * 不要擅自把多个标签组合成多行或空格分隔，除非题面或样例明确支持。

4. 算法与数据范围：

   * 根据数据范围选择算法，不能只写暴力，除非范围允许；
   * 注意整数溢出，必要时使用 long long、__int128 或 double；
   * 浮点题注意 eps，但不要在严格不等式中滥用 eps 导致边界误判；
   * 注意 0、1、负数、极大值、重复元素、空输入、精度、排序、下标越界等边界。

5. OJ 反馈利用：

   * 如果有旧代码和 OJ 反馈，必须优先分析旧代码为何错；
   * 如果旧代码已经部分通过，不要轻易推翻整体输出格式；
   * 小范围 WA 通常优先怀疑边界、精度、优先级、漏掉某类输出；
   * 大范围 WA 才优先怀疑输入输出格式或算法方向；
   * 如果一次修改导致通过点减少，应考虑回退大改，只做最小修复。

最终回答格式：

先简短说明：

* 格式推断
* 核心思路
* 复杂度
* 可能的坑或本次修正点

然后必须给出且只给出一个 Markdown C++ 代码块：

```c++
完整、可编译、可提交的 C++17 代码
```

要求：

* 代码块中只能放代码；
* 不要输出多个代码块；
* 不要输出伪代码；
* 不要发明文件输入输出；
* 不要输出调试信息；
* 不要把解释写进代码块外的第二个代码块；
* 如果题目非常简单，也要给完整 main 函数；
* 除非题目明确要求，否则不要使用非标准库或平台相关代码。
""",
        },
        {"role": "user", "content": user_content},
    ]
    ai_text = await provider.revise_cpp_solution(messages)  # type: ignore[arg-type]
    _write(problem_dir / "ai-01.md", ai_text)
    code = _extract_cpp_code(ai_text)
    if not code:
        _append_log(problem_dir, "AI 输出中未找到 cpp 代码块，跳过。")
        return

    code_path = problem_dir / "solution.cpp"
    _write(code_path, code)
    ai_text, local_ok = await _iterate_local_validation(
        provider=provider,
        messages=messages,
        ai_text=ai_text,
        compiler=compiler,
        code_path=code_path,
        executable_path=problem_dir / "solution.exe",
        problem_dir=problem_dir,
        samples=_extract_samples(detail),
    )

    MAX_SUBMIT_ATTEMPTS = 5

    if mode == "rehearsal":
        if not local_ok:
            _append_log(problem_dir, "本地编译未通过，不进入提交确认。")
            return
        if internal_id is None:
            _append_log(problem_dir, "缺少内部题号，不能提交。")
            return
        for submit_attempt in range(1, MAX_SUBMIT_ATTEMPTS + 1):
            console.print(
                Panel(
                    escape(preview_file(code_path)),
                    title=f"{display_id} 演练模式第 {submit_attempt}/{MAX_SUBMIT_ATTEMPTS} 轮待提交",
                )
            )
            submit_result = await _submit_with_rate_limit_retry(
                ctx, contest_id, display_id, internal_id, code_path, "C++", True, problem_dir
            )
            _write(
                problem_dir
                / f"submission-rehearsal-{submit_attempt:02d}-{datetime.now().strftime('%H%M%S')}.json",
                json.dumps(submit_result, ensure_ascii=False, indent=2),
            )
            if submit_result is None:
                _append_log(problem_dir, "演练模式：用户取消提交，停止当前题。")
                break
            if _submission_accepted(submit_result):
                _append_log(problem_dir, "演练模式提交通过，进入下一题。")
                break

            _append_log(problem_dir, f"演练模式第 {submit_attempt}/{MAX_SUBMIT_ATTEMPTS} 轮提交未通过，进入 ReAct 修复。")
            ai_text, code = await _react_repair_after_oj_failure(
                provider=provider,
                messages=messages,
                last_ai_text=ai_text,
                compiler=compiler,
                code_path=code_path,
                executable_path=problem_dir / "solution.exe",
                problem_dir=problem_dir,
                samples=_extract_samples(detail),
                statement=statement,
                submit_result=submit_result,
                just_failed_attempt=submit_attempt,
                max_attempts=MAX_SUBMIT_ATTEMPTS,
                prefix=f"rehearsal-{submit_attempt:02d}",
            )
            if not code:
                _append_log(problem_dir, "演练模式：ReAct 修复未能给出可提交代码，停止当前题。")
                break
            _write(code_path, code)
        else:
            _append_log(
                problem_dir,
                f"演练模式已达到 {MAX_SUBMIT_ATTEMPTS} 轮提交迭代上限，停止当前题。",
            )
        return

    if internal_id is None:
        _append_log(problem_dir, "缺少内部题号，不能提交。")
        return

    submit_count = 0
    while True:
        if not local_ok:
            _append_log(problem_dir, "本地编译未通过，不进入提交确认。")
            break
        console.print(Panel(escape(preview_file(code_path)), title=f"{display_id} 待确认提交"))
        if Confirm.ask("是否提交这道题？", default=False):
            submit_count += 1
            submit_result = await _submit_with_rate_limit_retry(
                ctx, contest_id, display_id, internal_id, code_path, "C++", True, problem_dir
            )
            _write(
                problem_dir / f"submission-{datetime.now().strftime('%H%M%S')}.json",
                json.dumps(submit_result, ensure_ascii=False, indent=2),
            )
            if _submission_accepted(submit_result):
                _append_log(problem_dir, "提交通过，进入下一题。")
                break

            _append_log(problem_dir, f"第 {submit_count}/{MAX_SUBMIT_ATTEMPTS} 次提交未通过。")
            if submit_count >= MAX_SUBMIT_ATTEMPTS:
                _append_log(problem_dir, f"已达到 {MAX_SUBMIT_ATTEMPTS} 次提交上限，停止当前题。")
                break
            if not Confirm.ask("是否进入 ReAct 修复并继续？", default=True):
                break
            ai_text, code = await _react_repair_after_oj_failure(
                provider=provider,
                messages=messages,
                last_ai_text=ai_text,
                compiler=compiler,
                code_path=code_path,
                executable_path=problem_dir / "solution.exe",
                problem_dir=problem_dir,
                samples=_extract_samples(detail),
                statement=statement,
                submit_result=submit_result,
                just_failed_attempt=submit_count,
                max_attempts=MAX_SUBMIT_ATTEMPTS,
                prefix=f"semi-{submit_count:02d}",
            )
            if not code:
                _append_log(problem_dir, "ReAct 修复未能给出可提交代码。")
                local_ok = False
            else:
                _write(code_path, code)
                local_ok = True
            continue
        reason = Prompt.ask("拒绝提交的理由（会反馈给 AI 修改；留空跳过本题）", default="")
        if not reason:
            _append_log(problem_dir, "用户跳过提交。")
            break
        messages.append({"role": "assistant", "content": ai_text})
        messages.append({"role": "user", "content": f"用户拒绝提交，理由：{reason}\n请据此修改代码。"})
        ai_text = await provider.revise_cpp_solution(messages)  # type: ignore[arg-type]
        _write(problem_dir / f"ai-user-revision-{datetime.now().strftime('%H%M%S')}.md", ai_text)
        code = _extract_cpp_code(ai_text) or code
        _write(code_path, code)
        ai_text, local_ok = await _iterate_local_validation(
            provider=provider,
            messages=messages,
            ai_text=ai_text,
            compiler=compiler,
            code_path=code_path,
            executable_path=problem_dir / "solution.exe",
            problem_dir=problem_dir,
            samples=_extract_samples(detail),
            prefix="user-revision",
        )


def configure_ai_flow(ctx: AppContext) -> None:
    console.print("[yellow]API Key 将保存到本地 config.json。请只在可信设备上配置。[/yellow]")
    provider_choice = Prompt.ask(
        "Provider",
        choices=["deepseek", "openai-compatible"],
        default="deepseek",
    )
    api_key = masked_prompt("API Key")

    if provider_choice == "deepseek":
        base_url = Prompt.ask("Base URL", default="https://api.deepseek.com")
        model = Prompt.ask("Model", default="deepseek-v4-pro")
    else:
        base_url = Prompt.ask("Base URL")
        model = Prompt.ask("Model")

    ctx.config_storage.update(
        ai=AIConfig(
            provider=provider_choice,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
    )
    console.print("[green]AI 配置已保存。[/green]")


async def debug_api_flow(ctx: AppContext) -> None:
    method = Prompt.ask("请求方法", choices=["GET", "POST", "PUT", "PATCH", "DELETE"], default="GET")
    path = Prompt.ask("路径或完整 URL", default="/api/contests?offset=0&limit=15")
    body_text = Prompt.ask("JSON 请求体（留空表示无）", default="")
    referrer = Prompt.ask("Referrer（留空使用默认值）", default="")

    body: dict[str, Any] | None = None
    if body_text:
        try:
            loaded = json.loads(body_text)
        except json.JSONDecodeError as exc:
            console.print(f"[red]JSON 请求体解析失败：{exc}[/red]")
            return
        if not isinstance(loaded, dict):
            console.print("[red]JSON 请求体必须是对象。[/red]")
            return
        body = loaded

    try:
        response = await ctx.client.request(
            method,
            path,
            json=body,
            referrer=referrer or None,
            require_json=False,
            raise_for_status=False,
        )
    except RuntimeError as exc:
        console.print(f"[red]Debug 请求失败：{exc}[/red]")
        return

    render_debug_response(response)


async def api_smoke_test_flow(
    ctx: AppContext,
    contest_id: int | None,
    display_problem_id: str | None,
    submit_file: Path | None,
    language: str,
    *,
    contest_password: str | None = None,
) -> None:
    rows: list[tuple[str, str, str]] = []

    async def run_step(name: str, action: Any) -> Any:
        try:
            result = await action()
        except RuntimeError as exc:
            rows.append((name, "失败", str(exc)))
            return None
        if isinstance(result, dict) and result.get("error"):
            rows.append((name, "失败", safe_text(result.get("data") or result.get("error"))))
            return result
        rows.append((name, "通过", ""))
        return result

    await run_step("GET /", ctx.client.warmup)

    if not await ctx.auth.ensure_login():
        console.print("[yellow]当前没有可用登录态，需要先登录后才能测试认证 API。[/yellow]")
        await login_flow(ctx)

    contests_data = await run_step(
        "GET /api/contests?offset=0&limit=15",
        lambda: ctx.contests.list_contests(offset=0, limit=15),
    )
    if contests_data is not None:
        render_contests(contests_data)

    if contest_id is None:
        contest_id = _extract_first_contest_id(contests_data)
        if contest_id is None:
            contest_id = IntPrompt.ask("请输入要继续测试的比赛 ID")

    await run_step(f"GET /contest/{contest_id}", lambda: ctx.client.get(f"/contest/{contest_id}", require_json=False))
    await run_step(f"GET /api/contest?id={contest_id}", lambda: ctx.contests.get_contest(contest_id))
    access_data = await run_step(
        f"GET /api/contest/access?contest_id={contest_id}",
        lambda: ctx.contests.check_access(contest_id),
    )

    if contest_password:
        ctx.save_contest_password(contest_id, contest_password)
        await run_step(
            "POST /api/contest/password",
            lambda: ctx.contests.submit_password(contest_id, contest_password),
        )
        access_data = await run_step(
            f"GET /api/contest/access?contest_id={contest_id}（密码后）",
            lambda: ctx.contests.check_access(contest_id),
        )
    elif _looks_password_required(access_data):
        console.print("[yellow]访问权限结果显示可能需要比赛密码。[/yellow]")
        if console.is_interactive and Confirm.ask("是否测试 POST /api/contest/password？", default=False):
            password = masked_prompt("比赛密码")
            await run_step(
                "POST /api/contest/password",
                lambda: ctx.contests.submit_password(contest_id, password),
            )
        else:
            rows.append(("POST /api/contest/password", "跳过", "未提供比赛密码"))

    problems_data = await run_step(
        f"GET /api/contest/problem?contest_id={contest_id}",
        lambda: ctx.problems.list_problems(contest_id),
    )
    if problems_data is not None:
        render_problems(problems_data)

    if display_problem_id is None:
        display_problem_id = _extract_first_display_problem_id(problems_data)
        if display_problem_id is None:
            display_problem_id = Prompt.ask("请输入要继续测试的显示题号，例如 JD001")

    problem_data = await run_step(
        f"GET /api/contest/problem?contest_id={contest_id}&problem_id={display_problem_id}",
        lambda: ctx.problems.get_problem(contest_id, display_problem_id),
    )
    if problem_data is not None:
        render_problem_detail(problem_data)

    internal_id = _extract_internal_problem_id(problem_data)
    if internal_id is None:
        if console.is_interactive:
            manual = Prompt.ask("未能解析内部 problem_id；留空则跳过提交相关 API", default="")
            internal_id = int(manual) if manual.isdigit() else None
        else:
            rows.append(("解析内部 problem_id", "跳过", "非交互环境且响应中没有可解析 ID"))

    if internal_id is not None:
        await run_step(
            f"GET /api/submission_exists?problem_id={internal_id}&contest_id={contest_id}",
            lambda: ctx.submissions.submission_exists(contest_id, internal_id),
        )

    if submit_file is not None:
        if internal_id is None:
            rows.append(("POST /api/submission", "跳过", "缺少内部 problem_id"))
        elif not submit_file.exists():
            rows.append(("POST /api/submission", "跳过", f"文件不存在：{submit_file}"))
        else:
            result = await submit_code_with_confirmation(
                ctx,
                contest_id,
                display_problem_id,
                internal_id,
                submit_file,
                language,
                wait=True,
            )
            rows.append(("POST /api/submission + GET /api/submission", "通过" if result else "跳过", ""))
    else:
        rows.append(("POST /api/submission", "跳过", "未提供 --submit-file；真实提交必须手动确认"))
        rows.append(("GET /api/submission?id=...", "跳过", "需要真实 submission id"))

    render_api_test_report(rows)


def render_debug_response(response: APIResponse) -> None:
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() in {"content-type", "content-length", "set-cookie", "date", "server"}
    }
    console.print(Panel(str(response.status_code), title="状态码"))
    console.print(Panel(escape(json.dumps(headers, ensure_ascii=False, indent=2)), title="响应头摘要"))
    if isinstance(response.data, (dict, list)):
        print_json(response.data)
    else:
        console.print(Panel(escape(safe_text(str(response.data)[:2000])), title="响应文本"))
    console.print(f"cookies 是否更新：{response.cookies_updated}；csrf 是否更新：{response.csrf_updated}")


def render_api_test_report(rows: list[tuple[str, str, str]]) -> None:
    table = Table(title="API 测试报告")
    table.add_column("接口")
    table.add_column("结果", no_wrap=True)
    table.add_column("说明")
    for name, status, message in rows:
        style = "green" if status == "通过" else "yellow" if status == "跳过" else "red"
        table.add_row(safe_text(name), f"[{style}]{status}[/{style}]", escape(safe_text(message)))
    console.print(table)


def render_submission_summary(data: Any) -> None:
    payload = data.get("data") if isinstance(data, dict) else data
    if not isinstance(payload, dict):
        console.print(Panel(escape(safe_text(data)), title="判题摘要"))
        return

    statistic = payload.get("statistic_info") if isinstance(payload.get("statistic_info"), dict) else {}
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    cases = info.get("data") if isinstance(info.get("data"), list) else []
    passed = 0
    total = len(cases)
    score_from_cases = 0
    for case in cases:
        if isinstance(case, dict):
            if case.get("result") == 0 and case.get("error") == 0:
                passed += 1
            if isinstance(case.get("score"), (int, float)):
                score_from_cases += case["score"]

    score = statistic.get("score", score_from_cases if total else "未知")
    result = payload.get("result", "未知")
    time_cost = statistic.get("time_cost", "未知")
    memory_cost = statistic.get("memory_cost", "未知")

    lines = [
        f"提交 ID: {payload.get('id', '未知')}",
        f"结果码: {result}",
        f"分数: {score}",
        f"测试点: {passed}/{total}" if total else "测试点: 无详情",
        f"耗时: {time_cost}",
        f"内存: {memory_cost}",
    ]
    if data.get("error") if isinstance(data, dict) else False:
        lines.append(f"错误: {data.get('data')}")
    console.print(Panel("\n".join(safe_text(line) for line in lines), title="判题摘要"))


def _looks_password_required(data: Any) -> bool:
    text = str(data).lower()
    return any(
        word in text
        for word in ("password", "forbidden", "permission", "access denied", "need password", "需要密码")
    )


def _is_wrong_password_response(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if not data.get("error"):
        return False
    return "password" in str(data.get("data") or data.get("error")).lower()


def _truthy_response(data: Any) -> bool:
    if isinstance(data, bool):
        return data
    if isinstance(data, dict):
        for key in ("exists", "data", "result", "submitted", "success"):
            value = data.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, dict) and _truthy_response(value):
                return True
    return False


def _extract_internal_problem_id(data: Any) -> int | None:
    detail = unwrap_data(data)
    candidates: list[Any] = []
    if isinstance(detail, dict):
        candidates.extend(
            [
                detail.get("id"),
                detail.get("problem_id"),
                detail.get("problemId"),
                detail.get("internal_problem_id"),
            ]
        )
    for item in extract_items(data, preferred_keys=("problems",)):
        candidates.extend([item.get("id"), item.get("problem_id"), item.get("problemId")])

    for candidate in candidates:
        try:
            if candidate is not None and str(candidate).isdigit():
                return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _extract_submission_id(data: Any) -> str | None:
    if isinstance(data, dict):
        for key in ("id", "submission_id", "submissionId"):
            value = data.get(key)
            if value:
                return str(value)
        for key in ("data", "result", "submission"):
            value = data.get(key)
            nested = _extract_submission_id(value)
            if nested:
                return nested
    return None


def _extract_wait_seconds(data: Any) -> int | None:
    text = str(data.get("data") if isinstance(data, dict) else data)
    match = re.search(r"wait\s+(\d+)\s*seconds?", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


async def _submit_with_rate_limit_retry(
    ctx: AppContext,
    contest_id: int,
    display_problem_id: str,
    internal_id: int,
    code_path: Path,
    language: str,
    wait: bool,
    problem_dir: Path,
    *,
    max_wait_retries: int = 5,
) -> Any:
    result: Any = None
    for _ in range(max_wait_retries + 1):
        result = await submit_code_with_confirmation(
            ctx, contest_id, display_problem_id, internal_id, code_path, language, wait
        )
        wait_seconds = _extract_wait_seconds(result)
        if wait_seconds is None:
            return result
        sleep_seconds = wait_seconds + 1
        _append_log(problem_dir, f"提交被限流（{result!r}），等待 {sleep_seconds} 秒后用相同代码重新提交。")
        await asyncio.sleep(sleep_seconds)
    return result


def _submission_accepted(data: Any) -> bool:
    payload = data.get("data") if isinstance(data, dict) else data
    if not isinstance(payload, dict):
        return False
    statistic_info = payload.get("statistic_info")
    if isinstance(statistic_info, dict):
        score = statistic_info.get("score")
        if isinstance(score, (int, float)) and score >= 100:
            return True
    return payload.get("result") == 0 and bool(statistic_info)


async def _already_full_score(
    ctx: AppContext,
    contest_id: int,
    internal_id: int,
    problem_dir: Path,
) -> bool:
    try:
        exists = await ctx.submissions.submission_exists(contest_id, internal_id)
    except RuntimeError as exc:
        _append_log(problem_dir, f"检查已有提交失败，继续处理：{exc}")
        return False
    _write(problem_dir / "submission_exists.json", json.dumps(exists, ensure_ascii=False, indent=2))
    if isinstance(exists, dict) and exists.get("data") is False:
        return False
    # XMUOJ 的 submission_exists 只告诉是否提交过；满分状态通常在题目列表 my_status/statistic_info。
    return False


def _extract_first_contest_id(data: Any) -> int | None:
    for item in extract_items(data, preferred_keys=("contests",)):
        value = item.get("id") or item.get("contest_id") or item.get("pk")
        if value is not None and str(value).isdigit():
            return int(value)
    return None


def _extract_first_display_problem_id(data: Any) -> str | None:
    for item in extract_items(data, preferred_keys=("problems",)):
        value = _problem_display_id(item)
        if value:
            return str(value)
    return None


def _problem_display_id(item: dict[str, Any]) -> str:
    value = (
        item.get("_id")
        or item.get("display_id")
        or item.get("displayId")
        or item.get("number")
        or item.get("code")
    )
    return str(value) if value else ""


def _problem_internal_id(item: dict[str, Any]) -> int | None:
    value = item.get("id") or item.get("problem_id") or item.get("problemId")
    if value is not None and str(value).isdigit():
        return int(value)
    return None


def _problem_item_full_score(item: dict[str, Any]) -> bool:
    if item.get("my_status") == 0:
        return True
    statistic = item.get("statistic_info")
    total_score = item.get("total_score") or item.get("score")
    if isinstance(statistic, dict) and "score" in statistic:
        try:
            return float(statistic["score"]) >= float(total_score or 100)
        except (TypeError, ValueError):
            return False
    status = str(item.get("status") or item.get("result") or "").lower()
    return status in {"accepted", "ac", "通过", "满分"}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read_optional(path: Path) -> str:
    if not path.exists():
        return f"{path.name} 不存在，可能是前一步未执行。\n"
    return path.read_text(encoding="utf-8", errors="replace")


async def _iterate_local_validation(
    *,
    provider: AIProvider,
    messages: list[dict[str, str]],
    ai_text: str,
    compiler: str | None,
    code_path: Path,
    executable_path: Path,
    problem_dir: Path,
    samples: list[tuple[str, str]],
    prefix: str = "local",
    max_attempts: int = 3,
) -> tuple[str, bool]:
    if not compiler:
        _append_log(problem_dir, "未检测到编译器，跳过本地编译迭代。")
        return ai_text, False

    for attempt in range(1, max_attempts + 1):
        stamp = f"{prefix}-{attempt}"
        compile_ok, compile_output = _compile_cpp(compiler, code_path, executable_path)
        _write(problem_dir / f"compile-{stamp}.log", compile_output)
        _write(problem_dir / "compile.log", compile_output)
        if not compile_ok:
            _append_log(problem_dir, f"第 {attempt} 轮编译失败，反馈给 DeepSeek 修复。")
            feedback = _read_optional(problem_dir / f"compile-{stamp}.log")
            ai_text = await _revise_after_local_failure(
                provider=provider,
                messages=messages,
                ai_text=ai_text,
                feedback=f"编译失败，请修复 C++17 代码。\n{feedback}",
                code_path=code_path,
                output_path=problem_dir / f"ai-{stamp}-compile-fix.md",
            )
            continue

        _append_log(problem_dir, f"第 {attempt} 轮编译通过。")
        # 样例结果仅作记录，不作为是否允许提交的强制限制；
        # 只有提交到 OJ 后判题未通过时，才会把样例结果附带给 AI 参考。
        sample_ok, sample_output = _run_samples(executable_path, samples)
        _write(problem_dir / f"samples-{stamp}.log", sample_output)
        _write(problem_dir / "samples.log", sample_output)
        _append_log(problem_dir, f"第 {attempt} 轮样例{'通过' if sample_ok else '未全部通过（仅记录，不阻止提交）'}。")
        return ai_text, True

    compile_ok, compile_output = _compile_cpp(compiler, code_path, executable_path)
    _write(problem_dir / f"compile-{prefix}-final.log", compile_output)
    if compile_ok:
        _append_log(problem_dir, "本地编译通过，允许进入提交确认。")
        return ai_text, True

    _append_log(problem_dir, f"本地编译迭代达到上限 {max_attempts}，仍未通过，阻止提交确认。")
    return ai_text, False


async def _revise_after_local_failure(
    *,
    provider: AIProvider,
    messages: list[dict[str, str]],
    ai_text: str,
    feedback: str,
    code_path: Path,
    output_path: Path,
) -> str:
    messages.append({"role": "assistant", "content": ai_text})
    messages.append(
        {
            "role": "user",
            "content": feedback
            + "\n\n可以先简短分析失败原因和修复依据。请把最终的代码写入到一个 Markdown 代码块，格式必须是：\n"
            "```c++\n"
            "中间是完整可编译 C++17 代码\n"
            "```",
        }
    )
    revised = await provider.revise_cpp_solution(messages)  # type: ignore[arg-type]
    _write(output_path, revised)
    code = _extract_cpp_code(revised)
    if code:
        _write(code_path, code)
    return revised


def _build_react_kickoff(
    *,
    statement: str,
    submit_result: Any,
    sample_feedback: str,
    just_failed_attempt: int,
    max_attempts: int,
) -> str:
    if just_failed_attempt <= 1:
        escalation = (
            "本轮策略（最小修复）：先做失败归因，从【代码实现错误】【样例本身弱或错】【题意理解错误】"
            "三类里判断主因，再做最小必要修改，不要推翻已经通过的部分。"
        )
    else:
        escalation = (
            "本轮策略（深度修复）：允许重读题面、质疑样例、重建“题意契约”、必要时更换算法或整体输出解释。"
            "尤其当本地样例全过但 OJ 仍判错时，第一假设应该是“题意理解错误”而不是小 bug。"
        )
    return (
        f"OJ 第 {just_failed_attempt}/{max_attempts} 次提交未通过。"
        "现在进入 ReAct 修复模式：你将通过“思考 + 一个行动”逐步定位并修复问题。\n\n"
        + escalation
        + "\n\n可用行动（每次只能选一个）：\n"
        "1. 重读题面 —— 框架会把题面和样例重新发给你；\n"
        "2. 写代码 —— 紧接着给出且只给出一个 ```c++ 代码块，框架会本地编译并用样例试跑，再把结果回给你；\n"
        "3. 质疑样例 —— 当你认为某个样例错误或题意有歧义时，写出你的判断和你将采用的解释，框架不会强迫你迁就坏样例；\n"
        "4. 完成 —— 当你对“已经本地编译通过”的那份代码有信心时，请求提交到 OJ。\n\n"
        "输出格式必须是：\n"
        "思考：<你的推理>\n"
        "行动：<重读题面 | 写代码 | 质疑样例 | 完成>\n"
        "（写代码时紧跟一个 ```c++ 代码块；质疑样例时写出你的判断）\n\n"
        "本次判题结果：\n"
        + json.dumps(submit_result, ensure_ascii=False, indent=2)
        + "\n\n本地样例试跑（仅供参考，样例可能很弱甚至有错）：\n"
        + sample_feedback
    )


def _parse_react_action(text: str) -> str:
    for keyword in ("写代码", "重读题面", "质疑样例", "完成"):
        if re.search(rf"行动\s*[:：]\s*\**\s*{keyword}", text):
            return keyword
    # 没写明确行动，但带了代码块，按“写代码”处理
    if _extract_cpp_code(text):
        return "写代码"
    return ""


async def _react_repair_after_oj_failure(
    *,
    provider: AIProvider,
    messages: list[dict[str, str]],
    last_ai_text: str,
    compiler: str | None,
    code_path: Path,
    executable_path: Path,
    problem_dir: Path,
    samples: list[tuple[str, str]],
    statement: str,
    submit_result: Any,
    just_failed_attempt: int,
    max_attempts: int,
    prefix: str,
    max_steps: int = 6,
) -> tuple[str, str | None]:
    """OJ 提交失败后进入的 ReAct 修复循环。

    全程复用同一条 messages（同一题同一对话，不重置上下文），返回
    (最新 ai_text, 本地编译通过的候选代码或 None)。OJ 提交仍由外层循环控制，
    本函数只负责“思考-行动-观察”地产出下一份候选代码。
    """
    sample_feedback = _read_optional(problem_dir / "samples.log")
    trace_path = problem_dir / f"react-{prefix}.md"
    messages.append({"role": "assistant", "content": last_ai_text})
    messages.append(
        {
            "role": "user",
            "content": _build_react_kickoff(
                statement=statement,
                submit_result=submit_result,
                sample_feedback=sample_feedback,
                just_failed_attempt=just_failed_attempt,
                max_attempts=max_attempts,
            ),
        }
    )

    last_compiled_code: str | None = None
    ai_text = last_ai_text
    for step in range(1, max_steps + 1):
        ai_text = await provider.chat(messages)  # type: ignore[arg-type]
        _append_file(trace_path, f"### 第 {step} 步（模型）\n{ai_text}\n\n")
        messages.append({"role": "assistant", "content": ai_text})
        action = _parse_react_action(ai_text)
        _append_log(problem_dir, f"ReAct[{prefix}] 第 {step} 步行动：{action or '未识别'}")

        if action == "重读题面":
            observation = "【题面重发】\n" + statement
        elif action == "质疑样例":
            observation = (
                "已记录你对样例/题意的质疑。框架不会强迫你迁就可能错误的样例。"
                "请继续：要么用【写代码】给出你按自己解释实现的代码，要么用【重读题面】再确认，"
                "要么在确有信心时用【完成】请求提交。"
            )
        elif action == "写代码":
            code = _extract_cpp_code(ai_text)
            if not code:
                observation = "没有解析到 ```c++ 代码块。请用【写代码】并给出且只给出一个 ```c++ 代码块。"
            else:
                _write(code_path, code)
                if not compiler:
                    last_compiled_code = code
                    observation = "本地没有编译器，无法编译验证，已采用你这份代码。若有信心可用【完成】请求提交。"
                else:
                    compile_ok, compile_output = _compile_cpp(compiler, code_path, executable_path)
                    _write(problem_dir / f"compile-react-{prefix}-{step}.log", compile_output)
                    if not compile_ok:
                        observation = "编译失败，请修复后再用【写代码】：\n" + compile_output
                    else:
                        last_compiled_code = code
                        sample_ok, sample_output = _run_samples(executable_path, samples)
                        _write(problem_dir / "samples.log", sample_output)
                        observation = (
                            "编译通过。本地样例试跑结果如下（仅供参考，样例可能弱或错，"
                            "不要为了迁就样例而违背你判断的真实题意）：\n"
                            + sample_output
                            + "\n如对当前代码有信心，请用【完成】请求提交；否则继续分析或改代码。"
                        )
        elif action == "完成":
            if last_compiled_code is not None:
                _append_log(problem_dir, f"ReAct[{prefix}]：模型请求提交当前候选代码。")
                return ai_text, last_compiled_code
            observation = "目前还没有【写代码】并本地编译通过的候选代码，请先用【写代码】给出可编译代码。"
        else:
            observation = (
                "未识别到合法行动。请严格按格式：先“思考：”，再“行动：<重读题面|写代码|质疑样例|完成>”。"
            )
        _append_file(trace_path, f"### 第 {step} 步（观察）\n{observation}\n\n")
        messages.append({"role": "user", "content": observation})

    if last_compiled_code is not None:
        _append_log(problem_dir, f"ReAct[{prefix}] 达到 {max_steps} 步上限，提交最后一份可编译候选代码。")
        return ai_text, last_compiled_code
    _append_log(problem_dir, f"ReAct[{prefix}] 达到 {max_steps} 步上限，仍无可编译候选代码。")
    return ai_text, None


def _append_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


def _append_log(problem_dir: Path, message: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}\n"
    with (problem_dir / "task.log").open("a", encoding="utf-8") as fh:
        fh.write(line)
    console.print(safe_text(message))


def _extract_cpp_code(text: str) -> str:
    match = re.search(r"```(?:c\+\+|cpp|cxx)\s*\n(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if not match:
        match = re.search(r"```\s*\n(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _compile_cpp(compiler: str, source: Path, output: Path) -> tuple[bool, str]:
    source = source.resolve()
    output = output.resolve()
    log = f"command: {compiler} -std=c++17 -O2 {source.name} -o {output.name}\n"
    try:
        result = subprocess.run(
            [compiler, "-std=c++17", "-O2", str(source), "-o", str(output)],
            cwd=str(source.parent),
            capture_output=True,
            text=True,
            timeout=20,
        )
    except FileNotFoundError as exc:
        log += f"returncode: -1\nstdout:\n\nstderr:\n编译器或源文件不存在：{exc}\n"
        return False, log
    except subprocess.TimeoutExpired as exc:
        log += f"returncode: -1\nstdout:\n{exc.stdout or ''}\nstderr:\n编译超时。\n{exc.stderr or ''}\n"
        return False, log
    log += f"returncode: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}\n"
    return result.returncode == 0, log


def _extract_samples(detail: dict[str, Any]) -> list[tuple[str, str]]:
    raw = detail.get("samples") or detail.get("sample") or []
    samples: list[tuple[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                sample_in = item.get("input") or item.get("sample_input") or item.get("in") or ""
                sample_out = item.get("output") or item.get("sample_output") or item.get("out") or ""
                if sample_in or sample_out:
                    samples.append((str(sample_in), str(sample_out)))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                samples.append((str(item[0]), str(item[1])))
    return samples


def _run_samples(executable: Path, samples: list[tuple[str, str]]) -> tuple[bool, str]:
    if not samples:
        return True, "没有样例，跳过样例运行。\n"
    executable = executable.resolve()
    logs: list[str] = []
    ok = True
    for index, (sample_in, expected) in enumerate(samples, start=1):
        try:
            result = subprocess.run(
                [str(executable)],
                cwd=str(executable.parent),
                input=sample_in,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except FileNotFoundError as exc:
            ok = False
            logs.append(
                f"sample {index}: FAIL\n"
                f"returncode: -1\ninput:\n{sample_in}\nexpected:\n{expected.strip()}\n"
                f"actual:\n\nstderr:\nFILE_NOT_FOUND: 可执行文件不存在：{executable}\n{exc}\n"
            )
            continue
        except subprocess.TimeoutExpired as exc:
            ok = False
            logs.append(
                f"sample {index}: FAIL\n"
                f"returncode: -1\ninput:\n{sample_in}\nexpected:\n{expected.strip()}\n"
                f"actual:\n{exc.stdout or ''}\nstderr:\n运行超时。\n{exc.stderr or ''}\n"
            )
            continue
        actual = result.stdout.strip()
        want = expected.strip()
        passed = result.returncode == 0 and actual == want
        ok = ok and passed
        logs.append(
            f"sample {index}: {'PASS' if passed else 'FAIL'}\n"
            f"returncode: {result.returncode}\ninput:\n{sample_in}\nexpected:\n{want}\nactual:\n{actual}\nstderr:\n{result.stderr}\n"
        )
    return ok, "\n".join(logs)
