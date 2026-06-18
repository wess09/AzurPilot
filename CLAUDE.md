---
description:
alwaysApply: true
---

# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本仓库中工作时提供指导。

> **重要：必须使用中文交流。** 所有回复、注释、文档、提交信息均使用简体中文。代码中的变量名、函数名使用英文。

## 项目概述

AzurPilot 是碧蓝航线手游的自动化框架。通过 ADB/uiautomator2 控制安卓模拟器，截取屏幕截图，通过图像匹配和 OCR 识别 UI 元素，自动执行游戏任务。支持 CN/EN/JP/TW 游戏服务器，各服务器有独立的资源文件。采用 GPL-3.0 许可证。

**设计约束**：为 7×24h 连续运行设计。不支持真机（长时间运行会黑屏/卡死、截图压缩、OCR 模型迁移问题）。固定 1280×720 分辨率——清晰度与截图延迟的最佳平衡，非标准宽高比没有统一标准。

## 常用命令

本项目使用 **uv** 项目模式管理 Python 依赖。运行环境为项目本地的 `.venv`。

### 环境搭建
```bash
uv sync --frozen                               # 从 pyproject.toml + uv.lock 创建/同步 .venv
```

### 运行应用
```bash
uv run python gui.py    # 启动 WebUI 服务器（默认端口 22267）
uv run python alas.py   # 直接运行调度器
uv run python mcp_server_sse.py  # 启动独立 MCP SSE 服务器（端口 22268）
```

### 代码检查
```bash
# Python（CI 使用 ruff 宽松设置——仅检查致命语法错误和未定义名称）
uv run ruff check . --select E9,F63,F7,F82 --ignore F821,F722

# Webapp（Electron/Vue）
cd webapp && pnpm lint
cd webapp && pnpm typecheck
```

### 构建 Webapp
```bash
cd webapp && pnpm install
cd webapp && pnpm build && pnpm compile
```

### 配置生成（修改配置 YAML 文件后必须执行）
```bash
uv run -m module.config.config_updater
```
重新生成 `args.json`、`menu.json`、`config_generated.py`、`template.json` 和 `i18n/*.json`。

### 资源管理
```bash
uv run -m dev_tools.button_extract    # 从截图中提取按钮定义
```

## 架构

### 核心流程
1. `gui.py` 启动 Web 服务器并管理配置实例
2. `alas.py` (`AzurLaneAutoScript`) 是任务运行器——加载配置、初始化设备、分发任务到处理器
3. 每个任务处理器（如 `module/research/research.py`）继承自基类，使用设备进行截图、UI 检测和输入
4. `module/device/device.py` 封装 ADB/uiautomator2 进行截图捕获和触摸输入
5. UI 导航 (`module/ui/ui.py`) 处理页面检测和游戏画面间的路由
6. 模板匹配 (`module/base/template.py`) 和 OCR (`module/ocr/`) 识别游戏 UI 元素

### 入口点
- **`alas.py`** — 核心调度器。`AzurLaneAutoScript.loop()` 运行无限调度循环：按优先级选择下一个任务、分发到方法、处理错误、休眠到下一个任务。
  - 55 个任务方法（research、commission、tactical、dorm、meowfficer、guild、reward、awaken、shop_frequent 等）
  - 错误处理：返回 `True`（成功）、`False`（不可恢复）或 `'recoverable'`（可自动恢复）
  - 模拟器重启逻辑：`_try_restart_emulator()` 处理 ADB 离线/卡死场景
  - LLM 错误分析：可选集成 OpenAI API 进行错误诊断
  - 配置热重载：`ConfigWatcher` 在任务间检测文件变更
- **`gui.py`** — WebUI 后端（PyWebIO + Starlette + uvicorn）。每个 AzurPilot 配置实例运行在独立的 `multiprocessing.Process` 中。
  - CLI 参数：`--host`、`-p/--port`、`-k/--key`、`--cdn`、`--electron`、`--ssl-key`、`--ssl-cert`、`--run`
  - 热重载模式：`State.deploy_config.EnableReload` 在子进程中生成 `func()`
  - API 路由：`/api/cl1_stats`、`/api/ap_timeline`、`/api/notify`、`/api/notify_stream`、`/api/import_legacy_upload`、`/obs`、`/ws/live_screenshot`
  - MCP 挂载：`app.mount("/mcp", mcp_app)` — MCP SSE 服务器在 `/mcp`
- **`mcp_server_sse.py`** — MCP 服务器，通过 SSE 暴露 18 个工具供外部 AI 助手集成。
  - 服务器名称：`"AzurPilot-MCP"`，传输：`SseServerTransport("/mcp/messages")`
  - 工具：`list_instances`、`get_status`、`list_tasks`、`get_task_help`、`get_resources`、`get_config`、`update_config`、`get_recent_logs`、`start_instance`、`stop_instance`、`get_screenshot`、`get_current_running_task`、`get_scheduler_queue`、`trigger_task`、`clear_scheduler_queue`、`restart_emulator`、`restart_adb`、`update_alas`

### 模块层结构 (`module/`)

