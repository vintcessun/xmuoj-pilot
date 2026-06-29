from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.pretty import Pretty
from rich.table import Table
from rich.text import Text

from xmuoj_pilot.models import Contest, Problem

console = Console()


def safe_text(value: Any) -> str:
    text = str(value)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def print_banner() -> None:
    text = Text("XMUOJ Pilot", style="bold cyan")
    text.append("\n厦大 OJ 命令行学习辅助工具", style="dim")
    console.print(Panel(text, border_style="cyan"))


def print_json(data: Any) -> None:
    console.print(Pretty(data, expand_all=False))


def extract_items(data: Any, preferred_keys: Iterable[str] = ()) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    if not isinstance(data, dict):
        return []

    keys = list(preferred_keys) + [
        "data",
        "results",
        "items",
        "list",
        "rows",
        "contests",
        "problems",
    ]
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = extract_items(value, preferred_keys=preferred_keys)
            if nested:
                return nested

    for value in data.values():
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            return value

    return []


def unwrap_data(data: Any) -> Any:
    if isinstance(data, dict):
        for key in ("data", "result", "detail", "problem", "contest", "submission"):
            value = data.get(key)
            if isinstance(value, dict):
                return value
    return data


def render_contests(data: Any) -> None:
    items = extract_items(data, preferred_keys=("contests",))
    if not items:
        console.print("[yellow]未识别到比赛列表，原始响应如下：[/yellow]")
        print_json(data)
        return

    table = Table(title="比赛列表")
    table.add_column("比赛 ID", style="cyan", no_wrap=True)
    table.add_column("标题")
    table.add_column("开始时间")
    table.add_column("结束时间")
    table.add_column("状态")

    for item in items:
        contest = Contest.from_raw(item)
        table.add_row(
            str(contest.id or ""),
            safe_text(contest.title),
            safe_text(contest.start_time),
            safe_text(contest.end_time),
            safe_text(contest.status),
        )
    console.print(table)


def render_problems(data: Any) -> None:
    items = extract_items(data, preferred_keys=("problems",))
    if not items:
        console.print("[yellow]未识别到题目列表，原始响应如下：[/yellow]")
        print_json(data)
        return

    table = Table(title="题目列表")
    table.add_column("内部 ID", style="cyan", no_wrap=True)
    table.add_column("显示题号", style="green", no_wrap=True)
    table.add_column("标题")
    table.add_column("分数")
    table.add_column("状态")

    for item in items:
        problem = Problem.from_raw(item)
        table.add_row(
            str(problem.internal_id or ""),
            safe_text(problem.display_id),
            safe_text(problem.title),
            safe_text(problem.score),
            safe_text(problem.status),
        )
    console.print(table)


def render_problem_detail(data: Any) -> None:
    detail = unwrap_data(data)
    if not isinstance(detail, dict):
        console.print(Panel(escape(safe_text(data)), title="题目详情"))
        return

    title = str(detail.get("title") or detail.get("name") or detail.get("problem_title") or "题目详情")
    body = problem_to_markdown(detail)
    console.print(Panel(escape(safe_text(body)), title=escape(safe_text(title))))


def problem_to_markdown(detail: dict[str, Any]) -> str:
    fields = [
        ("显示题号", detail.get("_id") or detail.get("display_id") or detail.get("displayId") or detail.get("code")),
        ("内部 ID", detail.get("id") or detail.get("problem_id") or detail.get("problemId")),
        ("时间限制", detail.get("time_limit") or detail.get("timeLimit")),
        ("内存限制", detail.get("memory_limit") or detail.get("memoryLimit")),
    ]
    lines = [f"{name}: {safe_text(value)}" for name, value in fields if value not in (None, "")]

    labels = {
        "description": "题目描述",
        "content": "题面内容",
        "statement": "题面",
        "input_description": "输入描述",
        "output_description": "输出描述",
        "input": "输入",
        "output": "输出",
        "samples": "样例",
        "sample": "样例",
        "hint": "提示",
    }
    for key, label in labels.items():
        value = detail.get(key)
        if value:
            lines.append(f"\n## {label}\n{safe_text(html_to_text(value))}")

    return "\n".join(lines) or json.dumps(detail, ensure_ascii=False, indent=2)


def html_to_text(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    parser = _HTMLToTextParser()
    parser.feed(str(value))
    text = parser.text()
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class _HTMLToTextParser(HTMLParser):
    block_tags = {"p", "div", "br", "li", "tr", "pre", "h1", "h2", "h3", "h4", "table"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def preview_file(path: Path, line_count: int = 20) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    preview = "\n".join(f"{idx + 1:>4}: {safe_text(line)}" for idx, line in enumerate(lines[:line_count]))
    if len(lines) > line_count:
        preview += f"\n...（还有 {len(lines) - line_count} 行）"
    return preview
