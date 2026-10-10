# 前端

> React 控制台（frontend/）：React + TypeScript + Vite 实现的 WebUI，业务通信统一走 `/api/v1/ws`。详细界面设计与协议见 frontend/README.md 与 frontend/API.md。

## 1. 模块概述

[资源管理](resource-management.md) 位于「资源统计」内的「资源趋势」旁边，路径为 `/i/:instance/statistics?view=management`；旧 `/resources` 路径自动跳转。由 `pages/ResourceManagement.tsx` 与 `resources/` 提供 ECharts 桑基图、库存与收支明细。图节点支持资源与任务筛选，明细支持分页和完整区间 CSV 导出；原调度的石油自动控制使用现有配置事务接口保存。五种语言、窄屏和空数据状态均沿用控制台组件与主题。

「舰队管理」下并列放置「舰队信息」与 [心智单元计算器](mind-calculator.md)。计算器路径为 `/i/:instance/task/MindCalculator`，旧 `/mind-calculator` 自动跳转；沿用 `components/taskNavItems.ts` 的 WebUI 页面导航机制，同时覆盖侧栏树、悬浮菜单及顶栏任务跳转，不注册新的游戏任务。「舰队信息」由 `pages/FleetInfoPage.tsx` 提供舰队卡片和扫描开关，调用 `tasks.run(FleetScan)`，只在该扫描运行时调用 `scheduler.stop`；其他任务运行、更新或连接不可用时禁用。启动前等待配置队列保存，扫描运行期间及结束后重读舰队信息；浏览页面不启动游戏，也不修改实例自启设置。

frontend/ 是 AzurPilot 的浏览器控制台，替代旧版 PyWebIO 界面，覆盖主页与实例导航、任务配置表单、总览日志与截图预览、统计图表、系统设置、远程访问与更新器。前端不包含任何游戏逻辑，所有业务操作都通过 WebSocket API 交给 [API 服务](api.md)执行。

frontend/README.md 与 frontend/API.md 已经是本前端的详细文档：前者覆盖界面行为、主题材质、启动开发与迁移边界，后者定义消息协议。本文不重复其内容，只作为模块文档体系的索引篇，说明目录分工、构建测试入口与生成产物红线。

注意：项目中的 **1280×720 是游戏截图识别的约束，不适用于 WebUI 布局**。前端按普通响应式网页开发，支持移动端折叠菜单，e2e 视口为 1440×1100。

统计页各分类均保留历史展示与筛选，并提供导出入口：页面可导出本类数据，表格有各自的导出明细按钮，图表支持保存为图片。

茗喵证券交易所的注册和登录使用 `src/stock/Captcha.tsx` 与 `recaptcha.ts` 中的 Google reCAPTCHA v2，脚本及验证 iframe 统一走 `www.recaptcha.net`，官方静态依赖使用 `www.gstatic.com/recaptcha/`。认证请求字段为 `recaptchaToken`；私密密钥由 Go 交易所环境变量 `RECAPTCHA_SECRET_KEY` 读取。站点停用域名验证，Go 不匹配 hostname 或 action。切换注册/登录时立即清空 token，提交后重置，组件卸载后忽略延迟回调；前端与 Go 服务须同步升级。

## 2. 模块职责

### 负责

- 渲染单页应用（hash 路由）：主页、实例总览、任务配置、统计、系统设置、更新器等页面
- WebSocket 连接管理：认证、心跳、请求关联、超时与重连（`src/api/client.ts`）
- 配置表单展示与保存：字段保存队列、草稿恢复、重试与数值校验（`src/config/EditQueue.ts`）
- 任务优先级字段的拖动排序与解析：`src/app/taskPriority.ts`（纯函数：解析/合并/移动）+ `src/components/TaskPriorityField.tsx`（拖拽交互），写入 `Scheduler_Scheduler_Tasks`，提交值用 `
> ` 分隔（注释行与全角箭头已兼容归一）
- 主题、语言、背景等浏览器侧偏好的保存与应用（localStorage / IndexedDB）
- 日志面板在数据进入 React state 前只保留最近 1000 条，作为后端环形缓冲之外的独立防线，避免异常历史 payload 在 WebView2 中生成超大 DOM
- 独立 mock 服务（`mock/`），无需 Python、ADB 或模拟器即可开发验证前端交互

### 不负责

