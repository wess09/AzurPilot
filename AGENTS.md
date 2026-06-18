---
description:
alwaysApply: true
---

# AGENTS.md

> **重要：必须使用中文交流。** 所有回复、注释、文档、提交信息均使用简体中文。代码中的变量名、函数名使用英文。

本文件为 AI Agent 在本仓库中工作时提供指导。与 `CLAUDE.md` 互为补充——CLAUDE.md 偏完整参考，本文件偏实操要点。

---

## 项目概述

**AzurPilot** 是碧蓝航线手游的自动化框架。通过 ADB/uiautomator2 控制安卓模拟器，截取屏幕截图，通过图像匹配和 OCR 识别 UI 元素，自动执行游戏任务。支持 CN/EN/JP/TW 服务器。采用 GPL-3.0 许可证。

**设计约束**：7×24h 连续运行。固定 1280×720 分辨率。不支持真机。

---

## 开发环境

- **Python >=3.14,<3.15**
- **uv** 包管理器（项目模式，`package = false`）
- **依赖安装**：`uv sync --frozen`
- **运行时环境**：项目本地 `.venv/`
- **不维护 `requirements*.txt`**——依赖在 `pyproject.toml` 中声明，锁文件 `uv.lock` 提交到 git

## 基本命令

```bash
uv sync --frozen                                 # 安装依赖
uv run python gui.py                             # 启动 WebUI（端口 22267）
uv run python alas.py                            # 直接运行调度器
uv run python mcp_server_sse.py                  # 启动 MCP SSE 服务器（端口 22268）
uv run ruff check . --select E9,F63,F7,F82 --ignore F821,F722  # CI lint
uv run -m module.config.config_updater           # 配置生成（修改 YAML 后必须运行）
uv run -m dev_tools.button_extract               # 从截图提取按钮定义
```

---

## 入口点

| 文件 | 用途 |
|---|---|
| `alas.py` | 核心调度器——`AzurLaneAutoScript.loop()` 运行无限调度循环，55 个任务方法 |
| `gui.py` | WebUI 后端——PyWebIO + Starlette + uvicorn，每个配置实例在独立子进程中运行 |
| `mcp_server_sse.py` | MCP SSE 服务器——通过 SSE 暴露 18 个工具供外部 AI Agent 集成 |

---

## 配置系统（关键陷阱）

### 源文件（手动编辑）

| 文件 | 用途 |
|---|---|
| `module/config/argument/task.yaml` | 任务→选项组映射、菜单结构 |
| `module/config/argument/argument.yaml` | 参数定义（类型、选项、默认值） |
| `module/config/argument/override.yaml` | 不可修改的覆盖值（`display: hide`） |
| `module/config/argument/default.yaml` | 可修改的任务特定默认值 |
| `module/config/argument/gui.yaml` | GUI 界面翻译键 |
| `module/config/argument/dashboard.yaml` | 仪表盘资源列表 |

### 生成产物（不要手动编辑）

- `module/config/argument/args.json` — 合并后的完整参数定义
- `module/config/argument/menu.json` — 菜单定义
- `module/config/config_generated.py` — Python 配置类（IDE 自动补全用）
- `module/config/i18n/{zh-CN,zh-MIAO,en-US,ja-JP,zh-TW}.json` — 五种语言翻译文件
- `config/template.json` — 配置模板

### 正确操作流程

```
1. 编辑 YAML 源文件（argument.yaml / task.yaml / default.yaml / override.yaml / gui.yaml）

2. 运行生成器：
   uv run -m module.config.config_updater

3. 生成器自动完成：
   task.yaml + argument.yaml + override.yaml + default.yaml
     → args.json（合并参数定义）
     → menu.json（菜单结构）
     → config_generated.py（Python 类）
     → i18n/*.json（翻译文件，新增 key 的值默认等于 key 路径本身）
     → template.json（配置模板）

4. 【必须手动】翻译新增的 i18n 条目：
   打开 i18n/<lang>.json，找到值为 "Group.Argument.name" 这样的 key 路径字符串，
   逐行替换为正确的翻译文本。
   已有翻译会被保留（生成器从旧文件读取），只有新增 key 需要翻译。

5. zh-TW 会自动简繁转换，但仍需人工校对。
```