**基础层** (`module/base/`):
- `ModuleBase` (`base.py`) — 所有游戏逻辑的根类。组合 `AzurLaneConfig` + `Device`。提供 `appear()`、`appear_then_click()`、`loop()`、图像工具。拥有 `worker` (AsyncExecutor) 用于后台任务。
- `Button` (`button.py`) — UI 元素，包含边界框、颜色、点击区域、模板图像。通过 `file` 属性支持服务器特定资源。继承自 `Resource`。
- `Template` (`template.py`) — 对截图进行模板匹配。支持 GIF 模板。
- `Resource` (`resource.py`) — 跟踪所有 Button/Template 实例的基类，通过 `resource_release()` 支持缓存释放。
- `Mask` (`mask.py`) — 扩展 `Template` 用于灰度遮罩图像。
- `Filter` (`filter.py`) — 基于正则的过滤系统，用于游戏物品（舰船、装备等）。支持预设和 `>` 分隔的优先级排序。
- `Timer` (`timer.py`) — 双重计时器，用于时间计数和访问计数。提供 `reached()`、`reset()`、`reached_and_reset()`。访问计数在慢设备上提供鲁棒性。
- `AsyncExecutor` (`async_executor.py`) — 单例异步执行器，带后台线程用于非阻塞存储/推送操作。
- `ApiClient` (`api_client.py`) — HTTP 客户端，用于错误报告、遥测和公告，支持双域名故障转移。
- `DeviceId` (`device_id.py`) — 通过 WMIC 查询生成硬件指纹用于设备识别。
- `retry` (`retry.py`) — 带退避、抖动和可配置异常处理的重试装饰器。
- `Switch` (`switch.py`) — 在状态间切换（如 normal/hard 模式）。
- `Scroll` (`scroll.py`) — 游戏滚动条处理，基于颜色的位置检测和拖拽操作。
- `Navbar` (`navbar.py`) — 页面内标签导航，带活跃/非活跃颜色检测。

**设备层** (`module/device/`):
- `Device` (`device.py`) — 多重继承：`Screenshot + Control + AppControl + Input`。模拟器交互的统一接口。
- `Connection` (`connection.py`) — ADB 连接层：`adb_connect()`、`adb_reconnect()`、`adb_shell()`、`adb_command()`、`adb_forward()`、`adb_reverse()`、`detect_device()`、`detect_package()`、`install_uiautomator2()`。
- `ConnectionAttr` (`connection_attr.py`) — 持有 `config`、`serial`、`adb_binary`、`adb_client`、`adb`、`u2`，以及设备系列检测的缓存属性（`is_mumu_family`、`is_ldplayer_bluestacks_family`、`is_nox_family`、`is_vmos`、`is_bluestacks4_hyperv`、`is_bluestacks5_hyperv`、`is_wsa`、`is_over_http`）。
- `module/device/method/` — 多种截图/输入后端：
  - **截图后端**：`ADB`、`ADB_nc`、`uiautomator2`、`aScreenCap`、`aScreenCap_nc`、`DroidCast`、`DroidCast_raw`、`scrcpy`、`nemu_ipc`、`ldopengl`
  - **控制后端**：`ADB`、`uiautomator2`、`minitouch`、`Hermit`、`MaaTouch`、`nemu_ipc`
- `module/device/platform/` — 模拟器管理：
  - **Windows 模拟器**：夜神 (32/64)、蓝叠 (4/5, Hyper-V)、雷电 (3/4/9/14)、MuMu (6/9/12)、MEmu
  - **Mac 模拟器**：BlueStacksAir、MuMuPro
  - **其他**：SSH（远程模拟器）
  - 通过 Windows 注册表（MUI Cache、UserAssist、安装路径、卸载注册表）和进程扫描检测

**配置系统** (`module/config/`):
- `config/template.json` 定义所有配置选项的 schema 和默认值。
- `module/config/config_generated.py` 从 `template.json` 自动生成——提供 IDE 自动补全。
- `module/config/config_updater.py` 在 `template.json` 变更时重新生成 `config_generated.py`。
- `module/config/config.py` (`AzurLaneConfig`) 从 `config/{config_name}.json` 加载用户配置并与模板合并。
- `AzurLaneConfig` 继承自 `ConfigUpdater + ManualConfig + GeneratedConfig + ConfigWatcher`
- 用户配置文件存储在 `config/{config_name}.json`（如 `config/alas.json`）。
- 4 层 YAML 管道用于 GUI：`task.yaml` + `argument.yaml` + `override.yaml` + `default.yaml` → `args.json`
- `config_updater.py` 生成：`args.json`、`menu.json`、`config_generated.py`、`template.json`、`i18n/*.json`。
- 配置路径格式：`<Task>.<Group>.<Argument>`（如 `Main.Campaign.Name`）。
- 访问配置：`self.config.Group_Argument`（下划线分隔）。
- `server.py` — 全局服务器选择器：`server = 'cn'`。函数：`set_server()`、`to_server()`、`to_package()`。有效服务器：`['cn', 'en', 'jp', 'tw']`。
- `watcher.py` — `ConfigWatcher` 跟踪文件修改时间：`start_watching()`、`get_mtime()`、`should_reload()`。
- `deep.py` — 高性能嵌套字典访问：`deep_get()`、`deep_set()`、`deep_pop()`、`deep_iter()`、`deep_iter_diff()`、`deep_iter_patch()`。
- `utils.py` — 工具函数：`LANGUAGES`、`SERVER_TO_LANG`、`SERVER_TO_TIMEZONE`、`filepath_args()`、`filepath_config()`、`read_file()`、`write_file()`、`parse_value()`、`alas_instance()`、`is_oobe_needed()`。
- `mcp_helper.py` — 用于 AI/MCP 集成的 `McpConfigHelper`：`get_tasks()`、`get_task_details()`、`get_dashboard_resources()`。
- `redirect_utils/` — 版本升级的配置迁移重定向函数。

