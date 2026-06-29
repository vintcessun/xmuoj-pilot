# XMUOJ Pilot

XMUOJ Pilot 是一个面向本人账号、本人授权练习场景的 XMUOJ CLI 工具。它提供登录状态管理、Cookie/CSRF 维护、比赛和题目获取、DeepSeek / OpenAI-compatible 配置、题面日志、AI 学习笔记、本地代码提交预览和判题结果轮询。

项目的交互入口以键盘方向键为主：主菜单、比赛选择、题目选择都使用 `↑/↓` 选择、`←/→` 翻页、`Enter` 确认、`Esc` 取消，不需要输入菜单数字。

## 安装与启动

```bash
uv sync
uv run xmuoj-pilot
```

常用命令：

```bash
uv run xmuoj-pilot login
uv run xmuoj-pilot configure-ai
uv run xmuoj-pilot study --contest-id 361
uv run xmuoj-pilot assist --contest-id 361 --mode semi
uv run xmuoj-pilot assist --contest-id 361 --mode rehearsal
uv run xmuoj-pilot submit 361 JD001 submissions/JD001.cpp --lang "C++"
uv run xmuoj-pilot test-api --contest-id 361 --problem-id JD001
```

## 主菜单

主菜单会显示当前选中的比赛，例如：

```text
主菜单 | 当前比赛：361 2026年校外实训一之剑道试炼
```

菜单项：

- 选择比赛：拉取比赛列表，方向键选择比赛，并进入题目列表。
- 查看当前比赛题目：展示当前比赛题目，方向键选择题目查看详情。
- 开始学习任务：批量拉取题面，为每道题保存日志，并调用 DeepSeek 生成学习笔记。
- 开始半自动做题：拉题面、调用 DeepSeek 生成 C++ 草稿、检测 `g++/gcc`、编译、运行样例、提交前人工确认。
- 全自动演练到待提交：自动完成题面获取、AI 草稿、本地编译、样例运行和日志保存，但不真实提交。
- 登录 / 切换账号
- 配置 AI Provider
- 调试 API 请求
- 测试 XMUOJ API

## 学习任务

学习任务会为每道题创建独立日志目录：

```text
logs/contest-361/YYYYMMDD-HHMMSS/JD001/
  statement.md
  deepseek-note.md
```

每道题使用独立 DeepSeek 请求，输入包含完整题面信息。当前实现用于生成题意、思路、边界情况和实现提示。

## 做题辅助流水线

`assist` 命令提供两个模式：

```bash
uv run xmuoj-pilot assist --contest-id 361 --mode semi
uv run xmuoj-pilot assist --contest-id 361 --mode rehearsal
```

半自动模式 `semi`：

- 每道题一个独立 DeepSeek 会话。
- 保存题面、AI 回复、代码草稿、编译日志、样例日志。
- 如果本机存在 `g++` 或 `gcc`，会尝试编译生成的 `solution.cpp`。
- 如果题面返回样例，会运行样例并记录结果。
- 到真实提交前暂停，展示代码预览。
- 用户确认后才提交；用户拒绝时可以输入理由，理由会反馈给 DeepSeek 继续修改。

演练模式 `rehearsal`：

- 自动执行题面获取、DeepSeek 草稿、本地编译、样例运行、日志保存和提交。

DeepSeek 输出不设置本地 token 上限，使用所选模型和服务端默认限制。

## 提交模式说明

当前支持安全提交模式：

- 提交前展示比赛 ID、显示题号、内部题号、语言、代码文件路径和代码预览。
- 如果用户拒绝提交，可以输入理由并让 AI 修改，或修改本地代码后再次运行提交。
- 提交后会轮询 `/api/submission?id=...` 并展示判题结果。

项目保留人工确认边界，避免误提交和批量替代学习。

## 本地配置

配置目录：

- Windows: `%APPDATA%/xmuoj-pilot/`
- Linux/macOS: `~/.config/xmuoj-pilot/`

文件：

- `config.json`: base URL、debug 开关、SSL 校验开关、当前比赛、比赛密码、AI Provider 配置
- `session.json`: cookies、csrf token、last_login_at

密码输入会显示 `*`。比赛密码在 CLI 输入后会保存，用于后续访问同一比赛。

项目默认关闭 SSL 证书校验，以适配本机 HTTPS 代理/抓包代理环境。如果你不使用代理并希望开启校验，可以设置：

```powershell
$env:XMUOJ_PILOT_VERIFY_SSL="true"
```

## API 测试

```bash
uv run xmuoj-pilot test-api --contest-id 361 --problem-id JD001
```

从环境变量登录并测试：

```powershell
$env:XMUOJ_PILOT_USERNAME="你的账号"
$env:XMUOJ_PILOT_PASSWORD="你的密码"
$env:XMUOJ_PILOT_CONTEST_ID="361"
$env:XMUOJ_PILOT_PROBLEM_ID="JD001"
uv run python scripts/api_smoke_from_env.py
```

## Windows 打包

```bash
uv add nuitka
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
```
