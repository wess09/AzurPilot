# 测试体系（tests/ + frontend 测试 + e2e）

> 三层测试的边界与入口：Python 单元测试、前端单元测试、浏览器端到端测试（真实后端 / 纯 mock 各一套）。

## 1. 模块概述

测试的目标分层与风险对应：Python 层验证调度、配置、API 协议与运行时的**真实行为**（起真实 ASGI 应用，只是用临时配置目录、不碰模拟器）；前端单元测试验证状态机制的**逻辑分支**（vitest，jsdom）；e2e 验证**界面交互链路**，分两套——主配置连真实 Python API（但禁止真实游戏进程），mock 配置连内存模拟服务（不需要 Python）。

一个贯穿原则：**测试永远不执行真实游戏任务**。主配置 e2e 通过替换 `runtime.start/stop` 与 updater 方法把危险操作变成显式拒绝，见下文。

## 2. 模块职责

### 负责

- **tests/**（Python）：70+ 个 unittest 模块，覆盖 API 协议与生命周期、配置事务与批量写、调度器恢复与停机、进程管理、设备重试、MCP 工具与认证、各游戏功能的纯逻辑（委托结算、商店策略、行动力面板数值等）与离线图像用例。
- **frontend/src/**/*.test.ts(x)**：vitest 单元测试（连接层、EditQueue、主题、各组件逻辑）。
- **frontend/e2e/**：Playwright 用例（配置编辑、控制台、表单、主题、远程访问、生产样式、mock）。
- **frontend/mock/**：内存模拟服务（`server.mjs`/`state.mjs`），e2e mock 配置与 `npm run dev:mock` 共用。
- **tests/serve_frontend.py**：e2e 主配置的专用后端（临时配置 + 危险操作替换）。

### 不负责

- 游戏识别的准确性验证——截图资源驱动的识别改动用已有截图离线人工比对（见 AGENTS.md），不进自动化测试。
- 真机/实机模拟器联调——属用户授权的实测范畴。

`tests.test_persistence` 和 `tests.test_persistence_migration` 覆盖 v1 STRICT 表、类型化值、部分快照、只读旧源、崩溃重试、WAL 备份及单实例切片。全量测试可设置 `AZURPILOT_CONFIG_DIR` 为临时目录，使无显式目录的普通存储也保持隔离；对应业务测试仍使用各自临时夹具与模拟服务，不连接真实账号。

## 3. 模块位置

```
tests/
├── serve_frontend.py       # e2e 专用服务：临时配置 + 禁真实任务/更新
├── test_api*.py            # API 协议、生命周期、MCP 集成（真实 create_app + 临时配置）
├── test_config_*.py        # 配置事务、批量写、迁移
├── test_process_manager.py 等   # runtime 进程与事件
├── test_scheduler_*.py     # 调度恢复、停机
├── test_handover_*.py 等   # 各游戏功能的可离线逻辑
├── meowfficer/ shop_event/ # 图像夹具（离线识别用例）
└── __init__.py
frontend/
├── src/**/*.test.ts        # vitest 单元测试
├── e2e/*.spec.ts           # Playwright（主配置跑除 mock.spec 外全部）
├── mock/                   # 内存模拟服务及其测试
├── playwright.config.ts    # 主配置：连 tests/serve_frontend.py
└── playwright.mock.config.ts   # mock 配置：连 mock server + Vite mock 模式
```

## 4. 核心入口

| 命令 | 层 | 说明 |
| --- | --- | --- |
| `uv run python -m unittest tests.test_api` | Python | 单模块（unittest） |
| `uv run python -m unittest discover -s tests` | Python | 全量 unittest |
| `uv run pytest tests/shop_event` | Python | pytest 用例（shop_event 图像夹具等） |
| `npm test --prefix frontend` | 前端单元 | vitest |
| `npm run test:e2e --prefix frontend` | e2e 主配置 | 需先有最新前端构建 |
| `npm run test:e2e:mock --prefix frontend` | e2e mock | 不需要 Python/模拟器 |

## 6. 工作流程

### e2e 主配置的安全边界（tests/serve_frontend.py）

```
临时目录 → fixture() 造配置 → 拷贝 frontend/dist → create_app(password='', manage_runtime=False, mount_mcp=False)
  → runtime.start = runtime.stop = raise ApiError('TEST_ENVIRONMENT')   # 拒绝执行游戏任务
  → updater.fetch/apply/cancel 三个方法整体替换为拒绝                     # 禁真实更新
  → statistics.report 换成空点数实现
```

浏览器由此拿到真实协议行为，而任何「启动实例」「更新程序」点击都会得到显式错误而非真实执行。用例若新增了危险方法，需在此同步替换，否则会真实执行。

### 两套 e2e 的分工

- **主配置**：连接真实 Python API（Starlette 起在临时配置上），验证协议、认证、表单保存全链路；跑 `e2e/` 下除 `mock.spec.ts` 与 `stock-exchange/` 之外的用例。
- **mock 配置**：`npm run mock`（22492）+ Vite mock 模式（5174），`state.mjs` 全内存，`AZURPILOT_MOCK_SCENARIO=empty` 可测零实例首启，`AZURPILOT_MOCK_PASSWORD` 测登录；只跑 `mock.spec.ts`。界面交互的快速迭代用这套。
- **stock 配置**：`npm run test:e2e:stock`，只跑 `stock-exchange/`；交易所 mock 由该配置自行启动，需相邻 `../AzurPilot_StockExchange` 仓库，见 [前端 README](../../../frontend/README.md)。

### Python 测试的隔离手法

API 类测试用 `fixture(directory)` 在临时目录造完整配置树，`create_app(..., manage_runtime=False)` 关掉真实进程管理；需要进程行为的测试（process_manager、webui_lifecycle）用真实子进程但以假任务体运行。图像类测试读 `tests/` 内置夹具截图，不连设备。

## 11. 异常与错误处理

- e2e 失败产物（截图、trace）在 `frontend/test-results/`（git 忽略）。
- 主配置 e2e 前置条件是**最新的前端构建**——`dist/` 过期会造成「测的是旧界面」的假失败。
- `reuseExistingServer: false`：两套 e2e 都拒绝复用已占端口的服务，避免测到旧进程。

## 16. 修改注意事项

- **新增危险 API 方法时同步改 `serve_frontend.py` 的替换表**，否则主配置 e2e 会真实执行它。
- Python 测试不要写死用户目录；配置一律经 `fixture()` 临时目录（`AzurLaneConfig` 初始化会保存配置）。
- 前端单元测试聚焦纯逻辑（队列、状态机、格式化）；需要后端契约的类型走 e2e 或 mock。
- CI 侧的生成产物校验（按钮/配置/API 契约 diff）不属于本目录，见[外部桥接与开发工具](submodule-tools.md)。

## 17. 已知限制

- mock 服务只验证前端交互；安全策略（认证、来源校验）以 Python API 测试为准。
- e2e 视口固定 1440×1100，移动端布局依赖开发期人工验证。

## 20. 相关模块

- [前端](../webui/frontend.md) —— 被测对象的实现说明
- [API 服务](../webui/api.md) —— 协议语义与认证
- [运行时服务](../webui/runtime.md) —— `manage_runtime` 与进程管理的边界
- [部署与启动链路](deploy.md) —— gui.py 依赖同步与 e2e 无关，但 `serve_frontend` 复用其 uv 环境