**UI 导航** (`module/ui/`):
- `Page` (`page.py`) — 基于图的导航。每个页面有 `check_button` 和 `links` 字典。使用 A* 寻路找到最短导航路径。
- `UI` (`ui.py`) — `ui_goto(page)`、`ui_page_appear()`、`ui_ensure()`、`ui_back()`。
- `ui_white/` — 特定画面的白色主题 UI 资源。

**OCR 系统** (`module/ocr/`):
- `Ocr` (`ocr.py`) — 通用文本识别。支持 `lang` 选项：`'azur_lane'`、`'cnocr'`、`'jp'`、`'tw'`。预处理图像提取字母，然后使用 OCR 模型。
- `Digit` (`ocr.py`) — 识别数字，返回 `int`。后处理修正常见 OCR 错误（I→1, D→0, S→5, B→8）。
- `DigitCounter` (`ocr.py`) — 识别计数器如 `14/15`，返回 `(current, remain, total)`。
- `Duration` (`ocr.py`) — 识别时长如 `08:00:00`，返回 `timedelta`。
- `OcrYuv`、`DigitYuv`、`DigitCounterYuv`、`DurationYuv` — YUV 色彩空间变体。
- `AlOcr` (`al_ocr.py`) — 基于 RapidOCR 的后端，支持 NCNN。支持 DirectML (Windows) 和 CoreML (macOS) GPU 加速。
- `NcnnRecOCR` (`ncnn_ocr.py`) — 基于 NCNN 的 OCR 识别，推理更快。模型：en、cn、jp、tw。模型存储在 `bin/ocr_models/ncnn/`。
- `ModelProxyFactory` (`rpc.py`) — 基于 zerorpc 的 OCR 服务器模式，用于分布式推理。
- `models.py` — 惰性加载的 OCR 模型实例：`azur_lane` (EN)、`azur_lane_jp` (JP)、`cnocr` (中+英)、`jp` (日文)、`tw` (繁体中文)。
- ONNX 模型存储在 `bin/ocr_models/`，NCNN 模型在 `bin/ocr_models/ncnn/`。

**处理器层** (`module/handler/`):
- `InfoHandler` (`info_handler.py`) — 弹窗/对话框检测和关闭的基础处理器。继承 `ModuleBase`。
- `LoginHandler` (`login.py`) — 应用重启/登录流程处理。
- `AutoSearchHandler` (`auto_search.py`) — 自动搜索战斗处理。
- `EnemySearchingHandler` (`enemy_searching.py`) — 地图操作中的敌人检测。
- `FastForwardHandler` (`fast_forward.py`) — 快进按钮处理。
- `AmbushHandler` (`ambush.py`) — 伏击遭遇处理。
- `MysteryHandler` (`mystery.py`) — 神秘格子处理。
- `StrategyHandler` (`strategy.py`) — 策略面板处理。
- `SensitiveInfoHandler` (`sensitive_info.py`) — 敏感信息遮罩。

**战斗系统** (`module/combat/`):
- `Combat` (`combat.py`) — 主战斗处理器。继承 `Level + HPBalancer + Retirement + SubmarineCall + CombatAuto + CombatManual`。
- `AutoSearchCombat` (`auto_search_combat.py`) — 自动搜索战斗处理。
- `CombatAuto` (`combat_auto.py`) — 自动战斗模式。
- `CombatManual` (`combat_manual.py`) — 手动战斗模式。
- `Emotion` (`emotion.py`) — 情绪追踪和管理。
- `HPBalancer` (`hp_balancer.py`) — 战斗中的血量平衡。
- `Level` (`level.py`) — 等级检测。
- `SubmarineCall` (`submarine.py`) — 潜艇呼叫处理。

**地图系统** (`module/map/`):
- `Map` (`map.py`) — 主地图处理器。继承 `MapOperation + MapCamera + MapFleet`。
- `MapBase` (`map_base.py`) — 基础地图网格操作。
- `MapCamera` (`camera.py`) — 地图摄像机控制。
- `MapFleet` (`fleet.py`) — 地图上的舰队管理。
- `MapGrids` (`map_grids.py`) — 网格检测和管理。
- `MapOperation` (`map_operation.py`) — 地图操作（移动、攻击等）。

**地图检测** (`module/map_detection/`):
- `Detector` (`detector.py`) — 主地图检测器。
- `Grid` (`grid.py`) — 网格检测。
- `GridPredictor` (`grid_predictor.py`) — 网格预测。
- `Homography` (`homography.py`) — 单应性变换。
- `Perspective` (`perspective.py`) — 透视校正。

**游戏逻辑模块** — 每个功能有自己的子目录。每个模块有自己的 `assets.py` 定义 Button/Template 对象。任务模块包含 `run()` 方法。

