---
description:
alwaysApply: true
---

# 快速上手指南

**生成日期**: 2026-05-27
**项目版本**: dev 分支

---

## 一、项目简介

**AzurPilot** 是碧蓝航线手游的自动化框架。通过 ADB/uiautomator2 控制安卓模拟器，截取屏幕截图，通过图像匹配和 OCR 识别 UI 元素，自动执行游戏任务。

### 核心特性

- 🎮 支持 CN/EN/JP/TW 四个游戏服务器
- 🔄 7×24h 连续运行设计
- 🖥️ WebUI 管理界面
- 🤖 MCP 服务器集成
- 📊 掉落统计与分析

---

## 二、核心概念与术语

### 2.1 基础术语

| 术语 | 说明 |
|------|------|
| **Button** | UI 元素，包含边界框、颜色、模板图像 |
| **Template** | 模板匹配对象，用于识别游戏内图像 |
| **OCR** | 光学字符识别，用于读取游戏内文字 |
| **状态循环** | 截图-检查-操作的循环模式 |
| **页面 (Page)** | 游戏内的一个界面状态 |

### 2.2 技术术语

| 术语 | 说明 |
|------|------|
| **ADB** | Android Debug Bridge，安卓调试桥 |
| **uiautomator2** | 安卓 UI 自动化框架 |
| **ONNX** | 开放神经网络交换格式，用于 OCR 模型 |
| **NCNN** | 高性能神经网络推理框架 |
| **MCP** | Model Context Protocol，AI 模型上下文协议 |

### 2.3 项目术语

| 术语 | 说明 |
|------|------|
| **ALAS** | AzurPilot 的旧称（AzurLaneAutoScript 的缩写） |
| **AzurPilot** | 项目名称 |
| **大世界** | 游戏内的 Operation Siren 模式 |
| **指挥喵** | 游戏内的 Meowfficer 系统 |

---

## 三、快速开始

### 3.1 环境准备

```bash
# 克隆项目
git clone <repository-url>
cd AzurLaneAutoScript

# 安装依赖
uv sync --frozen
```

### 3.2 启动应用

```bash
# 启动 WebUI（推荐）
uv run python gui.py

# 直接运行调度器
uv run python alas.py

# 启动 MCP 服务器
uv run python mcp_server_sse.py
```

### 3.3 配置文件

- 用户配置：`config/alas.json`
- 配置模板：`config/template.json`
- 配置定义：`module/config/argument/*.yaml`

---

## 四、模块索引

### 4.1 入口层

| 模块 | 说明 | 文档链接 |
|------|------|---------|
| alas.py | 核心调度器 | [ENTRY-ALAS.md](ENTRY-ALAS.md) |
| gui.py | WebUI 启动器 | [ENTRY-GUI.md](ENTRY-GUI.md) |
| mcp_server_sse.py | MCP 服务器 | [ENTRY-MCP-SERVER.md](ENTRY-MCP-SERVER.md) |

### 4.2 核心基础层

| 模块 | 说明 | 文档链接 |
|------|------|---------|
| module/base | 基础工具类 | [BASE.md](BASE.md) |
| module/config | 配置系统 | [CONFIG.md](CONFIG.md) |
| module/device | 设备连接层 | [DEVICE.md](DEVICE.md) |
| module/ui | UI 导航系统 | [UI.md](UI.md) |
| module/ocr | OCR 系统 | [OCR.md](OCR.md) |
| module/handler | 游戏处理器 | [HANDLER.md](HANDLER.md) |

### 4.3 战斗系统层

| 模块 | 说明 | 文档链接 |
|------|------|---------|
| module/combat | 战斗逻辑 | [COMBAT.md](COMBAT.md) |
| module/map | 地图处理 | [MAP.md](MAP.md) |
| module/campaign | 战役执行 | [CAMPAIGN.md](CAMPAIGN.md) |

### 4.4 游戏功能层

| 模块 | 说明 | 文档链接 |
|------|------|---------|
| module/research | 科研系统 | [GAME-FUNCTIONS.md](GAME-FUNCTIONS.md) |
| module/commission | 委托系统 | [GAME-FUNCTIONS.md](GAME-FUNCTIONS.md) |
| module/dorm | 宿舍管理 | [GAME-FUNCTIONS.md](GAME-FUNCTIONS.md) |
| ... | 其他功能模块 | [GAME-FUNCTIONS.md](GAME-FUNCTIONS.md) |

### 4.5 大世界层

