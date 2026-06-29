"""已 AC（满分）参考代码库。

按题目**内部 ID** 扁平存储，不按比赛分目录（同一题在不同比赛里内部 ID 相同，
可天然去重共享）。默认目录为当前工作目录下的 ``ac-library/``，可被 git 跟踪、拉取：

    ac-library/
        index.html          # 总索引页（可托管到 GitHub Pages）
        index.json          # 机器可读索引
        <internal_id>.json  # 单题记录（含 AC 代码）

记录字段：internal_id, display_id, title, language, score, submission_id,
contest_id, fetched_at, statement, code。

做题流程可通过 :meth:`ACLibrary.get_reference` 先查本地、再查远程（GitHub Pages
等静态托管）按内部 ID 拿到参考代码。
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def default_library_dir() -> Path:
    env = os.getenv("XMUOJ_PILOT_AC_LIBRARY_DIR")
    if env:
        return Path(env)
    return Path("ac-library")


class ACLibrary:
    def __init__(self, root: Path | None = None, *, remote_base_url: str | None = None) -> None:
        self.root = root or default_library_dir()
        # 远程基址，例如 https://<user>.github.io/<repo>
        self.remote_base_url = (remote_base_url or os.getenv("XMUOJ_PILOT_AC_LIBRARY_URL") or "").rstrip("/")

    # ---- 路径（按内部 ID）----
    def record_path(self, internal_id: int | str) -> Path:
        return self.root / f"{internal_id}.json"

    # ---- 读写单题记录 ----
    def save_record(
        self,
        internal_id: int | str,
        *,
        code: str,
        display_id: str = "",
        title: str = "",
        language: str = "",
        score: Any = None,
        submission_id: str = "",
        contest_id: int | None = None,
        statement: str = "",
    ) -> Path:
        record = {
            "internal_id": internal_id,
            "display_id": display_id,
            "title": title,
            "language": language,
            "score": score,
            "submission_id": submission_id,
            "contest_id": contest_id,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "statement": statement,
            "code": code,
        }
        path = self.record_path(internal_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_local(self, internal_id: int | str) -> dict[str, Any] | None:
        path = self.record_path(internal_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    async def fetch_remote(self, internal_id: int | str) -> dict[str, Any] | None:
        if not self.remote_base_url:
            return None
        import httpx

        url = f"{self.remote_base_url}/{internal_id}.json"
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

    async def get_reference(self, internal_id: int | str) -> dict[str, Any] | None:
        """先本地后远程地按内部 ID 获取参考记录；含非空 code 才算命中。"""
        record = self.load_local(internal_id)
        if record and record.get("code"):
            return record
        remote = await self.fetch_remote(internal_id)
        if remote and remote.get("code"):
            return remote
        return None

    # ---- 索引页 ----
    def build_index(self) -> None:
        if not self.root.exists():
            return
        records: list[dict[str, Any]] = []
        for record_path in sorted(self.root.glob("*.json")):
            if record_path.name == "index.json":
                continue
            try:
                data = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("code"):
                records.append(data)

        index_json = [
            {
                "internal_id": r.get("internal_id"),
                "display_id": r.get("display_id"),
                "title": r.get("title"),
                "score": r.get("score"),
                "language": r.get("language"),
                "contest_id": r.get("contest_id"),
                "path": f"{r.get('internal_id')}.json",
            }
            for r in records
        ]
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "index.json").write_text(
            json.dumps(index_json, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._write_index_page(records)

    def _write_index_page(self, records: list[dict[str, Any]]) -> None:
        rows = []
        for r in records:
            iid = html.escape(str(r.get("internal_id") or ""))
            did = html.escape(str(r.get("display_id") or ""))
            title = html.escape(str(r.get("title") or ""))
            score = html.escape(str(r.get("score") if r.get("score") is not None else ""))
            cid = html.escape(str(r.get("contest_id") if r.get("contest_id") is not None else ""))
            rows.append(
                f'<tr><td><a href="#p{iid}">{iid}</a></td><td>{did}</td>'
                f"<td>{title}</td><td>{score}</td><td>{cid}</td></tr>"
            )
        table = (
            "<table><thead><tr><th>内部 ID</th><th>显示题号</th><th>标题</th>"
            "<th>分数</th><th>来源比赛</th></tr></thead><tbody>\n"
            + ("\n".join(rows) or "<tr><td colspan=5>暂无数据</td></tr>")
            + "\n</tbody></table>"
        )
        sections = []
        for r in records:
            iid = html.escape(str(r.get("internal_id") or ""))
            did = html.escape(str(r.get("display_id") or ""))
            title = html.escape(str(r.get("title") or ""))
            score = html.escape(str(r.get("score") if r.get("score") is not None else ""))
            language = html.escape(str(r.get("language") or ""))
            code = html.escape(str(r.get("code") or ""))
            sections.append(
                f'<section id="p{iid}">\n'
                f"<h2>内部 ID {iid}（{did} {title}）</h2>\n"
                f"<p>分数：{score} ｜ 语言：{language} ｜ "
                f'<a href="{iid}.json">JSON</a></p>\n'
                f"<pre><code>{code}</code></pre>\n"
                f"</section>"
            )
        body = (
            "<h1>XMUOJ AC 参考代码库</h1>\n" + table + "\n" + "\n".join(sections)
        )
        page = _HTML_TEMPLATE.format(title="XMUOJ AC 参考代码库", body=body)
        (self.root / "index.html").write_text(page, encoding="utf-8")


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ font-family: system-ui, "Segoe UI", sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
th {{ background: #f6f8fa; }}
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