**CI 会检查** `button_extract.py` 和 `config_updater.py` 是否有未提交的 diff——如果有则 CI 失败。

**配置访问路径**：`self.config.Group_Argument`（下划线分隔），对应 GUI 中的 `<Task>.<Group>.<Argument>`。

### i18n 翻译生成机制

生成器对每种语言执行 `generate_i18n(lang)`：
- 从旧翻译文件读取已有翻译（保留）
- 新增 key 的默认值 = key 路径本身（如 `"Campaign.Event.name"`），需人工翻译
- 活动名称优先使用同语言服务器名称，回退顺序 `en → cn → jp → tw`
- 五种语言：`zh-CN`、`zh-MIAO`、`en-US`、`ja-JP`、`zh-TW`

### 配置加载流程（运行时）

```
AzurLaneConfig("alas")
  → init_task(task) → load()
    → read_file("./config/alas.json")       # 用户 JSON
    → config_update(old)                     # 与 args.json 默认值合并
    → config_redirect(old, new)              # 版本迁移
    → _override(new)                         # 云手机覆盖
  → config_override()                        # 强制覆盖，重置过期 NextRun
  → bind(task)                               # 映射属性名到配置路径
  → save()                                   # 写回磁盘
```

---

## 核心设计规则

### 状态循环模式（强制）

所有游戏交互必须使用持续的截图-检查循环。**绝不**使用点击-等待-休眠模式：

```python
def some_function(self, skip_first_screenshot=True):
    while 1:
        if skip_first_screenshot:
            skip_first_screenshot = False
        else:
            self.device.screenshot()

        # 退出条件——用 appear()，不设 interval
        if self.appear(END_CONDITION):
            break

        # 点击——用 interval 防连击（2-5 秒）
        if self.appear_then_click(BUTTON_A, interval=2):
            continue
        if self.appear_then_click(BUTTON_B, interval=3):
            continue
```

### 绝对禁止的模式

- ❌ `click(X); sleep(2)` — 禁止"点击-等待"模式
- ❌ `sleep()` 出现在状态循环内
- ❌ 使用负面条件做循环控制（`if not self.appear(...)`）
- ❌ 用 `appear_then_click()` 做循环退出条件——用 `appear()` 退出
- ❌ 嵌套状态循环——展平到父循环
- ❌ 给退出条件设置 `interval`
- ❌ `handle_*()` 返回非 bool 值（`True` = 已操作需新截图，`False` = 未操作）

### 死循环检测

- `GameStuckError`：无操作截图超过 1 分钟（战斗/启动中为 5 分钟）
- `GameTooManyClickError`：最近 15 次操作中单按钮点击 ≥12 次，或两个按钮各 ≥6 次

---

## 异常层次 (`module/exception.py`)

| 类别 | 异常 |
|---|---|
| **正常战役结束** | `CampaignEnd`、`OilExhausted`、`OilMaxed` |
| **地图导航错误** | `MapDetectionError`、`MapWalkError`、`MapEnemyMoved`、`CampaignNameError` |
| **游戏状态错误（触发重启）** | `GameStuckError`、`GameBugError`、`GameTooManyClickError` |
| **连接/页面错误** | `GameNotRunningError`、`GamePageUnknownError`、`EmulatorNotRunningError` |
| **开发者错误** | `ScriptError`、`ScriptEnd` |
| **不可恢复** | `RequestHumanTakeover`、`AutoSearchSetError` |

异常只在顶层捕获，捕获后日志和截图保存到独立目录，用户信息会被清洗。

---

## 架构概览

### 类层次结构

```
ModuleBase ← AzurLaneConfig + Device
  ├── UI ← InfoHandler（页面导航）
  ├── Combat ← Level + HPBalancer + Retirement + SubmarineCall + CombatAuto + CombatManual
  ├── CampaignBase ← CampaignUI + Map + AutoSearchCombat
  └── LoginHandler ← UI（应用重启/登录流程）

AzurLaneAutoScript (alas.py) ← AzurLaneConfig + Device + ServerChecker
  └── 通过惰性导入分发到任务模块

Device ← Screenshot + Control + AppControl + Input
  └── Connection ← ConnectionAttr
      └── Adb, WSA, Uiautomator2, AScreenCap, MaaTouch, Minitouch, ScrcpyCore, Platform
```

### 任务调度

