# AzurPilot 仓库指南

**AzurPilot** 是基于 AzurLaneAutoScript (ALAS) 修改的碧蓝航线自动化辅助框架。通过 ADB/uiautomator2 控制 Android 模拟器，使用截图 + 图像匹配 + OCR 识别 UI 并自动执行游戏任务。

---

## 开发环境

- **Python ≥3.14**（项目要求 3.14+，CI 使用 ubuntu-latest + Python 3.14）
- **uv** 包管理器（非 pip/poetry）。`pyproject.toml` 中 `package = false`，所以需用 `uv run python script.py` 而非 `uv run script.py`
- **依赖安装**：`uv sync --frozen`（创建/同步 `.venv`）
- **运行时 Python 环境**：项目本地 `.venv/`
- **不维护 `requirements*.txt`**——所有依赖在 `pyproject.toml` 中声明，`uv.lock` 提交到 git

## 入口点

| 文件 | 用途 |
|---|---|
| `alas.py` | 核心调度器——`AzurLaneAutoScript.loop()` 运行无限调度循环 |
| `gui.py` | WebUI 后端——PyWebIO + Starlette + uvicorn，每个配置实例在独立子进程中运行 |
| `mcp_server_sse.py` | MCP SSE 服务——暴露 18 个工具供外部 AI Agent 集成（端口 22267） |

## 基本命令

```bash
# 运行 WebUI
uv run python gui.py

# 直接运行调度器
uv run python alas.py

# 安装依赖
uv sync --frozen

# CI lint（仅 E9/F63/F7/F82——不重要，不是完整 ruff 规则集）
uv run ruff check . --select E9,F63,F7,F82 --ignore F821,F722

# 配置生成（修改 YAML 源文件后必须运行）
uv run -m module.config.config_updater

# 按钮提取
uv run -m dev_tools.button_extract
```

## 配置系统（关键陷阱）

**永远不要手动编辑**以下自动生成的文件：
- `config/argument/args.json`
- `config/argument/menu.json`
- `module/config/config_generated.py`
- `config/template.json`
- `i18n/*.json`

**应编辑的源文件**（在 `module/config/argument/` 下）：
- `task.yaml` —— 任务→选项组映射
- `argument.yaml` —— 选项组→选项属性定义
- `override.yaml` —— 值/显示覆盖
- `gui.yaml` —— GUI 界面文本（i18n 源）

**修改 YAML 后**必须运行 `config_updater.py` 重新生成所有衍生文件。

**CI 会检查** `button_extract.py` 和 `config_updater.py` 是否有未提交的 diff——如果有则 CI 失败。

**配置访问路径**：`self.config.Group_Argument`（下划线分隔），对应 GUI 中的 `<Task>.<Group>.<Argument>`。

## 核心设计规则

### 状态循环模式（强制要求）

```python
# 正确——使用连续截图+检查循环
def some_function(self, skip_first_screenshot=True):
    while 1:
        if skip_first_screenshot:
            skip_first_screenshot = False
        else:
            self.device.screenshot()
        if self.appear(END_CONDITION):       # 退出条件，不要加 interval
            break
        if self.appear_then_click(BUTTON_A, interval=2):  # 点击，加 interval 防连击
            continue
```

### 绝对禁止的模式
- ❌ `click(X); sleep(2)` —— 禁止"点击-等待"模式
- ❌ `sleep()` 出现在状态循环内
- ❌ 使用负面条件做循环控制（`if not self.appear(...)`）
- ❌ 用 `appear_then_click()` 做循环退出条件——用 `appear()` 退出
- ❌ 嵌套状态循环——展平到父循环
- ❌ 给退出条件设置 `interval`

### 死循环检测
- `GameStuckError`：无操作截图超过 1 分钟（战斗/启动中为 5 分钟）
- `GameTooManyClickError`：最近 15 次操作中单按钮点击 ≥12 次，或两个按钮各 ≥6 次

## 异常层次

| 异常 | 含义 |
|---|---|
| `CampaignEnd`, `OilExhausted` | **正常**战役结束——不是错误 |
| `MapDetectionError`, `MapWalkError` | 地图导航问题 |
| `GameStuckError`, `GameBugError` | 游戏状态错误——触发重启 |
| `GameNotRunningError`, `GamePageUnknownError` | 连接/页面问题 |
| `RequestHumanTakeover` | **不可恢复**——需人工干预 |

异常只在顶层捕获，捕获后日志和截图保存到独立目录，用户信息会被清洗。

## 图像识别

- **固定分辨率**：1280×720 —— 所有资源文件和截图必须匹配
- **资源文件**（`assets/`）：按服务器（cn/en/jp/tw）和功能模块组织，以 Button 常量命名
- **Button 类**：`appear_on()`（平均颜色识别）或 `match()`（模板匹配）
- **Template 类**：必须用 `TEMPLATE_` 前缀命名
- **添加 Button 流程**：截图(1280×720) → 复制到 assets/ → PS 裁剪 → `button_extract.py`

## OCR

