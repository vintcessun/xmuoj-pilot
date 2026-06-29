from __future__ import annotations

import sys
from getpass import getpass


def masked_prompt(label: str) -> str:
    """Read a password-like value while echoing '*' for each typed character."""
    if not sys.stdin.isatty():
        return getpass(f"{label}: ")
    print(f"{label}: ", end="", flush=True)
    if sys.platform.startswith("win"):
        return _masked_prompt_windows()
    return _masked_prompt_posix()


def _masked_prompt_windows() -> str:
    import msvcrt

    chars: list[str] = []
    while True:
        char = msvcrt.getwch()
        if char in ("\r", "\n"):
            print()
            return "".join(chars)
        if char == "\x03":
            raise KeyboardInterrupt
        if char == "\x08":
            if chars:
                chars.pop()
                print("\b \b", end="", flush=True)
            continue
        if char in ("\x00", "\xe0"):
            msvcrt.getwch()
            continue
        chars.append(char)
        print("*", end="", flush=True)


def _masked_prompt_posix() -> str:
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    chars: list[str] = []
    try:
        tty.setraw(fd)
        while True:
            char = sys.stdin.read(1)
            if char in ("\r", "\n"):
                print()
                return "".join(chars)
            if char == "\x03":
                raise KeyboardInterrupt
            if char in ("\x7f", "\b"):
                if chars:
                    chars.pop()
                    print("\b \b", end="", flush=True)
                continue
            chars.append(char)
            print("*", end="", flush=True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
