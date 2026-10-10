# 前端状态机制（保存队列与连接状态）

> React 控制台的两条核心状态链：跨页面字段保存队列（EditQueue）的合并与竞态语义，以及 WebSocket 连接状态的迁移与恢复。

## 1. 模块概述

[前端](frontend.md)的界面行为在 frontend/README.md 中有完整说明，但两条状态链的实现语义只在源码里：**配置怎么从键盘变成服务端配置**，以及**连接断了之后 everything 怎么续**。这两条链的共同设计约束是：WebUI 按 7×24 运行，浏览器标签页可能随时刷新、断网、多开，任何一条链都不能因为时序问题丢输入或用旧值覆盖新值。

- **保存队列**（`src/config/EditQueue.ts`，约 184 行 + `src/config/editors.ts` 的作用域层）：字段输入不立即提交整个表单，而是进入按字段为单位的队列逐条发送；草稿持久化在 sessionStorage，刷新/重连后恢复重发。
- **连接层**（`src/api/client.ts`，约 124 行）：单例 `ApiClient` 管理 WebSocket、认证、心跳、请求超时与指数退避重连；连接状态四档 `connecting / auth / ready / offline` 驱动全局 UI。

两层的交汇点是 `resumeEditors()`：连接恢复 `ready` 时，扫描 sessionStorage 里所有作用域的队列草稿并重试——**不依赖当前显示哪个页面**。

## 2. 模块职责

### 负责

- 字段级保存队列：排队、逐条提交、已保存静默期、错误重试（可重试/永久二分）、草稿持久化与恢复。
- 队列作用域管理：`deploy`、`startup:<instance>`、`config:<instance>` 三类作用域各自独立队列；按实例隔离。
- 竞态防护：旧响应不覆盖新输入、配置读取不清理读取期间的新修改；保存成功时经 `onSaved` 回调把服务端回传的整份配置交给页面替换本地副本（序号校验通过才回调，避免旧响应覆盖新输入）。
- 连接生命周期：连接 URL 跟随 `document.baseURI`（远程反代前缀）、会话认证、心跳保活、断线重连与 pending 请求的失败语义。
- 远程访问状态的界面归并（`src/app/remoteStatus.ts`：后端状态串 → disabled/starting/ready/failed 四档）。

### 不负责

- 协议语义与后端处理——见 [API 服务](api.md)。
- 游戏配置的默认值与校验定义——字段 `validate`/`preserve_empty` 来自后端 schema（见 [配置系统](../config.md)）。
- 主题/语言等纯浏览器偏好——见 frontend/README.md。

## 3. 模块位置

```
frontend/src/config/
├── EditQueue.ts        # 队列本体：Edit 状态机、drain、reconcile、草稿持久化
├── EditQueue.test.ts   # 竞态语义的规格化测试（vitest，语义即用例名）
└── editors.ts          # editor(scope)：按作用域缓存队列、映射 API 方法、resumeEditors
frontend/src/api/client.ts   # ApiClient 单例：连接、认证、心跳、重连、请求超时
frontend/src/app/context.tsx # connection 状态 → resumeEditors() 触发点
frontend/src/app/remoteStatus.ts  # 远程隧道状态四档归并
```

## 4. 核心入口

| 入口 | 用途 |
| --- | --- |
| `editor(scope)` | 取某作用域的队列（无则创建）；scope 决定 API 方法 |
| `queue.change(path, value, payload?, error?)` | 字段输入入口：入队 + 触发 flush |
| `queue.settled()` | 运行工具前等候队列排空；有未保存项则抛错（不允许带旧配置启动） |
| `queue.onSaved = callback` | 页面订阅保存成功事件：回调拿到服务端回传的整份配置并替换本地副本 |
| `queue.confirmed()` / `queue.reconcile(confirmed)` | 配置读取后回传已确认 sequence，队列据此清理可清的本地态 |
| `resumeEditors()` | 连接 ready 后恢复所有作用域的草稿队列 |
| `api.request(method, params)` | 业务请求；连接未就绪时直接拒绝 `DISCONNECTED` |

## 5. 核心组件

### Edit 的状态机

