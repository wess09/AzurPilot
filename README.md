
# AzurPilot — 碧蓝航线自动化辅助工具

> 【TEST/测试】本行为验证 ci-report 自动评论功能的测试标注，验证后将被移除，无任何功能影响。

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/简体中文-中文-blue?style=flat-square" alt="简体中文"></a>
  <a href="README.zh-TW.md"><img src="https://img.shields.io/badge/繁體中文-繁體-green?style=flat-square" alt="繁體中文"></a>
  <a href="README.en.md"><img src="https://img.shields.io/badge/English-English-red?style=flat-square" alt="English"></a>
  <a href="README.ja.md"><img src="https://img.shields.io/badge/日本語-日本語-orange?style=flat-square" alt="日本語"></a>
  <a href="README.ko.md"><img src="https://img.shields.io/badge/한국어-한국어-violet?style=flat-square" alt="한국어"></a>
</p>

<p align="center">
  <img src="doc/logo.webp" alt="AzurPilot Logo" width="400">
</p>

<p align="center">
  <strong><a href="https://alas.nanoda.work/">AzurPilot 官网</a></strong> ｜ 碧蓝航线自动化脚本 · 大世界侵蚀循环 · 多平台支持
</p>

<p align="center">
  <a href="https://deepwiki.com/wess09/AzurPilot">
    <img src="https://deepwiki.com/badge.svg" alt="DeepWiki" height="22">
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/github/license/wess09/AzurPilot?style=flat-square&label=License&color=2ea44f" alt="License">
  <img src="https://img.shields.io/github/stars/wess09/AzurPilot?style=flat-square&label=Stars&color=ffcc00" alt="Stars">
  <img src="https://img.shields.io/github/forks/wess09/AzurPilot?style=flat-square&label=Forks&color=58a6ff" alt="Forks">
  <img src="https://img.shields.io/github/issues/wess09/AzurPilot?style=flat-square&label=Issues&color=f85149" alt="Issues">
</p>

<p align="center">
  <img src="https://img.shields.io/github/last-commit/wess09/AzurPilot?style=flat-square&label=Last%20Commit&color=8b949e" alt="Last Commit">
  <img src="https://img.shields.io/github/commit-activity/m/wess09/AzurPilot?style=flat-square&label=Commit%20Activity&color=8957e5" alt="Commit Activity">
  <img src="https://img.shields.io/github/repo-size/wess09/AzurPilot?style=flat-square&label=Repo%20Size&color=orange" alt="Repo Size">
  <img src="https://img.shields.io/github/languages/top/wess09/AzurPilot?style=flat-square&label=Top%20Language&color=3776AB" alt="Top Language">
</p>

<p align="center">
  <img src="https://img.shields.io/github/contributors/wess09/AzurPilot?style=flat-square&label=Contributors&color=00b4d8" alt="Contributors">
  <img src="https://img.shields.io/github/issues-pr/wess09/AzurPilot?style=flat-square&label=Pull%20Requests&color=ffb703" alt="Pull Requests">
  <img src="https://img.shields.io/github/issues-pr-closed/wess09/AzurPilot?style=flat-square&label=PRs%20Closed&color=2ea44f" alt="Closed Pull Requests">
</p>

<div align="center">
  <a href="https://alas.nanoda.work/">
    <img src="https://img.shields.io/badge/Web-下载-blue?style=for-the-badge&logo=google-chrome&logoColor=white" />
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://join.nanoda.work/#/">
    <img src="https://img.shields.io/badge/交流群-QQ-red?style=for-the-badge&logo=tencent-qq&logoColor=white" />
  </a>
</div>

## 项目简介

AzurPilot 是基于 AzurLaneAutoScript 修改而来的碧蓝航线自动化辅助工具，保留原项目的核心能力，并在此基础上整合了多个分支、功能改进和实验性特性。通过 ADB/uiautomator2 控制安卓模拟器，以截图识别、图像匹配与 OCR 自动执行游戏任务，支持 CN/EN/JP/TW 四服。