**战役系统** (`module/campaign/`):
- `CampaignBase` (`campaign_base.py`) — 基础战役执行逻辑。继承 `CampaignUI + Map + AutoSearchCombat`。
- `CampaignEvent` (`campaign_event.py`) — 活动战役处理。
- `CampaignOcr` (`campaign_ocr.py`) — 战役 OCR 用于关卡识别。
- `CampaignStatus` (`campaign_status.py`) — 战役状态追踪。
- `CampaignUI` (`campaign_ui.py`) — 战役 UI 导航。
- `GemsFarming` (`gems_farming.py`) — 钻石 farming 自动化。
- `Run` (`run.py`) — 战役运行编排。

**战役数据** (`campaign/`) — 地图定义文件通过 `importlib.import_module()` 动态加载。按事件/日期组织。

**资源** (`assets/`) — PNG 图像按服务器 (cn/en/jp/tw) 然后按模块组织。以 Button 常量命名（如 `BATTLE_PREPARATION.BUTTON.png`）。

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
优先级顺序：`Restart > OpsiCrossMonth > Commission > Tactical > Research > Exercise > Dorm > Meowfficer > Guild > Gacha > Reward > ShopFrequent > ... > Main > Main2 > Main3 > GemsFarming`

同一任务连续失败 3 次触发 `RequestHumanTakeover`。任务间通过 `ConfigWatcher` 热重载配置。`RESTART_SENSITIVE_TASKS = ['Commission', 'Research']` 的任务触发严格重启行为。

**任务分发**：`AzurLaneAutoScript.run(command)` 通过 `self.__getattribute__(command)()` 分发。返回 `True`（成功）、`False`（不可恢复）或 `'recoverable'`（可自动恢复，不计入失败次数）。

**空闲时**：`get_next_task()` 检查 `Optimization_WhenTaskQueueEmpty` 设置：`close_game`、`goto_main` 或 `stay_there`。

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

        # 结束条件——使用 appear()，不设 interval
        if self.appear(END_CONDITION):
            break

        # 点击——使用 interval 防止快速重复点击（2-5 秒）
        if self.appear_then_click(BUTTON_A, interval=2):
            continue
        if self.appear_then_click(BUTTON_B, interval=3):
            continue
```

规则：
- `skip_first_screenshot=True` 复用上一个状态循环的截图（避免冗余捕获）。
- `interval` 参数防止快速重复点击（通常 2-5 秒）。退出条件不要设 interval。
- 状态循环内不要添加 `sleep()`。
- 不要使用负条件控制循环。
- 不要将 `appear_then_click()` 作为循环退出条件——退出用 `appear()`。
- 不要嵌套状态循环——扁平化到父循环中。
- `handle_*()` 方法返回 `bool`：`True` 表示"已采取行动，需要新截图"。

### 死循环检测
- `GameStuckError`：1 分钟内无有效截图操作（战斗/启动期间为 5 分钟）。
- `GameTooManyClickError`：最近 15 次操作中，一个按钮被点击 ≥12 次，或两个按钮各 ≥6 次。

### 异常层次 (`module/exception.py`)
- **正常战役结束**：`CampaignEnd`、`OilExhausted`、`OilMaxed`
- **地图导航错误**：`MapDetectionError`、`MapWalkError`、`MapEnemyMoved`、`CampaignNameError`
- **游戏状态错误**（触发重启）：`GameStuckError`、`GameBugError`、`GameTooManyClickError`
- **连接/页面错误**：`GameNotRunningError`、`GamePageUnknownError`、`EmulatorNotRunningError`
- **开发者错误**：`ScriptError`、`ScriptEnd`
- **不可恢复**：`RequestHumanTakeover`、`AutoSearchSetError`

### 分辨率
固定 1280×720 用于所有图像识别。所有截图和资源必须匹配此分辨率。

### 调试按钮
```python
# 运行：uv run debug_button.py
az = SomeModule('alas', task='SomeTask')
az.image_file = r'path/to/screenshot.png'
print(az.appear(SOME_BUTTON))
```

### 调试其他服务器
```python
import module.config.server as server
server.server = 'en'  # 在导入任何 AzurPilot 模块之前设置
```

## 配置系统工作流

### 源文件（手动编辑）

| 文件 | 用途 |
|---|---|
| `module/config/argument/task.yaml` | 任务→选项组映射、菜单结构 |
| `module/config/argument/argument.yaml` | 参数定义（type、value、option、validate、display） |
| `module/config/argument/override.yaml` | 不可修改的覆盖值（`display: hide`） |
| `module/config/argument/default.yaml` | 可修改的任务特定默认值 |
| `module/config/argument/gui.yaml` | GUI 界面翻译键 |
| `module/config/argument/dashboard.yaml` | 仪表盘资源列表 |

### 生成产物（不要手动编辑）

- `module/config/argument/args.json` — 合并后的完整参数定义
- `module/config/argument/menu.json` — 菜单定义
- `module/config/config_generated.py` — Python 配置类
- `module/config/i18n/{zh-CN,zh-MIAO,en-US,ja-JP,zh-TW}.json` — 五种语言翻译文件
- `config/template.json` — 配置模板

### 正确操作步骤

1. 编辑 YAML 源文件（`argument.yaml` / `task.yaml` / `default.yaml` / `override.yaml` / `gui.yaml`）。
2. 运行 `uv run -m module.config.config_updater` 重新生成所有产物。
3. **【必须手动】翻译新增的 i18n 条目**：打开 `i18n/<lang>.json`，找到值为 `"Group.Argument.name"` 这样的 key 路径字符串，逐行替换为正确的翻译文本。已有翻译会被保留（生成器从旧文件读取），只有新增 key 需要翻译。
4. zh-TW 会自动简繁转换，但仍需人工校对。

### i18n 翻译生成机制

生成器对每种语言执行 `generate_i18n(lang)`：
- 从旧翻译文件读取已有翻译（保留）
- 新增 key 的默认值 = key 路径本身（如 `"Campaign.Event.name"`），需人工翻译
- 活动名称优先使用同语言服务器名称，回退顺序 `en → cn → jp → tw`
- 五种语言：`zh-CN`、`zh-MIAO`、`en-US`、`ja-JP`、`zh-TW`

### 配置加载流程（运行时）
```
AzurLaneConfig("alas")
  → init_task(task)
    → load()
      → read_file("./config/alas.json")     # 读取用户 JSON
      → config_update(old)                   # 与 args.json 默认值合并
      → config_redirect(old, new)            # 版本迁移
      → _override(new)                       # 云手机覆盖
    → config_override()                      # 强制覆盖，重置过期 NextRun
    → bind(task)                             # 映射属性名到配置路径
    → save()                                 # 写回磁盘