```
queued ──drain 取最旧──▶ saving ──成功──▶ saved（readyAt 起算静默期）
   ▲                        │
   │ retry                  └──失败──▶ error(retryable?) ──自动/手动 retry──▶ queued
   └──────────────────────────────────────────────────────────────────────┘
```

- 每条 Edit 带**单调递增 `sequence`**，是全部竞态判断的锚点。
- 错误分两类：`INVALID_PARAMS / READ_ONLY / NOT_FOUND / CONFIG_INVALID` 为**永久错误**（不重试，等用户改）；其余可重试，按 1s 起指数退避到 15s 上限自动重试。
- `saved` 有两段显示时序：提交成功后 700ms 静默期（避免打字过程中「已保存」反复闪），再显示最短 800ms 后从队列移除。

### 队列与作用域

`editors.ts` 的 `queues: Map<string, EditQueue>` 按 scope 缓存队列，同一实例的所有页面共享一个队列（跨页面字段队列）。scope 到 API 的映射：

| scope | API | 说明 |
| --- | --- | --- |
| `deploy` | `settings.patch` | 部署设置 |
| `startup:<instance>` | `startup.set` | 实例启动开关 |
| `config:<instance>` | `config.patch` | 任务配置（instance 取自路由参数） |

实例切换即切换 scope——两个实例的队列互不可见，草稿也按 scope 分别持久化（`azurpilot.edits.<scope>` 键）。

### 输入框两值分离与清空回落默认值

`prepareValue` 把「原始文本」与「提交值」分离：负号、小数点是合法的输入中间态，不触发提交错误；文本框（单行输入、多行自适应文本 AutoTextarea、密码框等）、时间或数值内容被全部清空时，按旧版本逻辑自动还原为参数默认设置并改写输入框回显，便于误删除后查看和后续修改（与后端 `config_update()` 的空值还原一致）。`preserve_empty` 字段例外——空值本身有意义，照旧提交。

文本／数值输入先在 `useDraftInput` 保留草稿，失焦或回车后才进入保存队列。心情的 `Fleet1Value`、`Fleet2Value` 和 `PublicEmotion.FleetValue` 开启 `resubmitOnEdit`：明确重新输入同一值也提交，以便建立新的实测基准；仅聚焦后失焦不提交。恢复条件及完整存档规则见 [战斗模块](../combat.md)。

### 连接状态迁移

```
connect() ──▶ connecting ──session 事件──▶ auth（需密码）或 ready
ready ──心跳 15s ping；45s 无接收视为死链主动断开──▶ offline ──重连──▶ connecting
onclose：所有 pending 请求以 DISCONNECTED 拒绝；指数退避 800ms×2ⁿ（上限 15s）+ 随机抖动
登录失败 UNAUTHORIZED：清密码、清 localStorage，回到 auth 态
disconnect()：stopped=true，不再自动重连（登出语义）
```

请求超时 45s（独立于连接状态）；`auth.login` 是唯一允许在非 ready 态发送的方法。

## 6. 工作流程

### 一次字段编辑的全链路

```
输入框草稿 ─▶ 失焦／回车 ─▶ prepareValue（文本/提交值分离、默认值回落、格式校验）
  ─▶ queue.change(path, value, payload)
      ├─ 立即入队（sequence++），草稿写入 sessionStorage（仅未确认条目）
      └─ flush → drain：取 sequence 最小的 queued → saving → config.patch
            ├─ 成功 → sequence 校验通过时先经 onSaved 回调把服务端回传的整份配置
            │          交给页面替换本地副本（TaskConfig 据此刷新，否则界面在草稿显示期
            │          过后回落到保存前的旧值）→ saved（readyAt=now）→ 静默期 + 显示期
            │          → settle 后从队列删除
            └─ 失败 → error（retryable 按错误码分类）→ 自动退避重试或等用户
```

### 重连后的恢复

```
断线 → onclose：pending 全拒（DISCONNECTED）→ offline
     → 指数退避重连 → session 事件 → ready
     → context.tsx 监听 connection==='ready' → resumeEditors()
        → 扫 sessionStorage 全部 azurpilot.edits.* 键重建对应队列（含当前不在显示的实例）
        → 对所有 retryable 的 error 条目 retry → drain 重发
服务端响应回到后，页面 config.get 的回执经 reconcile(confirmed) 只清理
「读取前已确认且过静默期」的条目——读取期间的新输入与回执仍由队列保护。
```