| 模块 | 说明 | 文档链接 |
|------|------|---------|
| module/os | 大世界核心 | [OS-SYSTEM.md](OS-SYSTEM.md) |
| module/os_combat | 大世界战斗 | [OS-SYSTEM.md](OS-SYSTEM.md) |
| module/os_handler | 事件处理 | [OS-SYSTEM.md](OS-SYSTEM.md) |

### 4.6 基础设施层

| 模块 | 说明 | 文档链接 |
|------|------|---------|
| module/statistics | 掉落统计 | [INFRASTRUCTURE.md](INFRASTRUCTURE.md) |
| module/notify | 推送通知 | [INFRASTRUCTURE.md](INFRASTRUCTURE.md) |
| module/daemon | 守护模式 | [INFRASTRUCTURE.md](INFRASTRUCTURE.md) |
| module/webui | WebUI 应用 | [INFRASTRUCTURE.md](INFRASTRUCTURE.md) |

---

## 五、推荐的代码阅读顺序

### 5.1 入门级（了解整体架构）

1. `alas.py` — 理解任务调度流程
2. `module/base/base.py` — 理解 ModuleBase 基类
3. `module/config/config.py` — 理解配置系统
4. `module/device/device.py` — 理解设备交互

### 5.2 进阶级（理解核心机制）

1. `module/ui/ui.py` — 理解 UI 导航
2. `module/ocr/ocr.py` — 理解 OCR 识别
3. `module/base/button.py` — 理解 Button/Template
4. `module/handler/info_handler.py` — 理解弹窗处理

### 5.3 高级级（深入游戏逻辑）

1. `module/combat/combat.py` — 理解战斗系统
2. `module/map/map.py` — 理解地图处理
3. `module/campaign/campaign_base.py` — 理解战役执行
4. `module/research/research.py` — 理解具体功能实现

---

## 六、常用开发任务

### 6.1 添加新功能

1. 在 `module/` 下创建新的模块目录
2. 创建包含 `run()` 方法的处理器类
3. 在 `alas.py` 中添加对应的任务方法
4. 在 `config/template.json` 中添加配置项
5. 运行 `uv run -m module.config.config_updater`
6. 在 `assets/` 中添加 UI 模板图像

### 6.2 添加新活动

1. 在 `campaign/` 下创建新目录
2. 在新目录中添加地图 YAML 文件
3. 更新 `campaign/Readme.md`
4. 运行 `uv run -m module.config.config_updater`
5. 在 `assets/cn/event/` 中添加模板图像

### 6.3 调试按钮

```python
az = SomeModule('alas', task='SomeTask')
az.image_file = r'path/to/screenshot.png'
print(az.appear(SOME_BUTTON))
```

---

## 七、常用命令速查

```bash
# 环境搭建
uv sync --frozen

# 运行应用
uv run python gui.py                    # 启动 WebUI
uv run python alas.py                   # 直接运行调度器
uv run python mcp_server_sse.py         # 启动 MCP 服务器

# 代码检查
uv run ruff check . --select E9,F63,F7,F82 --ignore F821,F722

# 配置生成
uv run -m module.config.config_updater

# 资源管理
uv run -m dev_tools.button_extract

# 开发工具
uv run dev_tools/map_extractor.py       # 地图数据提取
uv run dev_tools/emulator_test.py       # 模拟器连接测试
```

---

## 八、文档索引

| 文档 | 说明 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 项目整体架构 |
| [CONVENTIONS.md](CONVENTIONS.md) | 编码规范 |
| [ISSUES.md](ISSUES.md) | 问题清单 |
| [MODULE-MAP.md](MODULE-MAP.md) | 模块映射表 |
| [BASE.md](BASE.md) | 基础工具类分析 |
| [CONFIG.md](CONFIG.md) | 配置系统分析 |
| [DEVICE.md](DEVICE.md) | 设备层分析 |
| [UI.md](UI.md) | UI 导航分析 |
| [OCR.md](OCR.md) | OCR 系统分析 |
| [HANDLER.md](HANDLER.md) | 处理器层分析 |
| [COMBAT.md](COMBAT.md) | 战斗系统分析 |
| [MAP.md](MAP.md) | 地图处理分析 |
| [CAMPAIGN.md](CAMPAIGN.md) | 战役执行分析 |
| [GAME-FUNCTIONS.md](GAME-FUNCTIONS.md) | 游戏功能模块分析 |
| [OS-SYSTEM.md](OS-SYSTEM.md) | 大世界系统分析 |
| [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | 基础设施层分析 |