优先级：`Restart > OpsiCrossMonth > Commission > Tactical > Research > Exercise > Dorm > Meowfficer > Guild > Gacha > Reward > ShopFrequent > ... > Main > Main2 > Main3 > GemsFarming`

- 同一任务连续失败 3 次触发 `RequestHumanTakeover`
- 任务间通过 `ConfigWatcher` 热重载配置
- `RESTART_SENSITIVE_TASKS = ['Commission', 'Research']` 触发严格重启行为
- 返回值：`True`（成功）、`False`（不可恢复）、`'recoverable'`（可自动恢复，不计入失败次数）
- 空闲时：`Optimization_WhenTaskQueueEmpty` → `close_game` / `goto_main` / `stay_there`

---

## 模块层结构 (`module/`)

### 基础层 (`module/base/`)

| 类 | 文件 | 说明 |
|---|---|---|
| `ModuleBase` | `base.py` | 所有游戏逻辑的根类。组合 `AzurLaneConfig` + `Device`。拥有 `worker` (AsyncExecutor) |
| `Button` | `button.py` | UI 元素（边界框、颜色、点击区域、模板图像）。继承 `Resource` |
| `Template` | `template.py` | 模板匹配。支持 GIF。必须以 `TEMPLATE_` 前缀命名 |
| `Resource` | `resource.py` | 跟踪 Button/Template 实例，支持 `resource_release()` 缓存释放 |
| `Switch` | `switch.py` | 状态切换（如 normal/hard 模式） |
| `Scroll` | `scroll.py` | 游戏滚动条处理 |
| `Navbar` | `navbar.py` | 页面内标签导航 |
| `Filter` | `filter.py` | 基于正则的过滤系统，支持预设和 `>` 分隔的优先级排序 |
| `Timer` | `timer.py` | 双重计时器（时间计数 + 访问计数） |
| `AsyncExecutor` | `async_executor.py` | 单例异步执行器，后台线程用于非阻塞操作 |
| `ApiClient` | `api_client.py` | HTTP 客户端，双域名故障转移 |
| `DeviceId` | `device_id.py` | 硬件指纹（WMIC） |

### 设备层 (`module/device/`)

- `Device` — 多重继承：`Screenshot + Control + AppControl + Input`
- `Connection` — ADB 连接层
- `ConnectionAttr` — 设备系列检测缓存（`is_mumu_family`、`is_ldplayer_bluestacks_family` 等）
- **截图后端**：`ADB`、`ADB_nc`、`uiautomator2`、`aScreenCap`、`aScreenCap_nc`、`DroidCast`、`DroidCast_raw`、`scrcpy`、`nemu_ipc`、`ldopengl`
- **控制后端**：`ADB`、`uiautomator2`、`minitouch`、`Hermit`、`MaaTouch`、`nemu_ipc`
- **模拟器平台**：夜神、蓝叠、雷电、MuMu、MEmu、BlueStacksAir、MuMuPro、SSH

### 配置系统 (`module/config/`)

- `AzurLaneConfig` 继承 `ConfigUpdater + ManualConfig + GeneratedConfig + ConfigWatcher`
- `server.py` — 全局服务器选择器：`server = 'cn'`，有效值 `['cn', 'en', 'jp', 'tw']`
- `deep.py` — 高性能嵌套字典访问
- `mcp_helper.py` — AI/MCP 集成的 `McpConfigHelper`

### UI 导航 (`module/ui/`)

- `Page` — 基于图的导航，A* 寻路
- `UI` — `ui_goto()`、`ui_ensure()`、`ui_back()`

### OCR 系统 (`module/ocr/`)

- `AlOcr` — RapidOCR 后端，支持 ONNX/NCNN，GPU 加速（DirectML/CoreML）
- `NcnnRecOCR` — NCNN 推理，模型：en/cn/jp/tw
- OCR 类：`Ocr`（通用）、`Digit`（int）、`DigitCounter`（14/15）、`Duration`（08:00:00）、YUV 变体
- 模型：`azur_lane`（EN）、`cnocr`（中+英）、`jp`（日文）、`tw`（繁体中文）
- 后端：`onnx`（默认）、`ncnn`（更快）；设备：`cpu`、`gpu`、`ane`

### 战斗系统 (`module/combat/`)