```

## 常见开发任务

### 添加新活动
1. 在 `campaign/` 下创建新目录（如 `event_YYYYMMDD_cn`）
2. 在新目录中添加地图 YAML 文件
3. 更新 `campaign/Readme.md` 中的活动表
4. 运行 `uv run -m module.config.config_updater`
5. 在 `assets/cn/event/` 中添加对应的模板图像

### 添加新功能
1. 在 `module/` 下创建新的模块目录
2. 创建包含 `run()` 方法的处理器类
3. 在 `alas.py` 的 `AzurLaneAutoScript` 类中添加对应的任务方法
4. 在 `config/template.json` 中添加配置项
5. 运行 `uv run -m module.config.config_updater`
6. 在 `assets/` 中添加 UI 模板图像

### 运行特定任务
任务方法定义在 `alas.py` 的 `AzurLaneAutoScript` 上。常见任务：`research`、`commission`、`tactical`、`dorm`、`meowfficer`、`guild`、`reward`、`awaken`、`shop_frequent`。每个方法从 `module/` 实例化处理器并调用其 `run()` 方法。

### 开发工具
```bash
uv run -m deploy.installer              # 运行 AzurPilot 安装器
uv run dev_tools/map_extractor.py       # 从截图提取地图数据
uv run dev_tools/campaign_swipe.py      # 战役滑动测试工具
uv run dev_tools/item_statistics.py     # 物品统计提取
uv run dev_tools/research_extractor.py  # 提取科研数据
uv run dev_tools/research_optimizer.py  # 优化科研策略
uv run dev_tools/island_extractor.py    # 提取岛屿数据
uv run dev_tools/war_archives_update.py # 更新作战档案数据
uv run dev_tools/os_extract.py          # 提取大世界数据
uv run dev_tools/uiautomator2_screenshot.py  # 测试 uiautomator2 截图
uv run dev_tools/emulator_test.py       # 测试模拟器连接
uv run dev_tools/relative_record.py     # 记录相对位置
uv run dev_tools/grids_debug.py         # 调试网格检测
```

## 关键目录参考

| 目录 | 用途 |
|---|---|
| `alas.py` | 主入口——任务调度器和运行器（`AzurLaneAutoScript` 类） |
| `gui.py` | Web UI 启动器（uvicorn 服务器 + PyWebIO） |
| `mcp_server_sse.py` | MCP SSE 服务器，用于 AI 助手集成 |
| `module/` | 核心逻辑模块——每个子目录对应一个游戏功能 |
| `module/base/` | 基础工具：按钮处理、模板匹配、装饰器、重试逻辑 |
| `module/device/` | 设备连接、截图捕获、输入模拟（基于 ADB） |
| `module/config/` | 配置系统——基于 JSON/YAML 的配置管理 |
| `module/handler/` | 游戏处理器：登录、自动搜索、敌人检测、快进 |
| `module/campaign/` | 战役（战斗）执行逻辑 |
| `module/ui/` | UI 导航：页面检测、按钮路由、导航栏 |
| `module/ocr/` | OCR 系统：使用 RapidOCR/ONNX/NCNN 后端的文本识别 |
| `module/combat/` | 战斗逻辑：自动搜索、情绪、血量平衡、潜艇 |
| `module/map/` | 地图处理：摄像机、舰队、网格、操作 |
| `module/map_detection/` | 地图检测：单应性、透视、网格预测 |
| `module/os/` | 大世界——地图、摄像机、世界地图、舰队管理 |
| `module/os_combat/` | 大世界战斗逻辑 |
| `module/os_handler/` | 大世界事件处理器 |
| `module/os_ash/` | 大世界余烬/信标系统 |
| `module/os_shop/` | 大世界商店 |
| `module/os_simulator/` | 大世界地图模拟器 |
| `module/research/` | 科研系统 |
| `module/commission/` | 委托系统 |
| `module/tactical/` | 战术学院系统 |
| `module/dorm/` | 宿舍管理 |
| `module/meowfficer/` | 指挥喵管理 |
| `module/guild/` | 大舰队系统 |
| `module/shop/` | 商店系统 |
| `module/shop_event/` | 活动商店系统 |
| `module/reward/` | 奖励收取 |
| `module/exercise/` | 演习 PvP |
| `module/gacha/` | 建造系统 |
| `module/daily/` | 每日任务 |
| `module/hard/` | 困难模式 |
| `module/sos/` | SOS 任务 |
| `module/war_archives/` | 作战档案 |
| `module/raid/` | 突袭任务 |
| `module/event/` | 活动处理 |
| `module/eventstory/` | 活动剧情处理 |
| `module/event_hospital/` | 医院活动 |
| `module/coalition/` | 联动（霜冻/小学院）活动 |
| `module/island/` | 岛屿系统（赛季任务、科技、运输、项目） |
| `module/private_quarters/` | 私人休息室（店员、互动、商店） |
| `module/shipyard/` | 船坞系统 |
| `module/freebies/` | 免费福利收取 |
| `module/minigame/` | 小游戏 |
| `module/awaken/` | 觉醒系统 |
| `module/retire/` | 退役系统 |
| `module/equipment/` | 装备管理 |
| `module/meta_reward/` | META 奖励收取 |
| `module/daemon/` | 守护模式（后台监控） |
| `module/statistics/` | 掉落/资源统计和 AzurStats 集成 |
| `module/azur_stats/` | AzurStats 数据提交 |
| `module/log_res/` | 日志资源管理 |
| `module/notify/` | 推送通知（onepush 集成） |
| `module/llm.py` | LLM 错误分析（OpenAI API 集成） |
| `module/logger.py` | 日志系统（基于 Rich、文件轮转、Web UI 流式输出） |
| `module/webui/` | WebUI 应用（PyWebIO + Starlette） |
| `module/submodule/` | 外部桥接（AlasFpyBridge、AlasMaaBridge） |
| `campaign/` | 活动/地图数据文件——每个活动有自己的子目录和 YAML 地图定义 |
| `assets/` | UI 识别的模板图像，按服务器 (cn/en/jp/tw) 和功能组织 |
| `config/` | 配置模板（`template.json`、`deploy.template.yaml` 等） |
| `deploy/` | 安装脚本、Docker 设置、平台特定部署（AidLux、Windows） |
| `webapp/` | Electron + Vue 3 桌面应用 |
| `dev_tools/` | 开发工具：地图提取器、战役滑动工具、物品统计 |
| `bin/` | 二进制工具：DroidCast、scrcpy、ascreencap、MaaTouch、OCR 模型 |
| `submodule/` | 外部桥接：AlasFpyBridge、AlasMaaBridge |

## 测试
没有正式的 Python 测试套件。Webapp 有基本的 Playwright 测试（`webapp/tests/app.spec.js`）。测试通过在真实模拟器实例上运行任务完成。

## 备注
- `alas.py` 中的 `run()` 方法抛出异常而不是调用 `exit(1)`，允许调度循环捕获并重试
- 不同服务器区域 (CN/EN/JP/TW) 使用 `assets/` 下不同的模板图像
- `bin/` 包含截图捕获工具和 OCR 模型；默认方法因平台而异
- `campaign/` 中的地图文件是 YAML 格式，定义网格布局、敌人位置和出生点
- 大世界是最复杂的功能，跨越 `module/os/`、`module/os_combat/`、`module/os_handler/`、`module/os_ash/` 和 `module/os_shop/`
- LLM 错误分析（`module/llm.py`）使用 OpenAI API 诊断错误；通过 `Error_LlmAnalysis`、`Error_LlmApiKey`、`Error_LlmApiBase`、`Error_LlmModel` 配置
- 日志器（`module/logger.py`）使用 Rich 进行带颜色格式化的控制台输出；支持文件轮转和 Web UI 流式输出
- 推送通知（`module/notify/`）使用 onepush 库支持多渠道通知（QQ、微信等）
- MCP 服务器（`mcp_server_sse.py`）通过 SSE 传输提供 18 个工具供外部 AI 助手集成

## 关键约定

- **注释**：使用 Google docstring 风格。包含 `Pages:` 注解标注游戏 UI 状态（如 `Pages: in: page_meowfficer, out: MEOWFFICER_BUY`）。注释使用简体中文。注释占函数的 1/3–1/2，一个函数一个画面，一个文件 ≤500 行。
- **日志**：使用 `logger.hr(title, level)` 做节标题（level 0=脚本开始, 1=功能开始, 2=阶段开始, 3=子阶段），`logger.attr(name, value)` 记录属性。避免过度使用强调——如果什么都强调，就等于没强调。
- **命名**：`point` = (x,y) 屏幕坐标，`area` = (x1,y1,x2,y2) 边界框，`location` = (x,y) 网格坐标，`node` = "E3" 字符串网格引用。
- **模块独立性**：所有模块可独立运行，不依赖 GUI 或用户配置。每个模块通常只有一个方法读取用户配置。
- **性能**：~99% 的运行时间在等待模拟器截图（~350ms）。图像处理 ~2.5ms。地图检测/OCR ~100-180ms。不要过度优化 Python 代码。
- **异常处理**：异常只在顶层捕获。捕获时，日志和最近截图保存到单独的文件夹。用户身份信息被擦除。

## 常用 API 模式

### UI 组件
```python
# Switch——在状态间切换
MODE_SWITCH = Switch('Mode_switch_1')
MODE_SWITCH.add_status('normal', SWITCH_1_NORMAL, sleep=STAGE_SHOWN_WAIT)
MODE_SWITCH.add_status('hard', SWITCH_1_HARD, sleep=STAGE_SHOWN_WAIT)

