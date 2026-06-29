# XMUOJ Pilot

XMUOJ 命令行练习助手：登录态管理、比赛/题目获取、AI 学习笔记、AI 自动做题（含 ReAct 修复）、已 AC 参考代码库，以及本地提交预览与判题轮询。

交互界面以方向键操作：`↑/↓` 选择、`←/→` 翻页、`Enter` 确认、`Esc` 取消。

## 功能

- **登录与会话**：管理 cookie / CSRF，保存会话，自动复用。
- **比赛与题目**：拉取比赛列表、比赛详情、题目列表与题面（支持比赛密码）。
- **学习任务**：批量拉题面并为每题调用 DeepSeek 生成学习笔记。
- **AI 自动做题（assist）**：生成 C++ 草稿 → 本地编译 → 跑样例（仅作参考，不阻止提交）→ 提交 → 判题轮询。
  - 第一遍简单生成；从第二遍起进入 **ReAct 修复循环**（思考→行动→观察：重读题面 / 写代码 / 质疑样例 / 完成），每题一个对话不重置上下文，最多 5 次提交。
  - 提交遇到限流（`Please wait N seconds`）会自动等待后重试，而非当作错误。
- **AC 参考代码库**：抓取本账号已满分(AC)题目的代码，按**内部 ID**扁平存储，生成可托管页面；做题时按内部 ID 先查本地、再查远程，命中则作为参考代码注入。
- **安全提交**：提交前展示比赛 ID、题号、语言、代码预览；半自动模式需人工确认。

## 安装与启动

```bash
uv sync
uv run xmuoj-pilot          # 进入交互主菜单
```

## 命令用法

```bash
# 登录 / 配置 AI
uv run xmuoj-pilot login
uv run xmuoj-pilot configure-ai

# 学习笔记
uv run xmuoj-pilot study --contest-id 361

# 自动做题：semi=每题人工确认提交；rehearsal=全自动演练到提交
uv run xmuoj-pilot assist --contest-id 361 --mode semi
uv run xmuoj-pilot assist --contest-id 361 --mode rehearsal

# 只对单题走自动做题流程（流程测试用）
uv run xmuoj-pilot assist-problem JD001 --contest-id 361 --mode semi

# 抓取本账号该比赛的 AC 代码到本地参考库并生成索引页
uv run xmuoj-pilot fetch-ac --contest-id 361

# 手动提交本地代码文件
uv run xmuoj-pilot submit 361 JD001 submissions/JD001.cpp --lang "C++"

# 逐项测试 XMUOJ API
uv run xmuoj-pilot test-api --contest-id 361 --problem-id JD001
```

主菜单包含：选择比赛、查看题目、学习任务、半自动做题、全自动演练、测试单题自动做题、登录/切换账号、配置 AI、调试 API、测试 API。

## 日志产物

`assist` 每题一个目录，保存全过程便于复查：

```text
logs/assist-contest-361/YYYYMMDD-HHMMSS/JD001/
  statement.md            # 题面
  solution.cpp            # 当前代码
  compile.log / samples.log
  ai-*.md                 # AI 各轮回复
  react-*.md              # ReAct 修复轨迹
  reference-ac.json       # 命中的参考 AC 代码（若有）
  submission-*.json       # 各次提交的判题结果
  task.log
```

## AC 参考代码库

抓取后按内部 ID 存为 `ac-library/<内部ID>.json`，并生成 `index.html` / `index.json`。做题时通过配置项 `ac_library_url`（默认 `https://vintcessun.github.io/xmuoj-pilot`）按内部 ID 拉取远程参考代码；本地 `ac-library/` 优先。

可用环境变量临时指定：

```powershell
$env:XMUOJ_PILOT_AC_LIBRARY_URL="https://vintcessun.github.io/xmuoj-pilot"
$env:XMUOJ_PILOT_AC_LIBRARY_DIR="ac-library"
```

## GitHub Actions

- **Fetch AC Library**（`fetch-ac-library.yml`）：手动触发，填 `contest_id`（账号/密码用 Secret `XMUOJ_USERNAME` / `XMUOJ_PASSWORD`）。登录→抓取 AC 代码→提交回仓库→上传 artifact→部署 GitHub Pages（即可拉取的页面）。
- **Build & Release**（`build-release.yml`）：手动触发，构建 manylinux / Windows / macOS 单文件可执行。`version` 留空则只产出 artifact；填了版本号（如 `v0.1.0`）则创建对应 GitHub Release 并上传产物。

## 本地构建

```bash
uv run python scripts/build.py            # 构建当前平台单文件，输出到 dist/
```

## 配置文件

配置目录：Windows `%APPDATA%/xmuoj-pilot/`；Linux/macOS `~/.config/xmuoj-pilot/`。

- `config.json`：base URL、debug、SSL 校验、当前比赛、比赛密码、AI Provider、`ac_library_url`。
- `session.json`：cookies、csrf token、登录时间。

默认关闭 SSL 校验以适配抓包代理；如需开启：

```powershell
$env:XMUOJ_PILOT_VERIFY_SSL="true"
```