- `Combat` — 主战斗处理器，继承 `Level + HPBalancer + Retirement + SubmarineCall + CombatAuto + CombatManual`
- `AutoSearchCombat`、`CombatAuto`、`CombatManual`、`Emotion`、`HPBalancer`、`Level`、`SubmarineCall`

### 地图系统 (`module/map/`)

- `Map` — 继承 `MapOperation + MapCamera + MapFleet`
- `MapBase`、`MapCamera`、`MapFleet`、`MapGrids`、`MapOperation`

### 地图检测 (`module/map_detection/`)

- `Detector`、`Grid`、`GridPredictor`、`Homography`、`Perspective`

### 处理器层 (`module/handler/`)

- `InfoHandler` — 弹窗/对话框检测和关闭
- `LoginHandler` — 应用重启/登录流程
- `AutoSearchHandler`、`EnemySearchingHandler`、`FastForwardHandler`、`AmbushHandler`、`MysteryHandler`、`StrategyHandler`、`SensitiveInfoHandler`

### 其他游戏模块

每个模块有自己的 `assets.py` 定义 Button/Template 对象，任务模块包含 `run()` 方法。

| 模块 | 说明 |
|---|---|
| `campaign/` | 战役执行（`CampaignBase`、`CampaignEvent`、`GemsFarming`） |
| `research/` | 科研系统 |
| `commission/` | 委托系统 |
| `tactical/` | 战术学院 |
| `dorm/` | 宿舍管理 |
| `meowfficer/` | 指挥喵 |
| `guild/` | 大舰队 |
| `shop/` / `shop_event/` | 商店 / 活动商店 |
| `reward/` | 奖励收取 |
| `exercise/` | 演习 PvP |
| `gacha/` | 建造系统 |
| `daily/` | 每日任务 |
| `hard/` | 困难模式 |
| `sos/` | SOS 任务 |
| `war_archives/` | 作战档案 |
| `raid/` | 突袭任务 |
| `event/` | 活动处理 |
| `eventstory/` | 活动剧情 |
| `event_hospital/` | 医院活动 |
| `coalition/` | 联动（霜冻/小学院）活动 |
| `island/` | 岛屿系统（赛季任务、科技、运输、项目） |
| `private_quarters/` | 私人休息室（店员、互动、商店） |
| `shipyard/` | 船坞系统 |
| `freebies/` | 免费福利收取 |
| `minigame/` | 小游戏 |
| `awaken/` | 觉醒系统 |
| `retire/` | 退役系统 |
| `equipment/` | 装备管理 |
| `meta_reward/` | META 奖励收取 |
| `daemon/` | 守护模式（后台监控） |
| `statistics/` | 掉落/资源统计和 AzurStats 集成 |
| `notify/` | 推送通知（onepush 集成） |
| `llm.py` | LLM 错误分析（OpenAI API 集成） |
| `logger.py` | 日志系统（Rich、文件轮转、Web UI 流式输出） |
| `webui/` | WebUI 应用 |
| `submodule/` | 外部桥接（AlasFpyBridge、AlasMaaBridge） |

---

## 常用 API 模式

### Button / Template

```python
# Button — 通过平均颜色或模板匹配识别 UI 元素
button = Button(area=(x1, y1, x2, y2), color=(r, g, b), file='assets/cn/module/BUTTON.png')
self.appear(button)           # 检测
self.appear_then_click(button, interval=2)  # 检测并点击

# ButtonGrid — 生成 2D Button 数组
grid = ButtonGrid(origin=(21, 126), delta=(0, 98), button_shape=(60, 80), grid_shape=(1, 5))

# Template — 模板匹配，必须 TEMPLATE_ 前缀
self.appear(TEMPLATE_SHIP)
self.match_template(TEMPLATE_SHIP, similarity=0.85)
```

### Switch / Scroll / Navbar

```python
# Switch — 状态切换
MODE_SWITCH = Switch('Mode_switch_1')
MODE_SWITCH.add_status('normal', SWITCH_1_NORMAL, sleep=STAGE_SHOWN_WAIT)
MODE_SWITCH.add_status('hard', SWITCH_1_HARD, sleep=STAGE_SHOWN_WAIT)

# Scroll — 游戏滚动条
COMMISSION_SCROLL = Scroll(COMMISSION_SCROLL_AREA, color=(247, 211, 66), name='COMMISSION_SCROLL')

# Navbar — 标签导航
navbar_grids = ButtonGrid(origin=(21, 126), delta=(0, 98), button_shape=(60, 80), grid_shape=(1, 5))
GACHA = Navbar(grids=navbar_grids, active_color=(247, 255, 173), inactive_color=(140, 162, 181))
```