- **模型**：基于 PaddleOCR 定制训练
- **ocr 引擎**：`cnocr`（默认，中英）、`azur_lane`（游戏数字字母）、`jp`（日文）
- **OCR 类**：`Ocr`（通用）、`Digit`（返回 int）、`DigitCounter`（如 `14/15`）、`Duration`（如 `08:00:00`）
- **GPU 加速**：Windows 上用 DirectML，macOS 上用 ANE

## 调试

```python
# 调试按钮
az = SomeModule('alas', task='SomeTask')
az.image_file = r'path/to/screenshot.png'
print(az.appear(SOME_BUTTON))

# 调试其他服务器（在导入任何 ALAS 模块之前设置）
import module.config.server as server
server.server = 'en'
```

## Webapp（Electron 桌面应用）

- **技术栈**：Vue 3 + Ant Design Vue + Electron，pnpm + Vite + electron-builder
- **命令**：`pnpm lint`、`pnpm typecheck`、`pnpm test`（Playwright 测试）
- **构建**：`pnpm build && pnpm compile`
- **pre-push hook**：自动运行 typecheck
- **测试**：仅有一个 `webapp/tests/app.spec.js` Playwright 基础测试

## Docker

- `docker-compose.yml` 使用 `network_mode: host`，健康检查心跳在端口 22267
- Dockerfile 位于 `deploy/docker/Dockerfile`
- CI 在推送 `v*.*.*` tag 时自动构建并推送至 Docker Hub

## 注释规范

- Google 格式 docstring
- 中文注释（简体）
- 用 `Pages:` 标注函数进出时的游戏界面状态
- `logger.hr(title, level)` 标记阶段（0=脚本开始，1=功能开始，2=阶段开始，3=子阶段）
- `logger.attr(name, text)` 记录属性

## 测试

- **没有 Python 测试套件**——测试通过运行任务对接真实模拟器进行
- webapp 仅有一个 Playwright 测试，验证窗口创建等基本功能

## 性能

- ~99% 运行时在等待模拟器截图（~350ms）
- 图像处理 ~2.5ms，海图检测/OCR ~100-180ms
- 不需要过度优化 Python 代码

## 项目特有约定

- `handle_*()` 方法返回 `bool`：`True` 表示已操作游戏，需新截图
- `interval` 参数防连击，通常 2-5 秒
- 模块应可独立运行，不依赖 GUI 或用户配置
- 事件目录（`campaign/event_YYYYMMDD_xx/`）通过 `importlib.import_module()` 动态加载，map 文件为 YAML 格式
- 装饰器：`@Config.when(SERVER='en')` 条件分发、`@cached_property`、`@timer`、`@function_drop()`

---

## 资源历史趋势图（Resource History Tracking）

统计页面（`Gui.Overview.Stat`）现在支持展示所有 Dashboard 资源的**历史变化曲线**：石油、物资、钻石、活动Pt、魔方、核心数据、勋章、功勋、舰队币、行动力、黄币、紫币。

### 数据流向

```text
游戏运行 -> LogRes 记录资源值
              |
              v
  _record_all_resource_snapshot()
    -> 读取 12 个 Dashboard 资源当前值
    -> 写入 config/azurstats_local.db 的 resource_snapshots 表
              |
              v
  统计页面 -> get_resource_timeline()
    -> Canvas 折线图展示 12 条趋势线
    -> 图例切换、数值 tooltip、缩放/平移
```

### 相关文件

| 文件 | 用途 |
|---|---|
| `module/statistics/resource_stats.py` | **核心存储模块**。管理 `resource_snapshots` 表（SQLite），提供 `record_resource_snapshot()` 写入和 `get_resource_timeline()` 查询 |
| `module/log_res/log_res.py` | `LogRes.__setattr__()` 中增加 `_record_all_resource_snapshot()` 调用。任意资源变更时自动快照全部资源 |
| `module/statistics/opsi_month.py` | 导出 `get_resource_timeline()` 供 WebUI 使用 |
| `module/webui/app.py` | `alas_set_stat()` 中新增 `_render_resource_chart()`，在体力K线图下方渲染全资源趋势图，每 60 秒自动刷新 |
| `webapp/resource_chart.html` | 图表面板 HTML 模板（标题栏、统计行、图例、Canvas、缩放控件） |
| `webapp/resource_chart.js` | Canvas 图表渲染引擎——12 条折线、图例切换、十字线 tooltip、滚轮缩放、拖拽平移 |
| `dev_tools/snapshot_resources.py` | **手动强制记录快照脚本**（详见下方） |
| `dev_tools/seed_resource_snapshots.py` | **随机快照测试数据生成脚本**（详见下方） |

### 手动强制记录快照

`dev_tools/snapshot_resources.py` 可在任意时刻强制读取资源并记录快照。