### 刷新后的草稿恢复

构造函数从 sessionStorage 读回草稿时做三件事：跳过无 sequence/无 value 的脏数据；**丢弃空的不可重试错误草稿**（字段本来就是空的，用户再清空也不会触发输入事件，草稿会永远钉死字段）；取所有条目 sequence 的最大值续接计数器，避免恢复后的新输入与旧草稿撞号。

## 8. 数据流

```
键盘输入 ──prepareValue──▶ payload ──EditQueue──▶ WebSocket（config.patch 逐条）
                                    │
                                    ├─ sessionStorage：未确认草稿（每标签页独立）
                                    └─ 状态回执 ──reconcile──▶ 与 config.get 的确认值对账
connection 事件 ──context──▶ 全局 UI（离线横幅/登录页）+ resumeEditors
```

## 11. 异常与错误处理

| 情况 | 语义 |
| --- | --- |
| 响应回来时字段已被改（sequence 不匹配） | 丢弃响应，不落 saved/error——新输入继续排队 |
| 永久错误（参数非法/只读/不存在/配置非法） | 停在原字段显示错误，不自动重试 |
| 可重试错误（断线、超时、服务暂不可用） | 指数退避自动重试，页面显示错误与重试按钮 |
| sessionStorage 不可用/写失败 | 队列继续在内存工作，显示「草稿保存失败」提示 |
| 运行工具时队列未排空 | `settled()` 抛「存在未保存修改」，不带旧配置启动 |

## 12. 并发与线程模型

前端无多线程，竞态全部来自**异步时序**，防护手段是四件事：sequence 校验（旧响应不覆盖新输入，`onSaved` 回调也在校验通过后才触发，页面拿到的配置不会比本地输入旧）、reconcile 只清理读取前确认的条目（读取与输入并发安全）、publish 只持久化未确认条目（草稿不含已被服务端确认的旧值）、保存成功回传整份配置（页面以服务端回执为本地状态的最终事实，草稿显示期过后不回落旧值）。每个浏览器标签页独立 sessionStorage，多标签页互不覆盖草稿。

## 16. 修改注意事项

- **不要把 drain 改成批量并发发送**：逐条按 sequence 串行是有意为之——同字段连续修改时顺序必须与输入一致，且单条失败不影响其余。
- **sequence 校验两处都不能省**：drain 成功/失败落状态前都要比对 sequence，删掉任何一处都会让旧响应覆盖新输入。
- **静默期/停留期常量**（700ms/800ms）是界面不闪的参数，调整前跑 `EditQueue.test.ts` 的时序用例。
- **新增保存类型（非 config/deploy/startup）**：在 `editors.ts` 的 scope 分支加映射，不要绕过队列直接 `api.request` 写配置。
- 心跳与超时常量（15s/45s/45s）与后端会话超时联动，单方面调整会造成假离线。

## 17. 已知限制

- 草稿按标签页隔离（sessionStorage），同一浏览器跨标签页打开同一实例时，各自草稿不合并（后保存者胜出）。
- 断线期间输入的字段在重连前显示为排队态；若重连后服务端配置已被其他端修改，以 sequence 对账为准，可能出现「草稿覆盖」的取舍——当前语义是本地未确认输入优先重发。

## 19. 调试方法

- 队列行为异常先跑 `npm test -- frontend/src/config/EditQueue.test.ts`——竞态语义全部以用例名表述（如「新读取只清理此前确认的输入」）。
- 连接问题看浏览器 DevTools 的 WS 帧：请求 id 与响应关联、session 事件的 `authRequired`、心跳 ping。
- mock 模式（`npm run dev:mock`）可复现断线/重连，无需真实后端。

## 20. 相关模块

- [前端](frontend.md) —— 目录分工与构建测试入口
- [API 服务](api.md) —— `config.patch`/`settings.patch` 的服务端语义与事务
- [WebUI 总览](index.md) —— 跨进程配置事务（前端队列只是第一环）