### UI 导航

```python
# Page — 带导航链接的游戏画面
page_reward = Page(REWARD_CHECK)
page_reward.link(button=REWARD_GOTO_MAIN, destination=page_main)
page_main.link(button=MAIN_GOTO_REWARD, destination=page_reward)

# 导航方法
ui_goto(page)          # 沿最短路径导航
ui_ensure(page)        # 检测 + 导航
ui_back()              # 点击返回箭头
ui_additional()        # 处理弹窗/对话框
```

### OCR

```python
# 通用文本识别
ocr = Ocr('assets/cn/module/OCR_AREA', lang='cnocr', letter=(255, 255, 255), threshold=128)
result = ocr(self.device.image)

# 数字识别
digit = Digit('assets/cn/module/DIGIT_AREA', lang='azur_lane', letter=(255, 255, 255), threshold=128)
value = digit(self.device.image)  # 返回 int

# 计数器识别
counter = DigitCounter('assets/cn/module/COUNTER_AREA', lang='azur_lane')
current, remain, total = counter(self.device.image)  # 如 14/15 → (14, 1, 15)

# 时长识别
duration = Duration('assets/cn/module/DURATION_AREA', lang='azur_lane')
td = duration(self.device.image)  # 返回 timedelta
```

### 装饰器 (`module/base/decorator.py`)

```python
@Config.when(SERVER='en')        # 基于配置有条件地分发方法
@Config.when(SERVER=None)        # 回退
@cached_property                  # 计算一次，缓存结果
@timer                            # 打印执行时间
@function_drop(rate=0.5)          # 随机跳过
@run_once                         # 只执行一次
@retry(exceptions, tries, delay)  # 带退避的重试
```

### 工具函数 (`module/base/utils.py`)

```python
random_normal_distribution_int(a, b, n=3)       # 正态分布随机整数
random_rectangle_point(area)                     # 区域内随机点
crop(image, area)                                # 裁剪
get_color(image, area)                           # 区域平均颜色
color_similarity(c1, c2)                         # 颜色相似度
color_bar_percentage(image, area, prev_color)    # 进度条百分比
load_image(file)                                 # 加载图像（支持服务器回退）
```

### 地图符号

`++` 陆地、`--` 海洋、`SP` 出生点、`ME` 敌人可能出现、`MB` Boss 可能出现、`MM` 神秘敌人、`MA` 弹药拾取、`MS` 精英/塞壬出现

---

## 图像识别

- **固定分辨率**：1280×720 — 所有资源文件和截图必须匹配
- **资源文件**（`assets/`）：按服务器（cn/en/jp/tw）和功能模块组织
- **Button**：`appear_on()`（平均颜色）或 `match()`（模板匹配）
- **Template**：必须 `TEMPLATE_` 前缀
- **添加 Button 流程**：截图(1280×720) → 复制到 assets/ → PS 裁剪 → `button_extract.py`

---

## 调试

```python
# 调试按钮
az = SomeModule('alas', task='SomeTask')
az.image_file = r'path/to/screenshot.png'
print(az.appear(SOME_BUTTON))

# 调试其他服务器（在导入任何 AzurPilot 模块之前设置）
import module.config.server as server
server.server = 'en'
```

---

## 注释规范

- Google 格式 docstring，中文注释（简体）
- 用 `Pages:` 标注函数进出时的游戏界面状态（如 `Pages: in: page_meowfficer, out: MEOWFFICER_BUY`）
- `logger.hr(title, level)` 标记阶段（0=脚本开始，1=功能开始，2=阶段开始，3=子阶段）
- `logger.attr(name, text)` 记录属性
- 注释占函数的 1/3–1/2，一个函数一个画面，一个文件 ≤500 行

---

## 性能

- ~99% 运行时在等待模拟器截图（~350ms）
- 图像处理 ~2.5ms，地图检测/OCR ~100-180ms
- 不需要过度优化 Python 代码

---

## 关键目录参考

