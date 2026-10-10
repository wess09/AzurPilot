# 外部桥接与开发工具（module/submodule / dev_tools / module/debug）

> fork 仓库形式的游戏脚本桥接（MAA/FGO）与 `dev_tools` 资源、生成、调参工具全家桶。

## 1. 模块概述

AzurPilot 的核心流程覆盖碧蓝航线，但两类需求被刻意放在核心之外：**其他游戏的自动化**（MAA 的明日方舟、AlasFpy 的 FGO）以独立 fork 仓库挂为 git submodule，按需动态加载；**开发期工具**（资源提取、数据提取、生成器、调试）则集中在 `dev_tools/`，其中多个是 CI 与资源管线的组成部分。`module/debug` 提供宝石收割的本地调试服务（需环境变量开启）。

把桥接做成 submodule 而非子目录依赖，是因为两者各有独立的上游与发版节奏；框架只在运行时探测它们是否存在（`config/` 下出现 `template-maa.json` 等模板即启用对应桥）。

## 2. 模块职责

### 负责

- **module/submodule**：外部桥接注册表（`MOD_DICT`：maa→AlasMaaBridge、fpy→AlasFpyBridge）、功能→模块映射（`MOD_FUNC_DICT`：MaaCopilot/FpyBattle/FpyBenchmark/FpyCall）、桥接模块的动态 import 与配置加载（`submodule.py` 的 `load_mod/load_config`）、多模块配置实例的识别（`config/template-*.json` 命名约定）。
- **dev_tools**：仓库的全部离线工具（36 个脚本，截至 2026-09）——资源提取、Lua 数据解析、收益统计、生成器、CI 检查、截图辅助。
- **module/debug**：`commission_debug` 与 `web_debug_server`（委托调试的本地 web 端点，仅在 `ALAS_DEBUG_SERVER=1` 时启动）。

### 不负责

- 桥接模块自身的任务逻辑——在 `submodule/AlasMaaBridge`、`submodule/AlasFpyBridge` 两个 fork 仓库内。
- 运行时的进程管理——[运行时服务](../webui/runtime.md)按功能名分发到这里的注册表。

## 3. 模块位置

```
module/submodule/
├── submodule.py       # load_mod/load_config：importlib 动态加载桥接仓库
└── utils.py           # MOD_DICT/MOD_FUNC_DICT 注册表、实例扫描、get_config_mod
dev_tools/             # 36 个工具脚本 + README.md（工具索引）
module/debug/
├── commission_debug.py
└── web_debug_server.py
submodule/             # git submodule 挂载点（AlasMaaBridge、AlasFpyBridge）
```

## 4. 核心入口

| 入口 | 用途 |
| --- | --- |
| `get_available_func()` | 12 个工具任务名（Daemon…EmulatorManager），[运行时服务](../webui/runtime.md)按名分发 |
| `get_available_mod()/get_available_mod_func()` | 已安装桥接与其功能集 |
| `list_mod_instance()/get_config_mod()` | 扫描 `config/*.json` 识别「哪个配置属于哪个桥」（文件名 `配置名-模块名.json` 约定） |
| `load_mod(name)` | importlib 加载桥接包（MAA 需 DLL 预加载） |
| `uv run -m dev_tools.<tool>` | 各工具以模块方式运行 |

## 6. 工作流程

### 任务分发到桥接

`alas.py` 上的任务方法（如 `MaaCopilot`）→ 运行时 `process_manager` 的四路分发（alas 主任务 / 单工具任务 / 整桥接模块 loop / 桥接单函数）→ `load_mod()` 动态导入对应 fork 仓库并执行。桥接缺失时前端不展示对应配置模板，不会报错。

### dev_tools 分类（详单见 `dev_tools/README.md` 与[目录与任务映射](../overview/directory-map.md)）

| 类别 | 代表工具 |
| --- | --- |
| 图像资源提取 | `button_extract`（按钮 → assets.py）、`relative_record*`（模板采集）、`word_template_extractor` |
| Lua 数据提取 | `map_extractor`、`os_extract`、`ship_exp_extract`、`ship_data_extractor`、`island_extractor`、`research_extractor`、`commission_value_table` |
| 离线调参 | `research_optimizer`、`coin_statistics`、`item_statistics` |
| 生成与 CI | `button_extract`、`export_api_schema`（同步前端契约）、`import_smoke_test`（导入冒烟 + KNOWN_FAILURES 白名单，白名单过期也算失败）、`ci_pr_report` |
| 截图辅助 | `coordinate_picker`、`button_region_editor`、`campaign_swipe`、`grids_debug`、`relative_crop` |
| 资源快照 | `snapshot_resources`、`seed_resource_snapshots`（共用普通总库，开发数据使用 `--config-dir` 临时目录） |
| 普通存储维护 | `business_storage`（迁移、只读检查、WAL 备份、单实例调度切片及统计导入导出），见 [普通业务数据存储](persistence.md) |
| 其他 | `ocr_ncnn_convert`（模型转换）、`war_archives_update`（档案活动登记）等 |

CI 会重新生成按钮、配置与 API 契约并检查 diff（见 [.github/workflows/ci.yml](../../../.github/workflows/ci.yml)），因此这些生成器不是可选工具而是交付链的一环。

## 16. 修改注意事项

- **注册表三件套要同步改**：新增桥接功能时 `MOD_DICT`、`MOD_FUNC_DICT` 与运行时四路分发（process_manager）必须一致，漏一处会「前端有按钮但进程不认识」。
- **配置实例的文件名约定**：`<配置名>-<模块名>.json` 后缀决定模块归属（`get_config_mod`），重命名配置文件会破坏绑定。
- **生成器产物勿手改**：`assets.py`、`args.json`、`config_generated.py`、`frontend/src/api/generated.ts` 等由这里维护（约束见 [AGENTS.md](../../../AGENTS.md) 的配置与生成章节）。
- **`import_smoke_test` 的 KNOWN_FAILURES 是双向门**：记录根因才能加入；模块修复后不移除会被判「过期白名单」失败。
- `requirements_updater.py` 已退化为 `raise SystemExit` 占位（依赖由 pyproject/uv 管理），不要再调用或恢复它。

## 17. 已知限制

- 桥接仓库是 fork submodule，克隆默认不初始化；未拉取时对应功能整体不可用（这是设计而非故障）。
- `module/debug` 的 web 端点无鉴权，仅限本地调试环境变量开启，不可暴露到公网。

## 20. 相关模块

- [运行时服务](../webui/runtime.md) —— `get_available_func()` 的消费方与四路分发
- [API 服务](../webui/api.md) —— `export_api_schema` 生成的契约来源
- [调度器](../entry/alas.md) —— 工具任务在 `alas.py` 上的同名入口
- [配置系统](../config.md) —— config_updater 与模板/实例的文件约定
