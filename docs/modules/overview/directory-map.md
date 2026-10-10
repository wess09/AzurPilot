# 目录与任务映射

> 仓库目录速查表，以及「alas.py 任务方法 → 模块」的惰性导入映射规则。

## 1. 模块概述

本篇是导航页：不解释机制，只回答「这段功能在哪个目录」。所有目录的行为细节见对应模块文档（见 [docs/modules/README.md](../README.md) 索引）。

仓库顶层：

| 路径 | 说明 |
| --- | --- |
| `alas.py` | 调度器入口：任务循环、错误恢复、约 136 个任务方法（截至 2026-09） |
| `gui.py` | WebUI 启动器（uvicorn + 进程监督），见[WebUI 启动器](../entry/gui.md) |
| `mcp_server_sse.py` | 独立 MCP SSE 服务器，见 [MCP SSE 服务器](../entry/mcp-server.md) |
| `module/` | 全部实现代码（见下表） |
| `campaign/` | 玩家编写的活动/主线地图定义（Python 地图与战斗策略） |
| `assets/` | 四服按钮与模板资源（生成产物为主） |
| `module/config/` | 配置定义与生成器（见[配置系统](../config.md)） |
| `deploy/` | 安装/启动/前端构建辅助 |
| `frontend/` | React + TypeScript + Vite 控制台 |
| `dev_tools/` | 开发与生成工具（见[外部桥接与开发工具](../infra/submodule-tools.md)） |
| `submodule/` | git submodule 挂载点（MAA / FGO 桥接 fork） |
| `bin/` | 平台依赖的二进制（OCR 模型等） |
| `tests/` | Python 单元测试 |
| `docs/` | 参考文档（`docs/modules/` 为本体系） |

## 2. module/ 目录分类表

| 分类 | 目录 | 一句话 |
| --- | --- | --- |
| 入口 | （仓库根 `alas.py`/`gui.py`/`mcp_server_sse.py`） | 调度器、WebUI 启动器、MCP 服务器 |
| 基础层 | `module/base` | ModuleBase、Button/Template、Timer/Filter、资源释放 |
| 设备 | `module/device` | 模拟器连接、截图方法、控制方法（minitouch 等） |
| 配置 | `module/config` | 参数定义、生成器、事务与热重载 |
| UI/OCR | `module/ui`、`module/ocr` | 页面图导航与控件、OCR 模型与封装 |
| 处理器 | `module/handler` | 弹窗、登录、信息栏、委托、退役等通用处理 |
| 战斗/地图 | `module/combat`、`module/map`、`module/map_detection` | 战斗循环、棋盘感知与决策 |
| 战役 | `module/campaign` | 关卡选择、进图、`CampaignRun` 与大世界入口聚合 |
| 大世界系 | `module/os`、`module/os_handler`、`module/os_ash`、`module/os_combat`、`module/os_shop`、`module/os_simulator` | 大世界核心与辅助包 |
| 游戏功能 | `module/research`、`commission`、`reward`、`daily`、`exercise`、`gacha`、`hard`、`sos`、`war_archives`、`raid`、`event`、`event_hospital`、`coalition`、`eventstory`、`private_quarters`、`shipyard`、`freebies`、`minigame`、`awaken`、`shop`、`storage`、`retire`、`equipment`、`dock` 等 | 各玩法任务（见[日常维护合集](../game/daily-maintenance.md)、[其他游戏功能](../game/misc.md)） |
| 岛屿系 | `module/island` | 岛屿季度玩法 |
| 持久化 | `module/persistence` | 共享 SQLite 总库、原生编解码、只读旧源迁移与恢复 |
| 统计 | `module/statistics` | 掉落/收益统计与 azurstat 提交 |
| 通知 | `module/notify`、`module/llm.py`、`module/logger.py` | 推送、LLM 错误分析、日志 |
| WebUI | `module/api`、`module/runtime` | WebSocket API v1、进程管理与运行服务 |
| 桥接 | `module/submodule`（+ `submodule/` git 子模块） | MAA/FGO 桥接加载 |
| 调试 | `module/debug` | 委托调试与本地调试 web 服务 |

## 4. 任务方法 → 模块的映射规则

`alas.py` 的任务方法全部是**两行惰性导入 + 调用**，按方法名对应模块与类：

| 任务方法 | 实际导入 | 说明 |
| --- | --- | --- |
| `main()` | `module.campaign.run.CampaignRun` | 主线战役 |
| `opsi_scheduling()` 等 18 个 `opsi_*` | `module.campaign.os_run.OSCampaignRun` | 大世界入口聚合 |
| `island_farm()` 等 18 个 `island*` | `module.island.island_farm.IslandFarm` 等 | 岛屿任务直连（不经 run 层） |
| `reward` / `commission` / `research` | `module.reward.reward.Reward` 等 | 日常收菜类 |
| `Daemon` / `Benchmark` 等工具 | `module.daemon.*` / `module.submodule.utils` 注册表 | 工具任务 |

规则总结：**调度器只认识任务名字符串**；`task.yaml` 定义任务 → `alas.py` 提供同名方法 → 方法内部 import 真实实现。新增任务时三处同名（task.yaml、alas.py 方法、模块类）即可被调度、被 API 触发。因此「找任务实现」的最快路径是 `grep "def <task>" alas.py`，顺着 import 读到实现类。

## 16. 修改注意事项

- 调度优先级链：`alas.get_next_task()` 按 `Scheduler.NextRun` 挑选最早任务 → `run()` 惰性导入 → 异常按 recoverable 语义恢复（详见[调度器](../entry/alas.md)）。
- 任务数量用「约」表述：`alas.py` 上的任务方法随活动增删频繁，不要在别处写死精确数字。
- 新增顶层目录时同步本表与 [README.md](../../../README.md)。

## 20. 相关模块

- [编码规范与设计模式](conventions.md) —— 横切模式与命名约定
- [调度器](../entry/alas.md) —— 任务派发细节
- [模块文档索引](../README.md) —— 按主题检索全部模块文档