| 目录 | 用途 |
|---|---|
| `alas.py` | 主入口——任务调度器和运行器 |
| `gui.py` | WebUI 启动器 |
| `mcp_server_sse.py` | MCP SSE 服务器 |
| `module/base/` | 基础工具：按钮、模板、装饰器、重试 |
| `module/device/` | 设备连接、截图、输入模拟 |
| `module/config/` | 配置系统 |
| `module/handler/` | 游戏处理器：登录、自动搜索、敌人检测 |
| `module/campaign/` | 战役执行逻辑 |
| `module/ui/` | UI 导航 |
| `module/ocr/` | OCR 系统（RapidOCR/ONNX/NCNN） |
| `module/combat/` | 战斗逻辑 |
| `module/map/` / `module/map_detection/` | 地图处理和检测 |
| `module/os/` | 大世界（地图、摄像机、舰队） |
| `module/research/` | 科研系统 |
| `module/commission/` | 委托系统 |
| `module/statistics/` | 掉落/资源统计 |
| `module/llm.py` | LLM 错误分析 |
| `module/logger.py` | 日志系统 |
| `campaign/` | 活动/地图数据（YAML） |
| `assets/` | UI 模板图像（按服务器和模块组织） |
| `config/` | 配置模板 |
| `deploy/` | 安装脚本、Docker |
| `webapp/` | Electron + Vue 3 桌面应用 |
| `dev_tools/` | 开发工具 |
| `bin/` | 二进制工具和 OCR 模型 |

---

## 代码分析文档

`.agent/` 目录包含项目的深度代码分析文档，**在开始任何开发工作前应先阅读相关文档**。

### 项目级文档

| 文档 | 说明 |
|------|------|
| `.agent/README.md` | 快速上手指南、核心概念、模块索引 |
| `.agent/ARCHITECTURE.md` | 项目整体架构、分层图、依赖关系图 |
| `.agent/CONVENTIONS.md` | 编码规范、命名规则、状态循环模式 |
| `.agent/ISSUES.md` | 已知问题清单、优化路线图 |
| `.agent/MODULE-MAP.md` | 模块映射表、目录结构说明 |

### 核心模块文档

| 文档 | 说明 |
|------|------|
| `.agent/ENTRY-ALAS.md` | alas.py 核心调度器分析 |
| `.agent/ENTRY-GUI.md` | gui.py WebUI 启动器分析 |
| `.agent/ENTRY-MCP-SERVER.md` | mcp_server_sse.py MCP 服务器分析 |
| `.agent/BASE.md` | 基础工具类（ModuleBase、Button、Template） |
| `.agent/CONFIG.md` | 配置系统（AzurLaneConfig、YAML 管道） |
| `.agent/DEVICE.md` | 设备层（ADB、截图、输入模拟） |
| `.agent/UI.md` | UI 导航（Page、A* 路由） |
| `.agent/OCR.md` | OCR 系统（RapidOCR、ONNX、NCNN） |
| `.agent/HANDLER.md` | 处理器层（登录、弹窗、自动搜索） |

### 战斗系统文档

| 文档 | 说明 |
|------|------|
| `.agent/COMBAT.md` | 战斗逻辑（自动/手动战斗、情绪、血量） |
| `.agent/COMBAT-UI.md` | 战斗 UI 资源 |
| `.agent/MAP.md` | 地图处理（摄像机、舰队、网格） |
| `.agent/MAP-DETECTION.md` | 地图检测（透视、单应性、网格识别） |
| `.agent/CAMPAIGN.md` | 战役执行（关卡选择、战斗编排） |

### 游戏功能文档

| 文档 | 说明 |
|------|------|
| `.agent/GAME-FUNCTIONS.md` | 28 个游戏功能模块综合分析 |
| `.agent/OS-SYSTEM.md` | 大世界系统（6 个子模块） |
| `.agent/INFRASTRUCTURE.md` | 基础设施层（统计、通知、守护、WebUI） |

---

## Webapp（Electron）

- **技术栈**：Vue 3 + Ant Design Vue + Electron，pnpm + Vite + electron-builder
- **命令**：`pnpm lint`、`pnpm typecheck`、`pnpm test`（Playwright）
- **构建**：`pnpm build && pnpm compile`
- **Monorepo**：`webapp/packages/main`（主进程）、`webapp/packages/preload`（预加载）、`webapp/packages/renderer`（Vue 前端）

