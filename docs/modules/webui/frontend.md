# 前端

远程页的 `src/remote/PairingPanel.tsx` 展示服务器生成的配对码与标准二维码（`src/remote/PairingQr.tsx`）。
`PairingQr` 将 128 位单次配对密钥编码为 `azurpilot://pair?secret=<secret>` 协议二维码并支持一键复制六码与链接；AFA 在原生网关完成配对与认证，见 [远程访问](remote-access.md)。

二维码使用相连的圆角模块与圆角定位框，保留四模块静区、32px 纯白内边距及深色码点；主题色只少量混入深色基底。等待配对时，`PairingScanGuide` 在操作区旁展示手机对准二维码、扫描与识别反馈的六秒循环示意。示意图使用二维码图标，不接收配对密钥，其识别反馈不表示实际配对成功；真实二维码保持静止。窄屏时示意移至下方，离开视口或切到后台时暂停；系统开启减少动态效果时保留静态取景画面。示意图只保留辅助阅读标签，不展示说明文字。

> React 控制台（frontend/）：React + TypeScript + Vite 实现的 WebUI，业务通信统一走 `/api/v1/ws`。详细界面设计与协议见 frontend/README.md 与 frontend/API.md。

## 1. 模块概述

[资源管理](resource-management.md) 位于「资源统计」内的「资源趋势」旁边，路径为 `/i/:instance/statistics?view=management`；旧 `/resources` 路径自动跳转。由 `pages/ResourceManagement.tsx` 与 `resources/` 提供 ECharts 桑基图、库存与收支明细。图节点支持资源与任务筛选，明细支持分页和完整区间 CSV 导出；原调度的石油自动控制使用现有配置事务接口保存。五种语言、窄屏和空数据状态均沿用控制台组件与主题。

「舰队管理」下并列放置「智能换船」与「舰船数据」。`pages/FleetSwitch.tsx` 在 `/i/:instance/task/FleetSwitch` 整合「舰队信息」「换船配置」「换船调度」「换船装备」四个页签，使用与舰船数据相同的分段按钮样式；查询参数 `tab=info|rotation|training|equipment` 记录当前页签，刷新后保持选择。原 `FleetInfo`、`FleetRotation`、`FleetTraining`、`FleetEquipment` 及等级/好感调度链接自动跳转到对应页签。侧栏树、悬浮菜单及顶栏任务跳转共用 `components/taskNavItems.ts`，只保留一个智能换船入口，不注册新的游戏任务，各页签继续使用原有配置路径与保存接口。原「自动换装备」页面显示名称改为「换船装备」，默认开关和装备码规则不变。

整合前的[四个菜单入口](images/fleet-switch-before.png)来自用户提供的界面截图；整合后的[桌面](images/fleet-switch-desktop.png)与[手机](images/fleet-switch-mobile.png)截图来自隔离模拟服务，仅验证界面展示和交互，不代表实际游戏验证。

「舰队信息」页签仍由 `pages/FleetInfoPage.tsx` 提供舰队卡片和扫描开关，调用 `tasks.run(FleetScan)`，只在该扫描运行时调用 `scheduler.stop`；其他任务运行、更新或连接不可用时禁用。启动前等待配置队列保存，再以最新修订保存 `FleetInfo.FleetInfo.UpdateEmotion`（扫描时更新心情）选项；关闭时保留已有舰位心情参考，不进行被动学习。扫描运行期间及结束后重读舰队信息，显示扫描确认的舰位，不为历史记录推断舰位。浏览页面不启动游戏，也不修改实例自启设置；手动指定舰位互换尚未提供独立按钮，智能换船使用下述策略页签。

舰队信息的[桌面截图](images/fleet-management-desktop.png)与[手机截图](images/fleet-management-mobile.png)
来自隔离服务及合成记录，只验证舰位、未知心情和扫描选项展示，不代表实际账号操作。

「智能换船」的 `/i/:instance/task/FleetSwitch?tab=rotation` 页签名为「换船配置」，继续独立保存配置，
不注册游戏任务，也不显示调度状态或启动任务按钮。六支水面
舰队的36个舰位默认均为“不变”，可逐位改为“换船”，并为每支目标队多选候补队。
此页只保存共享的 `FleetInfo.FleetRotation.Rules`，不修改三个调度的开关和心情计算选项，
不调用 `tasks.run`。页面显示已保存
的上次来源与本轮进度，任务运行时只刷新进度，不覆盖尚未保存的规则编辑。
清空轮换记录按钮仅在任务停止时可用，不清空培养完成记录。实际刷图触发由战役出击前策略负责。