> **请注意**：本项目代码基本由 AI 代码生成与辅助编写，存在较大的不确定性，欢迎提交 [Pull Request](https://github.com/wess09/AzurPilot/pulls) 改正。

访问 **[AzurPilot 官网](https://alas.nanoda.work/)** 了解更多功能详情，或前往 **[下载页面](https://alas.nanoda.work/download.html)** 获取最新版本。

## GUI 预览

<div align="center">
  <img src="doc/GUI.png" alt="GUI Preview" width="800">
</div>

## 快速开始

> 💡 **推荐方式**：直接从 [AzurPilot 官网下载页](https://alas.nanoda.work/download.html) 下载对应平台的启动器，内置 Python 环境，开箱即用。

### Linux 一键部署

```shell
curl -fsSL https://alas.nanoda.work/install/deploy-image.sh | sudo -E bash
```

### 源码运行

本项目使用 `uv` 和项目根目录 `.venv` 管理 Python 运行环境（要求 Python >= 3.14）。发布版启动器会自带 uv、Python、ADB、Git，并在 `.venv` 中同步依赖；源码开发时可安装 uv 后运行：

```bash
uv sync --frozen --no-dev
uv run python gui.py
```

启动后浏览器访问 `http://127.0.0.1:25548` 进入 WebUI。

## 重要说明

- 本项目包含大量自动化逻辑和图像识别相关功能。使用前请确保已完成[游戏内设置](#使用前设置)，否则可能导致识别失败、流程异常或任务无法正常执行。
- 本项目包含部分实验性功能，可能存在未知问题。建议在使用前备份相关配置，并在发现异常时及时反馈。

## 使用前设置

使用前必须按照以下标准修改游戏内设置。

路径：主界面 → 右下角设置 → 左侧边栏选项。

| 设置名称 | 推荐值 |
| --- | --- |
| 帧数设置 | 60 帧 |
| 大型作战设置，减少 TB 引导 | 开 |
| 大型作战设置，自律时自动提交道具 | 开 |
| 大型作战设置，安全海域默认开启自律 | 关 |
| 剧情自动播放 | 开启 |
| 剧情自动播放速度调整 | 特快 |
| 待机模式设置，启用待机模式 | 关 |
| 其他设置，重复角色获得提示 | 关 |
| 其他设置，快速更换二次确认界面 | 关 |
| 其他设置，展示结算角色 | 关 |

### 大型作战设置

路径：大型作战 → 右上角雷达 → 指令模块 → 潜艇支援。

| 设置名称 | 推荐值 |
| --- | --- |
| X 消耗时潜艇出击 | 取消勾选 |

### 一键退役设置

路径：主界面 → 右下角建造 → 左侧边栏退役 → 左侧齿轮图标 → 一键退役设置。

| 设置名称 | 推荐值 |
| --- | --- |
| 选择优先级 1 | R |
| 选择优先级 2 | SR |
| 选择优先级 3 | N |
| 拥有满星的同名舰船时，保留几艘符合退役条件的同名舰船 | 不保留 |
| 没有满星的同名舰船时，保留几艘符合退役条件的同名舰船 | 满星所需或不保留 |

### 图像识别注意事项

请移除以下可能影响识别的内容：

- 角色设备装备
- 角色皮肤
- 可能遮挡界面元素的自定义显示内容

这些内容可能影响图像识别结果，导致自动化流程出现异常。

## MCP 服务

AzurPilot 提供 MCP 服务，可供支持 MCP 的客户端或工具调用，方便使用 Agent 管理 AzurPilot。

> MCP 服务默认随 WebUI 启动并挂载于 `/mcp` 路径下（WebUI 默认端口 25548），也可通过 `uv run python mcp_server_sse.py` 独立运行（独立端口 22268）。

### 本地连接配置

```json
{
  "mcpServers": {
    "alas": {
      "url": "http://127.0.0.1:25548/mcp/sse"
    }
  }
}
```

### 云服务器或内网连接配置

```json
{
  "mcpServers": {
    "alas": {
      "url": "http://[IP_ADDRESS]:25548/mcp/sse"
    }
  }
}
```

请将 `[IP_ADDRESS]` 替换为实际服务器地址或内网地址；若 WebUI 端口被修改，请同步替换 URL 中的端口。

### MCP 工具列表

当前可用 MCP 工具共 18 个。

| 类别 | 工具名称 | 功能 |
| --- | --- | --- |
| 实例管理 | `list_instances` | 列出所有实例 |
| | `get_status` | 获取实例状态 |
| | `start_instance` | 启动实例 |
| | `stop_instance` | 停止实例 |
| 任务管理 | `list_tasks` | 列出所有任务 |
| | `get_task_help` | 获取任务帮助 |
| | `trigger_task` | 触发任务 |
| | `get_scheduler_queue` | 获取调度队列 |
| | `clear_scheduler_queue` | 清空调度队列 |
| 监控与信息 | `get_current_running_task` | 获取当前运行任务 |
| | `get_resources` | 获取资源状态 |
| | `get_config` | 获取实例配置 |
| | `get_recent_logs` | 获取最近日志 |
| | `get_screenshot` | 获取截图 |
| 配置管理 | `update_config` | 更新配置 |
| 维护工具 | `restart_emulator` | 重启模拟器 |
| | `restart_adb` | 重启 ADB |
| | `update_alas` | 更新 AzurPilot |

## 多平台启动器

> 📥 从 [AzurPilot 官网](https://alas.nanoda.work/download.html) 下载 Windows / macOS / Linux 启动器

<div align="center">
  <img src="doc/loading.png" alt="loading" width="500" />
  <p>启动加载界面</p>
  <img src="doc/GUI.png" alt="GUI" width="500" />
  <p>Windows 客户端界面</p>
  <img src="doc/macGUI.png" alt="macGUI" width="500" />
  <p>Mac 客户端界面</p>
</div>

启动器项目地：[GitHub](https://github.com/wess09/alas-launcher) · 源项目 [ALAS Launcher: 一种新型的 AzurLaneAutoScript 启动器](https://github.com/swordfeng/alas-launcher)

更改内容：

1. 增加托盘化功能
2. Windows 原生推送
3. GUI 样式美化
4. uv 化
...

## 贡献者

由于本项目基于 AzurLaneAutoScript 及其社区分支继续开发，贡献者列表不仅包含本仓库的直接贡献者，也包含上游项目与相关分支中的原始贡献者。

*本项目的贡献名单

<a href="https://github.com/wess09/AzurPilot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/AzurPilot&max=1000" alt="AzurPilot Contributors">
</a>

*启动器项目的贡献名单

<a href="https://github.com/wess09/alas-launcher/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/alas-launcher&max=1000" alt="Launcher Contributors">
</a>

*ALAS原项目的功能名单

<a href="https://github.com/LmeSzinc/AzurLaneAutoScript/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=LmeSzinc/AzurLaneAutoScript&max=1000" alt="AzurLaneAutoScript Contributors">
</a>

## 相关链接

- [AzurPilot 官网](https://alas.nanoda.work/) — 项目介绍、功能详情、碧蓝航线自动化方案
- [AzurPilot 下载页](https://alas.nanoda.work/download.html) — 下载 Windows / macOS / Linux 版本的碧蓝航线脚本工具
- [GitHub 仓库](https://github.com/wess09/AzurPilot) — 源码、Issue、Pull Request
- [QQ 交流群](https://join.nanoda.work/#/) — 碧蓝航线自动化社区交流
- [AzurLaneAutoScript 上游项目](https://github.com/LmeSzinc/AzurLaneAutoScript) — ALAS 原版
- [AzurPilot 树莓派版](https://github.com/nnieie/AzurPilot) — 面向树莓派 / Termux 真机的 AzurPilot CN 部署版

## 开发与贡献

本项目基本完全是 VibeCoding 产物，不足之处请见谅。欢迎通过 Issue 或 Pull Request 反馈问题、提交修复或改进文档。

### 开发环境

```bash
uv sync --frozen        # 创建/同步 .venv（含开发依赖）

# 代码检查（CI 使用 ruff 宽松设置——仅检查致命语法错误和未定义名称）
uv run ruff check . --select E9,F63,F7,F82 --ignore F821,F722

# 测试（约 160 个单元测试）
uv run python -m unittest discover -s tests

# 配置生成（修改配置 YAML 文件后必须执行）
uv run -m module.config.config_updater
```

### 使用过的开发工具与模型

本项目开发过程中使用过多种 AI 模型与开发工具进行辅助。

**AI 模型：**

| | | |
| --- | --- | --- |
| Gemini | GPT | Claude |
| GLM | MiMo | DeepSeek |
| Kimi | Qwen | DouBao |

**开发工具：**

| | | |
| --- | --- | --- |
| Claude Code | Codex | Cursor | Antigravity |
| TRAE | ZCode | OpenCode | MiMoCode |


## 许可证

本项目遵循原项目及相关上游项目的许可证要求。启动器项目遵循 GPL-3.0 协议开源。

本项目依赖的相关项目许可证位于 /licenses

使用、修改或分发本项目时，请同时遵守相关上游项目的许可证要求。

## 赞助支持

<p align="center">
  <a href="https://afdian.com/a/miaonaa">
    <img src="doc/afdian.jfif" alt="爱发电" width="200">
  </a>
  <br>
  <b>支持本项目（用于支付服务器费用或训练新模型等？）</b>
</p>