# Scroll——游戏滚动条
COMMISSION_SCROLL = Scroll(COMMISSION_SCROLL_AREA, color=(247, 211, 66), name='COMMISSION_SCROLL')

# NavBar——标签导航
navbar_grids = ButtonGrid(origin=(21, 126), delta=(0, 98), button_shape=(60, 80), grid_shape=(1, 5))
GACHA = Navbar(grids=navbar_grids, active_color=(247, 255, 173), inactive_color=(140, 162, 181))

# Page——带导航链接的游戏画面
page_reward = Page(REWARD_CHECK)
page_reward.link(button=REWARD_GOTO_MAIN, destination=page_main)
page_main.link(button=MAIN_GOTO_REWARD, destination=page_reward)
```

### UI 导航方法
- `ui_click()` — 点击按钮并等待下一画面
- `ui_get_current_page()` — 检测当前所在页面
- `ui_goto(page)` — 沿最短路径导航到目标页面
- `ui_ensure(page)` — `ui_get_current_page()` + `ui_goto()`
- `ui_ensure_index()` — 翻页浏览地图章节
- `ui_goto_main()` — 导航到主画面
- `ui_back()` — 点击返回箭头
- `ui_additional()` — 处理弹窗/对话框

### Button 和 Template 类
- `Button` — 通过平均颜色 (`appear_on()`) 或模板匹配 (`match()`) 识别 UI 元素。`button` 属性在区域内生成随机点击点。
- `ButtonGrid(origin, delta, button_shape, grid_shape)` — 生成 2D Button 数组。
- `Template` — 模板匹配。必须以 `TEMPLATE_` 为前缀。方法：`match()`、`match_result()`、`match_multi()`。
- 添加新 Button：在 1280×720 下截图，复制到 `assets/`，在 Photoshop 中裁剪，运行 `uv run -m dev_tools.button_extract`。

### OCR 类 (`module/ocr/`)
- `Ocr` — 通用文本识别
- `Digit` — 识别数字，返回 `int`
- `DigitCounter` — 识别计数器如 `14/15`
- `Duration` — 识别时长如 `08:00:00`
- `OcrYuv`、`DigitYuv`、`DigitCounterYuv`、`DurationYuv` — YUV 色彩空间变体
- `AlOcr` — RapidOCR 后端，ONNX/NCNN 推理，GPU 加速（DirectML/CoreML）
- OCR 模型：`azur_lane`（游戏数字/字母）、`cnocr`（中+英）、`jp`（日文）、`tw`（繁体中文）
- OCR 后端：`onnx`（默认）、`ncnn`（推理更快）
- OCR 设备：`cpu`、`gpu`（Windows 上 DirectML）、`ane`（macOS 上 CoreML）

### 装饰器 (`module/base/decorator.py`)
- `@Config.when(SERVER='en')` — 基于配置有条件地分发方法（如服务器特定行为）。为其他服务器定义 `@Config.when(SERVER=None)` 回退。
- `@cached_property` — 计算一次，缓存结果。
- `@timer` — 打印函数执行时间。
- `@function_drop(rate=0.5, default=None)` — 随机跳过函数执行。
- `@run_once` — 函数只运行一次，无论调用多少次。
- `@retry(exceptions, tries, delay, backoff, jitter)` — 带退避的重试装饰器。

### 工具函数 (`module/base/utils.py`)
- `random_normal_distribution_int(a, b, n=3)` — 正态分布随机整数 [a, b)
- `random_rectangle_point(area)` — 区域内的随机点（2D 正态分布）
- `random_rectangle_vector(vector, box, random_range, padding)` — 在框内随机放置向量
- `crop(image, area)` — 裁剪图像
- `get_color(image, area)` — 区域的平均颜色
- `color_similarity(color1, color2)` / `color_similar(color1, color2, threshold)` — 颜色比较
- `color_bar_percentage(image, area, prev_color, reverse, starter, threshold)` — 进度条百分比
- `load_image(file)` — 加载图像，支持服务器特定回退
- `extract_letters(image, letter, threshold)` — 从图像中提取字母颜色
- `lower_template_match_similarity(similarity)` — 对非原生 720p 截图放宽匹配阈值

### 地图符号
- `++` 陆地（不可通行）、`--` 海洋、`SP` 舰队出生点、`ME` 敌人可能出现、`MB` Boss 可能出现、`MM` 神秘敌人、`MA` 弹药拾取、`MS` 精英/塞壬出现

## Python 依赖
所有依赖管理使用 **uv** 项目模式。直接依赖声明在 `pyproject.toml` 中，平台差异使用 PEP 508 标记，锁定的解析提交在 `uv.lock` 中。不要添加或重新生成 `requirements*.txt`。

关键依赖：
- **Python**：>=3.14,<3.15
- **核心**：numpy、scipy、pillow、opencv-python、imageio、imageio-ffmpeg
- **设备**：adbutils、uiautomator2、uiautomator2cache
- **OCR**：rapidocr、ncnn、onnxruntime-directml (Windows)、onnxruntime (Linux/Mac)
- **Web**：pywebio、starlette、uvicorn、aiofiles
- **通知**：onepush
- **AI**：openai（用于 LLM 错误分析）
- **MCP**：mcp、sse-starlette
- **工具**：pyyaml、inflection、psutil、chardet、matplotlib、pycryptodome、watchdog、numba、lz4

## Webapp（Electron）
独立的前端在 `webapp/`——Vue 3 + Ant Design Vue + Electron。使用 pnpm、Vite、electron-builder。用 `pnpm lint` 检查，`pnpm typecheck` 类型检查，`pnpm test` 测试。

Monorepo 结构：`webapp/packages/main`（Electron 主进程）、`webapp/packages/preload`（预加载脚本）、`webapp/packages/renderer`（Vue 前端）。

## CI
GitHub Actions 使用 `uv sync --frozen` 和 `uv run`。运行：ruff lint、`button_extract.py`、`config_updater.py`（检查未提交的 diff）、Docker 发布、上游同步。

工作流文件：
- `lint.yml` — Ruff lint + button_extract + config_updater（检查未提交的 diff）
- `docker-publish.yml` — 标签推送时构建并推送 Docker 镜像
- `sync2.yml` — 推送到 master/dev 时同步到 GitCode 镜像
- `ai-issue-labeler.yml` — 基于 AI 的 issue 标签
- `git-over-cdn-*.yml` — 面向中国用户的 Git over CDN

## 代码分析文档

`.agent/` 目录包含项目的深度代码分析文档，**在开始任何开发工作前应先阅读相关文档**。

### 快速入口

| 场景 | 推荐阅读 |
|------|---------|
| **首次了解项目** | `.agent/README.md` → `.agent/ARCHITECTURE.md` |
| **理解任务调度** | `.agent/ENTRY-ALAS.md` |
| **修改配置系统** | `.agent/CONFIG.md` |
| **添加新功能模块** | `.agent/GAME-FUNCTIONS.md` → `.agent/BASE.md` |
| **修改战斗逻辑** | `.agent/COMBAT.md` → `.agent/MAP.md` → `.agent/CAMPAIGN.md` |
| **修改 UI 导航** | `.agent/UI.md` |
| **修改 OCR 识别** | `.agent/OCR.md` |
| **修改设备连接** | `.agent/DEVICE.md` |
| **了解大世界系统** | `.agent/OS-SYSTEM.md` |
| **了解编码规范** | `.agent/CONVENTIONS.md` |
| **查看已知问题** | `.agent/ISSUES.md` |

### 文档索引

| 文档 | 说明 |
|------|------|
| `.agent/README.md` | 快速上手指南、核心概念、模块索引 |
| `.agent/ARCHITECTURE.md` | 项目整体架构、分层图、依赖关系图 |
| `.agent/CONVENTIONS.md` | 编码规范、命名规则、状态循环模式 |
| `.agent/ISSUES.md` | 已知问题清单、优化路线图 |
| `.agent/MODULE-MAP.md` | 模块映射表、目录结构说明 |
| `.agent/ENTRY-ALAS.md` | alas.py 核心调度器分析 |
| `.agent/ENTRY-GUI.md` | gui.py WebUI 启动器分析 |
| `.agent/ENTRY-MCP-SERVER.md` | mcp_server_sse.py MCP 服务器分析 |
| `.agent/BASE.md` | 基础工具类（ModuleBase、Button、Template） |
| `.agent/CONFIG.md` | 配置系统（AzurLaneConfig、YAML 管道） |
| `.agent/DEVICE.md` | 设备层（ADB、截图、输入模拟） |
| `.agent/UI.md` | UI 导航（Page、A* 路由） |
| `.agent/OCR.md` | OCR 系统（RapidOCR、ONNX、NCNN） |
| `.agent/HANDLER.md` | 处理器层（登录、弹窗、自动搜索） |
| `.agent/COMBAT.md` | 战斗逻辑（自动/手动战斗、情绪、血量） |
| `.agent/COMBAT-UI.md` | 战斗 UI 资源 |
| `.agent/MAP.md` | 地图处理（摄像机、舰队、网格） |
| `.agent/MAP-DETECTION.md` | 地图检测（透视、单应性、网格识别） |
| `.agent/CAMPAIGN.md` | 战役执行（关卡选择、战斗编排） |
| `.agent/GAME-FUNCTIONS.md` | 28 个游戏功能模块综合分析 |
| `.agent/OS-SYSTEM.md` | 大世界系统（6 个子模块） |
| `.agent/INFRASTRUCTURE.md` | 基础设施层（统计、通知、守护、WebUI） |

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
