"""已 AC（满分）参考代码库。

目录结构（默认相对当前工作目录的 ``ac-library/``，可被 git 跟踪、拉取）：

    ac-library/
        index.html                     # 总索引页（可拉取/可托管到 GitHub Pages）
        index.json                     # 机器可读的总索引
        contest-<id>/
            index.html                 # 单场比赛索引页
            <display_id>.json          # 单题记录（含 AC 代码）

记录字段：contest_id, problem_id, title, language, score, submission_id,
fetched_at, code。

做题流程可通过 :meth:`ACLibrary.get_reference` 先查本地、再查远程（GitHub Pages
等静态托管）拿到参考代码。
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


def default_library_dir() -> Path:
    env = os.getenv("XMUOJ_PILOT_AC_LIBRARY_DIR")
    if env:
        return Path(env)
    return Path("ac-library")


class ACLibrary:
    def __init__(self, root: Path | None = None, *, remote_base_url: str | None = None) -> None:
        self.root = root or default_library_dir()
        # 远程基址，例如 https://<user>.github.io/<repo>/ac-library
        self.remote_base_url = (remote_base_url or os.getenv("XMUOJ_PILOT_AC_LIBRARY_URL") or "").rstrip("/")

    # ---- 路径 ----
    def contest_dir(self, contest_id: int) -> Path:
        return self.root / f"contest-{contest_id}"

    def record_path(self, contest_id: int, display_problem_id: str) -> Path:
        return self.contest_dir(contest_id) / f"{display_problem_id}.json"

    # ---- 读写单题记录 ----
    def save_record(
        self,
        contest_id: int,
        display_problem_id: str,
        *,
        code: str,
        title: str = "",
        language: str = "",
        score: Any = None,
        submission_id: str = "",
        statement: str = "",
    ) -> Path:
        record = {
            "contest_id": contest_id,
            "problem_id": display_problem_id,
            "title": title,
            "language": language,
            "score": score,
            "submission_id": submission_id,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "statement": statement,
            "code": code,
        }
        path = self.record_path(contest_id, display_problem_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_local(self, contest_id: int, display_problem_id: str) -> dict[str, Any] | None:
        path = self.record_path(contest_id, display_problem_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    async def fetch_remote(self, contest_id: int, display_problem_id: str) -> dict[str, Any] | None:
        if not self.remote_base_url:
            return None
        url = f"{self.remote_base_url}/contest-{contest_id}/{display_problem_id}.json"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=True) as client:
                response = await client.get(url)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    async def get_reference(self, contest_id: int, display_problem_id: str) -> dict[str, Any] | None:
        """先本地后远程地获取参考记录；含非空 code 才算命中。"""
        record = self.load_local(contest_id, display_problem_id)
        if record and record.get("code"):
            return record
        remote = await self.fetch_remote(contest_id, display_problem_id)
        if remote and remote.get("code"):
            return remote
        return None

    # ---- 索引页 ----
    def build_index(self) -> None:
        if not self.root.exists():
            return
        contests: list[tuple[int, list[dict[str, Any]]]] = []
        for contest_dir in sorted(self.root.glob("contest-*")):
            if not contest_dir.is_dir():
                continue
            try:
                contest_id = int(contest_dir.name.split("-", 1)[1])
            except (IndexError, ValueError):
                continue
            records: list[dict[str, Any]] = []
            for record_path in sorted(contest_dir.glob("*.json")):
                try:
                    data = json.loads(record_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(data, dict):
                    records.append(data)
            if records:
                contests.append((contest_id, records))
                self._write_contest_page(contest_dir, contest_id, records)

        index_json = [
            {
                "contest_id": contest_id,
                "problems": [
                    {
                        "problem_id": r.get("problem_id"),
                        "title": r.get("title"),
                        "score": r.get("score"),
                        "language": r.get("language"),
                        "path": f"contest-{contest_id}/{r.get('problem_id')}.json",
                    }
                    for r in records
                ],
            }
            for contest_id, records in contests
        ]
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "index.json").write_text(
            json.dumps(index_json, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._write_root_page(contests)

    def _write_root_page(self, contests: list[tuple[int, list[dict[str, Any]]]]) -> None:
        rows = []
        for contest_id, records in contests:
            rows.append(
                f'<li><a href="contest-{contest_id}/index.html">比赛 {contest_id}</a>'
                f"（{len(records)} 题）</li>"
            )
        body = "\n".join(rows) or "<li>暂无数据</li>"
        page = _HTML_TEMPLATE.format(
            title="XMUOJ AC 参考代码库",
            body=f"<h1>XMUOJ AC 参考代码库</h1>\n<ul>\n{body}\n</ul>",
        )
        (self.root / "index.html").write_text(page, encoding="utf-8")

    def _write_contest_page(
        self, contest_dir: Path, contest_id: int, records: list[dict[str, Any]]
    ) -> None:
        sections = []
        for r in records:
            pid = html.escape(str(r.get("problem_id") or ""))
            title = html.escape(str(r.get("title") or ""))
            score = html.escape(str(r.get("score") if r.get("score") is not None else ""))
            language = html.escape(str(r.get("language") or ""))
            code = html.escape(str(r.get("code") or ""))
            sections.append(
                f'<section id="{pid}">\n'
                f"<h2>{pid} {title}</h2>\n"
                f"<p>分数：{score} ｜ 语言：{language} ｜ "
                f'<a href="{pid}.json">JSON</a></p>\n'
                f"<pre><code>{code}</code></pre>\n"
                f"</section>"
            )
        body = (
            f'<p><a href="../index.html">← 返回总索引</a></p>\n'
            f"<h1>比赛 {contest_id} AC 参考代码</h1>\n" + "\n".join(sections)
        )
        page = _HTML_TEMPLATE.format(title=f"比赛 {contest_id} AC 参考代码", body=body)
        (contest_dir / "index.html").write_text(page, encoding="utf-8")


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ font-family: system-ui, "Segoe UI", sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }}
pre {{ background: #0d1117; color: #e6edf3; padding: 1rem; border-radius: 8px; overflow-x: auto; }}
code {{ font-family: ui-monospace, "Cascadia Code", Consolas, monospace; }}
section {{ border-top: 1px solid #ddd; padding-top: 1rem; }}
a {{ color: #0969da; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""
