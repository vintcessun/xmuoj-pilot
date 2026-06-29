from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Generic, TypeVar

from xmuoj_pilot.ui.console import console, safe_text

T = TypeVar("T")


@dataclass(slots=True)
class SelectOption(Generic[T]):
    label: str
    value: T
    description: str = ""


def select_one(title: str, options: list[SelectOption[T]], *, page_size: int = 12) -> T | None:
    if not options:
        console.print("[yellow]没有可选择的项目。[/yellow]")
        return None

    if not sys.stdin.isatty():
        return _select_one_line(title, options)

    index = 0
    while True:
        _clear_screen()
        console.print(f"[bold cyan]{safe_text(title)}[/bold cyan]")
        console.print("[dim]↑/↓ 选择，←/→ 翻页，Enter 确认，Esc 取消；也可按数字 1-9 快速选择当前页[/dim]\n")

        start = (index // page_size) * page_size
        end = min(start + page_size, len(options))
        for row_index in range(start, end):
            option = options[row_index]
            prefix = ">" if row_index == index else " "
            style = "reverse bold" if row_index == index else ""
            desc = f"  [dim]{safe_text(option.description)}[/dim]" if option.description else ""
            hotkey = row_index - start + 1
            line = f"{prefix} [{hotkey}] {safe_text(option.label)}"
            if style:
                console.print(f"[{style}]{line}[/]{desc}")
            else:
                console.print(f"{line}{desc}")

        console.print(f"\n[dim]第 {start + 1}-{end} 项，共 {len(options)} 项[/dim]")
        key = _read_key()
        if key in {"enter"}:
            return options[index].value
        if key in {"esc", "ctrl_c"}:
            return None
        if key.startswith("digit:"):
            selected = start + int(key.removeprefix("digit:")) - 1
            if start <= selected < end:
                return options[selected].value
        if key in {"up"}:
            index = max(0, index - 1)
        elif key in {"down"}:
            index = min(len(options) - 1, index + 1)
        elif key in {"left"}:
            index = max(0, index - page_size)
        elif key in {"right"}:
            index = min(len(options) - 1, index + page_size)


def _select_one_line(title: str, options: list[SelectOption[T]]) -> T | None:
    console.print(f"[bold cyan]{safe_text(title)}[/bold cyan]")
    for idx, option in enumerate(options, start=1):
        desc = f" - {safe_text(option.description)}" if option.description else ""
        console.print(f"{idx}. {safe_text(option.label)}{desc}")
    raw = input("请输入序号，直接回车取消: ").strip()
    if not raw:
        return None
    if not raw.isdigit():
        return None
    index = int(raw) - 1
    if 0 <= index < len(options):
        return options[index].value
    return None


def _clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _read_key() -> str:
    if sys.platform.startswith("win"):
        return _read_key_windows()
    return _read_key_posix()


def wait_for_key(message: str = "按任意键继续...") -> None:
    console.print(f"[dim]{safe_text(message)}[/dim]")
    if not sys.stdin.isatty():
        input()
        return
    _read_key()


def _read_key_windows() -> str:
    import msvcrt

    char = msvcrt.getwch()
    if char == "\x03":
        return "ctrl_c"
    if char == "\x1b":
        return "esc"
    if char in ("\r", "\n"):
        return "enter"
    if char.isdigit() and char != "0":
        return f"digit:{char}"
    if char in ("\x00", "\xe0"):
        second = msvcrt.getwch()
        return {
            "H": "up",
            "P": "down",
            "K": "left",
            "M": "right",
        }.get(second, "")
    return ""


def _read_key_posix() -> str:
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        char = sys.stdin.read(1)
        if char == "\x03":
            return "ctrl_c"
        if char in ("\r", "\n"):
            return "enter"
        if char.isdigit() and char != "0":
            return f"digit:{char}"
        if char == "\x1b":
            rest = sys.stdin.read(2)
            return {
                "[A": "up",
                "[B": "down",
                "[D": "left",
                "[C": "right",
            }.get(rest, "esc")
        return ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