同页的`/i/:instance/task/FleetSwitch?tab=training`「换船调度」集中展示心情、等级和好感三个独立开关，
默认均关闭，共享上述舰位及候补。原等级/好感页面链接自动跳转到此页。等级与好感分别保存目标；
页面上方只保留一个`FleetInfo.FleetTraining.CheckIntervalHours`共用小时实读间隔，三个卡片内不再重复。
支持小数、不设上限、默认0.5小时；旧独立间隔优先按启用项目的最短值迁移，都关闭时取已有最短值，
分钟先等值换成小时，已有共用值优先，页面读取不写盘。0仍表示每次结算检查，实际读取时机仍为当前地图完成后。
任一模式开启都在开始、换船后和共用间隔到期时实读舰名与心情，再核对已启用培养条件。
“仅计算更换舰船心情”放在此页，三种调度共用；不开启心情调度时，低心情只延时，不临时换船。
记录区按“培养舰船”“完成舰船”“旧记录舰船”分成三个独立大框，显示舰队、舰位、实际舰名、
最近记录心情、等级、经验、好感及核对时间。培养舰船取共享配置中勾选舰位的在队船，完成状态优先归入完成框；
其余未完成记录归旧记录。每框按实际舰队、舰位1–6向下排列；完成和旧记录各选最近6条展示，
完整持久记录不裁剪，也不影响已完成舰船的排除。当前编队快照提供最近确认的位置和心情，
快照中不在队的记录回退到保存的位置及心情；同名多艘不能归并培养进度，缺失值不猜测。
同名舰船可以展示`State.readings`中同舰队、同舰位且舰名一致的实读值，不能借用其他同名舰船的记录，
这些舰位读数不进入完成分类，也不作为自动完成或换船依据。
旧空字符串编队快照按尚未扫描处理，已有历史仍可展示，不要求额外启动扫描。
各项保留最近记录值、不表示即时值，未知经验及旧记录缺项显示“未读取”，真实0心情/经验正常显示。
窄屏仅在表格内部横向滚动，分类标题保持可见。
当前[统一调度与三类记录截图](images/fleet-scheduling-and-records-desktop.png)使用隔离模拟服务和合成数据。
运行时只刷新记录和编队快照，不覆盖未保存输入。页面不显示任务运行侧栏，不调用`tasks.run`，
不改写心智计算器状态。浏览器验证使用隔离模拟服务，真实模拟器未在本轮验收。

frontend/ 是 AzurPilot 的浏览器控制台，替代旧版 PyWebIO 界面，覆盖主页与实例导航、任务配置表单、总览日志与截图预览、统计图表、系统设置、远程访问与更新器。前端不包含任何游戏逻辑，所有业务操作都通过 WebSocket API 交给 [API 服务](api.md)执行。

frontend/README.md 与 frontend/API.md 已经是本前端的详细文档：前者覆盖界面行为、主题材质、启动开发与迁移边界，后者定义消息协议。本文不重复其内容，只作为模块文档体系的索引篇，说明目录分工、构建测试入口与生成产物红线。

注意：项目中的 **1280×720 是游戏截图识别的约束，不适用于 WebUI 布局**。前端按普通响应式网页开发，支持移动端折叠菜单，e2e 视口为 1440×1100。

移动端在 950px 及以下使用导航与调度抽屉。新版主题的调度栏必须使用固定定位，桌面 L 形容器中的相对定位仅限 951px 及以上，隐藏抽屉不得占用正文高度；看图模式把手也仅在桌面显示。新版首页在窄屏按公告、实例列表顺序单列排列，由首页内容区整体滚动。480px 及以下，新版总览的日志工具栏独占一行，避免覆盖日志与截图切换入口；统计表格搜索也另起一行，保留标题和导出操作的可读宽度。所有主题的统计分类在 950px 及以下统一使用下拉菜单，完整列出分类名称，不裁切横排标签；编辑模式的合并页面开关保留在下拉旁边。桌面仍使用分段分类栏，紧凑主题按可用宽度改用下拉。相关回归位于 `frontend/e2e/mobile/mock.spec.ts`，使用触摸移动视口检查正文可见性、滚动可达性、抽屉与桌面断点切换，运行 `npm run test:e2e:mock --prefix frontend -- e2e/mobile/mock.spec.ts`。

统计页各分类均保留历史展示与筛选，并提供导出入口：页面可导出本类数据，表格有各自的导出明细按钮，图表支持保存为图片。


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
├── src/components/StockExchangeBoundary.tsx # 股票接入页面的加载和错误兜底
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

茗交所入口为 `src/pages/StockExchange.tsx`，侧栏导航位于「资源统计」下方，沿用 AzurPilot 主题与布局。此页面只负责实例股票告知确认/用户名注册、群内绑定命令、删除状态及本地恢复计划，注册并绑定后新标签页打开 `https://stock.azurpilot.com`。交易、教程、行情与登录均在独立站点，旧 `src/stock/` 目录及交易代理已删除。`src/components/StockExchangeBoundary.tsx` 提供加载与渲染错误兜底。Mock 完全本地，不再依赖交易所或验证码网络。详情见 [前端 README](../../../frontend/README.md#茗喵证券交易所)。

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
- 模拟统计报告的逐点序列同真实接口使用 `{t, v, s?}`，时间为微秒整数；通过前端 `normalizeReport` 还原后再渲染，避免旧 `{time, value}` 夹具导致日期与指标显示 NaN。
- e2e 失败先看截图输出在被 git 忽略的 `frontend/test-results/`；先确认跑的是哪套配置（主配置连临时 Python 后端，mock 配置连内存模拟服务）。
- 类型报错疑似与后端契约不一致时，先重跑 `dev_tools.export_api_schema`，再排查是否有人手改了生成产物。

## 20. 相关模块

- [舰队科技列表](fleet-technology.md) —— Lua 目录、累计扫描证据、人工校正和阵营加成。

- [WebUI 总览](index.md)
- [API 服务](api.md) —— 协议、认证与路由，前端所有业务通信的对端
- [配置系统](../config.md) —— args.json、menu.json 与翻译文件的来源
- [外部桥接与开发工具](../infra/submodule-tools.md) —— dev_tools.export_api_schema 所在的开发工具层