- API 协议、认证会话与业务适配：在 `module/api`，见 [API 服务](api.md)
- 进程、OCR、更新与认证等运行时服务：在 `module/runtime`，见 [WebUI 总览](index.md)
- 游戏配置定义与翻译生成：在 `module/config/`，见 [配置系统](../config.md)
- 真实运行与完整业务校验：mock 服务只验证前端交互，安全策略以 Python API 测试为准

## 3. 模块位置

```text
frontend/
├── src/main.tsx              # 应用入口：hash 路由表、错误兜底、先加载主题再挂载
├── src/api/                  # client.ts 连接层；generated.ts 与 contract.json 为生成产物
├── src/app/                  # 布局、主题系统（theme.ts 按需加载）、连接上下文、任务优先级解析（taskPriority.ts）、各类偏好
├── src/pages/                # 页面：Home / Overview / TaskConfig / Statistics / Settings / Updater 等
├── src/stock/                # 茗喵证券交易终端、开户登录、身份信息与行情图表
├── src/components/           # 可复用组件：FormControls、LogPanel、StatisticsChart、TaskPriorityField（任务优先级拖动排序）、实例切换等
├── src/config/               # EditQueue 跨页面字段保存队列、草稿恢复、输入校验
├── src/styles/               # 设计变量与界面样式（apple / forms / compact / minimal 等 css）
├── src/i18n.ts               # 控制台固定文案（五种语言），独立于游戏翻译 module/config/i18n
├── e2e/                      # Playwright 浏览器测试
├── mock/                     # 内存模拟服务（server.mjs、state.mjs）及其测试
├── playwright.config.ts      # e2e 主配置：连接 tests/serve_frontend.py 临时后端
├── playwright.mock.config.ts # e2e mock 配置：连接独立 mock server 与 Vite mock 模式
└── vite.config.ts            # 开发代理与相对构建（base: './'）
```

更细的文件级职责表见 frontend/README.md「目录职责」。

## 4. 核心入口

追代码从 `src/main.tsx` 开始：hash 路由表、顶层 ErrorBoundary 与主题加载流程都在这里。