---

## 测试

- **没有 Python 测试套件** — 测试通过运行任务对接真实模拟器进行
- Webapp 有基本的 Playwright 测试（`webapp/tests/app.spec.js`）

---

## CI

GitHub Actions 使用 `uv sync --frozen` 和 `uv run`：
- `lint.yml` — Ruff lint + button_extract + config_updater（检查未提交的 diff）
- `docker-publish.yml` — tag 推送时构建并推送 Docker 镜像
- `sync2.yml` — 推送到 master/dev 时同步到 GitCode 镜像
- `ai-issue-labeler.yml` — 基于 AI 的 issue 标签
- `git-over-cdn-*.yml` — 面向中国用户的 Git over CDN

---

## Python 依赖

关键依赖：
- **核心**：numpy、scipy、pillow、opencv-python、imageio
- **设备**：adbutils、uiautomator2
- **OCR**：rapidocr、ncnn、onnxruntime-directml (Windows)、onnxruntime (Linux/Mac)
- **Web**：pywebio、starlette、uvicorn、aiofiles
- **AI**：openai（LLM 错误分析）、mcp、sse-starlette
- **通知**：onepush
- **工具**：pyyaml、psutil、watchdog、numba、lz4

---

## Git 提交规范

### 提交前分析

提交代码前，必须分析当前 git 工作区中所有未提交的修改（staged、unstaged、untracked），按以下原则组织提交：

1. **理解修改目的**：主动理解每个修改的真实目的，不要简单粗暴地一次性提交
2. **合理聚合**：按功能目标 / 修复目的 / 重构范围 / 工程变更进行聚合
3. **语义边界**：避免把无关修改混在同一个 commit 中，拆分出具有明确语义边界的 commits
4. **区分变更类型**：
   - 格式化、重命名、类型修复、lint 修复 → 独立提交
   - 依赖变更、配置调整 → 独立提交
   - 核心逻辑变更 → 独立提交
5. **识别污染**：识别 AI 生成代码中常见的"顺手修改污染"（无关 import、无意义格式改动、调试代码、日志残留等）

### 提交前检查

检查是否存在以下不应提交的内容：
- 临时代码、console/debug 输出
- 注释掉的大段废弃逻辑
- 未使用文件
- cache/build/dist 产物
- prompt/debug/test residue
- accidentally committed artifacts

### 提交信息格式

使用 Conventional Commits 风格，中文撰写：

```
<type>(<scope>): <描述为什么改>
```

Type 类型：
- `feat`: 新功能
- `fix`: 修复 bug
- `refactor`: 重构
- `perf`: 性能优化
- `chore`: 工程变更
- `docs`: 文档更新
- `test`: 测试相关
- `build`: 构建相关
- `ci`: CI 相关

要求：
- message 不要空泛，要体现"为什么改"
- 避免"修改代码""更新逻辑"这种低信息量描述
- 尽量体现真实意图、影响范围、架构意义

### 示例

```bash
git add module/base/base.py &&
git commit -m "feat(base): 引入任务级上下文隔离机制" && \
git add module/config/watcher.py &&
git commit -m "fix(config): 修复长期记忆污染导致的状态串扰问题" && \
git add alas.py module/daemon/ &&
git commit -m "refactor(runtime): 拆分 workspace 调度与 agent 生命周期管理"
```

### 强耦合说明

如果某些修改之间存在强耦合导致无法拆分，请在提交说明中注明原因。

---

## 代码审查原则（强制）

每次修改代码后，必须以代码审查者的视角进行自我审查：

### 审查清单

1. **完整性**：是否完整满足需求
2. **无关修改**：是否有无关修改（AI 生成代码常见"顺手修改污染"）
3. **兼容性**：是否破坏兼容性
4. **潜在 bug**：是否有潜在 bug
5. **并发/状态**：是否有并发、异步、缓存、状态同步问题
6. **安全隐私**：是否有安全或隐私风险
7. **测试覆盖**：是否缺少测试
8. **简化方案**：是否有更简单的实现方式
9. **命名/抽象**：是否有命名、抽象、边界不清的问题

### 输出格式

```markdown
## 发现的问题
...

## 建议修正
...

## 是否需要继续修改
...
```