```bash
# 模式 1：从配置缓存读取（离线可用，不连模拟器）
uv run python dev_tools/snapshot_resources.py

# 模式 2：从游戏截图 OCR 读取（需模拟器运行中，游戏在主界面）
uv run python dev_tools/snapshot_resources.py --ocr

# 指定实例（默认 alas）
uv run python dev_tools/snapshot_resources.py --instance=alas2

# 查看已记录的快照数量
uv run python dev_tools/snapshot_resources.py --count

# 查看最近几条快照的详细数值
uv run python dev_tools/snapshot_resources.py --recent
```

**模式 1** 读取 `config/Dashboard.*.Value` 中的缓存值（12 项资源全量），游戏未运行也能用。**模式 2** 连接模拟器截图，从当前屏幕 OCR 读取主界面可见的资源。

### 随机快照测试数据生成脚本

`dev_tools/seed_resource_snapshots.py` 向数据库插入模拟资源快照数据，用于测试趋势图表的渲染效果。每种资源有独立的基准值、趋势方向和波动幅度——石油下降、物资上升、钻石稳定、活动Pt脉冲变化等。

```bash
# 插入 120 条随机快照（默认 ~30 小时跨度，15 分钟间隔）
uv run python dev_tools/seed_resource_snapshots.py

# 插入 500 条，每 30 分钟一条（约 10 天跨度）
uv run python dev_tools/seed_resource_snapshots.py --count=500 --interval=30

# 8% 的空值概率测试断点修复
uv run python dev_tools/seed_resource_snapshots.py --gap-prob=0.08

# 先清空旧数据再插入新的
uv run python dev_tools/seed_resource_snapshots.py --clear --count=200

# 只打印预览，不写入数据库
uv run python dev_tools/seed_resource_snapshots.py --dry-run

# 指定实例（默认 alas）
uv run python dev_tools/seed_resource_snapshots.py --instance=alas2
```

数据生成完毕后刷新统计页面（或等待 60 秒自动刷新）即可看到效果。

### 快照触发机制

| 触发方式 | 时机 | 数据来源 | 说明 |
|---|---|---|---|
| **自动**（任务驱动） | 战斗结算、商店购买、委托收取、大世界调度 | 游戏截图 OCR / 逻辑计算 | 任务模块调用 `LogRes(self.config).Xxx = val` 时 `__setattr__` 自动触发全量快照 |
| **手动**（脚本） | `uv run python dev_tools/snapshot_resources.py` | 配置缓存或游戏截图 OCR | 随时手动记录一次快照 |
| **图表刷新** | 每 60 秒 | 数据库 | 统计页面自动拉取最新数据重新渲染 |

### 各任务读取资源值的具体时机

| 任务模块 | 资源 | 读取时机 | 代码位置 |
|---|---|---|---|
| **战斗结算** `campaign/` | Oil, Coin | 每场战斗结算后读取结算界面数值 | `module/campaign/campaign_base.py` |
| **商店购买** `shop/` | Coin, Gem, Medal, Merit, GuildCoin, Core | 购买成功后读取当前数值 | `module/shop/shop_status.py:39-104` |
| **建造** `gacha/` | Cube | 建造后读取魔方剩余数 | `module/gacha/gacha_reward.py:131, 346` |
| **大世界——行动力** `os_handler/` | Oil, ActionPoint | `get_action_point()` 通过 OCR 读取界面上的石油和行动力 | `module/os_handler/action_point.py:170-172` |
| **大世界——币种** `os_handler/` | YellowCoin, PurpleCoin | `record_coin()` 通过 OCR 读取大世界界面的黄币/紫币 | `module/os_handler/os_status.py:134, 144` |
| **活动 Pt** `raid/` | Pt | 活动关卡结算后读取 Pt 数值 | `module/raid/raid.py:447, 452` |

### 资源值记录数据流详解

```text
[游戏内数值变化]
       │
       ▼
[任务模块通过 OCR/逻辑获取数值]
       │  e.g. LogRes(self.config).Coin = 12345
       ▼
[LogRes.__setattr__()]
       ├── 更新 Dashboard.{Key}.Value 到 config
       ├── 更新 Dashboard.{Key}.Record 时间戳
       ├── 如果是 YellowCoin → 同时写入 cl1_db 黄币快照
       └── 调用 _record_all_resource_snapshot()
              │
              ▼
         [_record_all_resource_snapshot()]
              ├── 遍历 LogRes.groups 全部 12 项 Dashboard 资源
              ├── 从 config.data 读取每项的实际值
              └── 调用 record_resource_snapshot(instance, dict)
                     │
                     ▼
                [record_resource_snapshot()]
                     ├── INSERT INTO resource_snapshots (ts, oil, coin, ...)
                     └── 写入 config/azurstats_local.db
```

**关键点**：
- 每次任何 Dashboard 资源发生变化时，**所有 12 项资源**都会被同时记录一次快照（全量快照）
- 快照值来自 `config` 中的缓存值（即 `Dashboard.*.Value`），而非实时游戏截图
- 所以快照密度取决于各任务模块调用 `LogRes` 的频率——活动期间 Pt 频繁更新，空闲期只有大世界任务定期触发
- 如果游戏长期未运行，快照记录完全停止，图表显示最后一条快照后无新数据