茗交所入口为 `src/pages/StockExchange.tsx`，实例侧栏的「茗喵证券交易所」导航位于「资源统计」下方，由 `src/app/App.tsx` 提供；移动端从导航抽屉进入。交易终端独立顶栏固定在窗口顶部，返回总览位于用户名左侧，与用户入口、亮暗主题按钮同排；窄屏下用户名截断。`src/stock/OverviewLink.tsx` 统一提供返回链接和应用初始化、代码加载、渲染异常的居中兜底页；状态、行情加载和错误页也始终提供屏幕中间的返回入口。开户、登录弹窗的返回入口水平居中。玩家数据错误由入口页承接，包含完全重建本地账户的范围预览和确认；实例配置管理不会展示交易身份错误。`src/stock/theme.tsx` 管理独立主题，默认暗色，通过 `localStorage` 的 `azurpilot.stock-theme` 记住本机选择，不跟随 WebUI 或系统主题；`src/stock/theme.css` 定义亮色语义配色，图表和验证码使用同一主题上下文，全屏图表的 Portal 显式携带主题属性。切换保留页面、表单与图表缩放范围；交互与联调方式见 [前端 README「茗喵证券交易所」](../../../frontend/README.md#茗喵证券交易所)。

行情涨跌幅统一以 `stock.open`（上海时间今日第一条已保存的行动力报价）为基准，市场列表、排序、滚动行情与证券详情保持一致；补传或修正会更新开盘价，跨日重新取值，当日无报价或开盘价为 0 时显示 `—`，切换历史图表不会改用历史开盘价。总行动力低于控制台阈值（默认 500 点）时，每月 5 日起且开赛后本月强制退市：相关挂单撤销、多空持仓按触发报价结算，次月重新判断。股票退市不影响玩家登录、后台上传、排行或交易其他股票；界面显示退市状态并禁止该股票的委托。

茗交所 Mock 还需单独启动相邻交易所仓库的 Go Mock 服务，本仓库 `dev:mock` 只提供模拟 API 与 Vite。代理将上游连接失败归为 `STOCK_UNAVAILABLE` 并提示启动方式，无效 JSON 或响应时间归为 `STOCK_INVALID_RESPONSE`，不再误报为浏览器请求格式错误；修复上游后可在交易页面重试连接。

| 入口 | 用途 |
| --- | --- |
| `npm run dev --prefix frontend` | 开发服务器（5173），代理到真实后端 |
| `npm run dev:mock --prefix frontend` | 同时启动 Vite 与 mock server（默认 22392），纯前端开发 |
| `npm run build --prefix frontend` | `tsc -b` 类型检查 + Vite 生产构建，产物在 `dist/` |
| `npm run typecheck --prefix frontend` | 仅 `tsc -b` 类型检查 |
| `npm test --prefix frontend` | vitest 单元测试（client、组件与纯函数） |
| `npm run test:e2e --prefix frontend` | Playwright e2e，主配置 |
| `npm run test:e2e:mock --prefix frontend` | Playwright e2e，mock 配置 |

Node.js >= 22.12（推荐 24），首次准备用 `npm ci --prefix frontend`。

两个 e2e 配置的区别：主配置在仓库根目录以 `uv run python -m tests.serve_frontend` 起服务——它使用临时配置目录、拒绝执行真实游戏任务（替换 `runtime.start/stop` 与 `updater.fetch/apply/cancel`），连接真实 Python API 跑除 `mock.spec.ts` 外的全部用例；mock 配置只跑 `mock.spec.ts`，同时拉起 mock server（22492）与 Vite mock 模式（5174），完全不需要 Python 与模拟器。

## 6. 工作流程

- 开发联调：`uv run python gui.py` 起后端（默认端口见 config/deploy.yaml 的 `WebuiPort`），另开 `npm run dev`，Vite 将 `/api`（含 WebSocket）与 `/healthz` 代理到后端，`AZURPILOT_BACKEND` 可换目标；代理保留 Host，浏览器来源校验仍然有效。
- 纯前端开发：`npm run dev:mock`，模拟服务只读公开的 args.json、menu.json、翻译与 template.json，所有数据在内存，重启即重置。
- 构建部署：`npm run build` 产出 `dist/`。gui.py 启动时检查前端源码摘要，缺产物或源码变化时自动执行 `npm ci` 与构建；Docker 多阶段构建预装静态产物。
- 构建使用相对 base（`base: './'`）：远程访问经 `/<peer_id>/` 前缀式反代加载，绝对路径会 404。

## 16. 修改注意事项

- **生成产物红线**：`src/api/generated.ts` 与 `src/api/contract.json` 由 `uv run python -m dev_tools.export_api_schema` 生成，禁止手改；CI 会重新生成并用 `git diff --exit-code` 校验。新增 API 方法的顺序：先定义后端参数模型与路由，再运行生成器，然后更新 `src/api/types.ts` 响应类型与对应测试；不得通过方法名反射任意 Python 属性。
- **`base: './'` 不能改回绝对路径**：这是远程访问反代的硬性要求，且配套要求 deploy.yaml 的 `RemoteAccessMode` 为 ssh。
- **不要在 React 中重复登记游戏配置**：配置表单直接读取后端生成的 args.json、menu.json 与翻译文件；新增任务或参数只需改 `module/config/` 并重新生成。
- 新增选择器使用 `FormControls.tsx` 的 `Select`，配置字段使用 `FieldInput`，不要在各页面单独绘制箭头、勾选等图标。
- 控制台固定文案在 `src/i18n.ts`（五种语言）；游戏任务配置的名称与说明翻译在 `module/config/i18n/`，二者独立，别改错位置。
- 主题与背景偏好只存浏览器（localStorage / IndexedDB），不写入服务端部署配置；上传背景保存在 IndexedDB（最大 200 MB）。

## 19. 调试方法

- 界面交互问题先用 mock 模式复现（无需 Python 与模拟器）；`AZURPILOT_MOCK_SCENARIO=empty` 从零实例测首次创建，`AZURPILOT_MOCK_PASSWORD` 可测登录与重连。
- e2e 失败先看截图输出在被 git 忽略的 `frontend/test-results/`；先确认跑的是哪套配置（主配置连临时 Python 后端，mock 配置连内存模拟服务）。
- 类型报错疑似与后端契约不一致时，先重跑 `dev_tools.export_api_schema`，再排查是否有人手改了生成产物。

## 20. 相关模块

- [WebUI 总览](index.md)
- [API 服务](api.md) —— 协议、认证与路由，前端所有业务通信的对端
- [配置系统](../config.md) —— args.json、menu.json 与翻译文件的来源
- [外部桥接与开发工具](../infra/submodule-tools.md) —— dev_tools.export_api_schema 所在的开发工具层
