# 通知、LLM 与日志

> 调度器的可观测性与外部触达设施：OnePush 多渠道推送、LLM 错误分析、Rich 多目标日志，以及决定「等还是跑」的服务器维护检查。

## 1. 模块概述

这四块代码不属于任何游戏功能，却决定了 AzurPilot 能否 7×24 无人值守运行：

- **推送通知**（`module/notify/`）把调度告警、停止条件和收益事件送到用户手机；
- **LLM 错误分析**（`module/llm.py`）在异常发生时调用 OpenAI 兼容 API 生成中文原因分析，省去用户贴日志问群的时间；
- **日志系统**（`module/logger.py`)是全框架唯一的日志入口，同一行日志同时落到控制台、按天轮转的文件和 WebUI 页面；
- **服务器状态检查**（`module/server_status.py` + `module/server_checker.py`）在游戏维护期间阻塞调度循环，避免无效重试，并在恢复瞬间触发游戏重启。

它们都被 [调度器](../entry/alas.md) 的异常恢复链调用：异常 → 记日志（error_context）→ 保存错误现场（触发 LLM 分析）→ 推送通知（OnePush + WebUI 双通道）→ 决定恢复或等待服务器。理解这条链是读懂任何崩溃日志的前提。

普通统计数值日志与既有 CL1 遥测保留；所有 Rich 异常渲染关闭 `tracebacks_show_locals`，避免敏感运行状态随局部变量落盘。

## 2. 模块职责

### 负责

- OnePush 渠道推送与本地 WebUI 推送的统一入口（`handle_notify` / `notify_webui`）
- 异常堆栈 + 最近日志的 LLM 分析与结果缓存
- 控制台彩色输出、按天文件轮转与归档、WebUI 渲染对象流
- `hr` / `attr` / `error_context` 等全项目约定的日志辅助方法
- 游戏服务器维护状态的查询、退避重试与恢复报告

### 不负责

- 错误现场的截图与日志归档（`alas.py` 的 `save_error_log` 负责，LLM 分析只是它最先执行的一步）
- 日志的 WebSocket 推送与前端渲染（`module/api` / `module/runtime/process_manager` 负责传输）
- 任务调度与错误恢复策略本身（只提供「服务器是否可用」这一个判断依据）
- 用户数据统计上报（见 [统计与数据提交](statistics.md)）

## 3. 模块位置

```
module/
├── notify/
│   ├── __init__.py       # 延迟导入转发，避免未用通知时加载 onepush
│   └── notify.py         # handle_notify（OnePush）、notify_webui（本地端口）
├── llm.py                # analyze_exception：OpenAI 兼容错误分析
├── logger.py             # 全局 logger、Rich 处理器、hr/attr/error_context
├── logger.pyi            # logger 扩展方法的类型提示
├── server_status.py      # 游戏网关直连协议层（TCP 10018/10019 + 原始 HTTP）
└── server_checker.py     # ServerChecker：调度面向的可用性检查器
```

| 文件 | 一句话职责 |
| --- | --- |
| notify/notify.py | 解析 YAML 推送配置，经 onepush 发往外部渠道；或 POST 到本地 WebUI 端口 |
| llm.py | 堆栈 + 日志尾部喂给 LLM，MD5 去重缓存，全程静默降级 |
| logger.py | logging.getLogger('alas') 挂三个 Rich 处理器，并 monkey-patch 辅助方法 |
| server_status.py | 无状态协议工具：向各地区游戏网关查询服务器原始状态 |
| server_checker.py | 公共状态 API 优先、网关兜底、退避重试的检查器 |

## 4. 核心入口

| 入口 | 用途 |
| --- | --- |
| `handle_notify(config_yaml, title=, content=)` | 发送 OnePush 推送；`module/notify/__init__.py` 做延迟导入转发 |
| `notify_webui(instance, title, content)` | POST `http://127.0.0.1:<WebuiPort>/api/notify`，供启动器接收 |
| `analyze_exception(config, e)` | LLM 分析异常；由 `alas.py` 的错误路径调用 |
| `logger`（`from module.logger import logger`） | 全框架统一日志对象；`hr`/`attr`/`error_context` 等方法为 monkey-patch |
| `set_file_logger(name)` / `set_func_logger(func)` | worker 进程启动时挂文件/WebUI 处理器（`process_manager.py` 调用） |
| `ServerChecker(server)` | 调度器 `cached_property checker`；`wait_until_available()` / `is_recovered()` |
| `server_status.query_server(region, server_id)` | 检查器 API 失败时的网关直连后备 |

## 5. 核心组件

| 组件 | 位置 | 说明 |
| --- | --- | --- |
| `Provider.request` 超时补丁 | notify.py | 给 onepush 所有 HTTP 请求注入 `(10, 30)` 秒超时，防止推送服务器无响应时永久阻塞调度线程（issue #824） |
| `_analyzed_errors_cache` | llm.py | 堆栈 MD5 → 分析文本的字典；超过 50 条整体清空 |
| `RichTimedRotatingHandler` | logger.py | 按天轮转的文件处理器，轮转时以 Rich 格式化并支持多进程 |
| `RichRenderableHandler` | logger.py | 把 Rich 渲染对象直接交给回调函数，是 WebUI 实时日志的数据源 |
| `HTMLConsole` / `Highlighter` / `WEB_THEME` | logger.py | Web 专用控制台：truecolor、80 宽、路径/时间/布尔值高亮 |
| `error_context()` / `exception_context()` | logger.py | 结构化错误输出（标题/原因/影响/建议/异常 + 堆栈） |
| `GatewayServer` | server_status.py | 网关返回的单服原始信息；`.status` 属性把协议数字转为状态文本 |
| `ServerChecker._state` | server_checker.py | `deque(maxlen=2)` 可用性队列，支撑「刚恢复」的一次性判断 |

## 6. 工作流程

### 推送通知（module/notify）

1. 调用方传入 YAML 字符串（通常即 `Error_OnePushConfig`）与 `title`/`content`；`provider: null` 视为未配置，直接跳过。
2. `yaml.safe_load_all` 合并配置后按 provider 取 notifier，先对 required 参数做缺失预检查（只警告不阻断）。
3. 特殊渠道修正：`Custom` 渠道强制 JSON 并注入 `data.title`/`data.content`（支持 `${content}` 占位符）；go-cqhttp 把 `access_token` 映射为 `token` 并解析响应中的失败状态。
4. 发送失败一律只记日志并返回 `False`：onepush 内部吞掉请求异常时返回 `None`，必须显式检查，否则推送不可达时日志里无失败痕迹。

`notify_webui` 是独立通道：读部署配置的 `WebuiPort`（默认 25548），向本机 `/api/notify` 发 2 秒超时的 POST，异常静默。业务方几乎总是双通道一起调用——OnePush 送达手机，WebUI 送达正在看页面的用户：`/api/notify` 收到后兵分两路，经 notify_hub 以 `notifications` 主题实时广播给浏览器（前端 Notification API 弹 Windows 原生通知），同时进队列供外部启动器经 `/api/notify_stream`（SSE）订阅。

调度器额外套了一层**低推送量模式**：`alas.py` 的可恢复异常分支（`GameNotRunningError`、`EmulatorNotRunningError`、`GameStuckError`、`GamePageUnknownError`、未满 3 次的 `ScriptError`、`RequestHumanTakeover`、`AutoSearchSetError` 与兜底 `Exception`）统一经 `_notify_recoverable()` 发双通道；开启 `Error_LowPushMode` 时该方法是空操作，只记一条 info 日志。这些错误都会被自动重启游戏/模拟器消化，逐个推送会在无人值守时形成轰炸。需要人工介入的路径（`_check_sensitive_exit`、`ScriptError` 满 3 次退出、调度循环的任务连败判定）仍直接调用 `handle_notify`，不受该模式影响。

### LLM 错误分析（module/llm.py）

1. 触发点只有 `alas.py`：任务级异常经 `save_error_log()` 时取 `sys.exc_info()` 分析（放在最前，避免后续截图二次崩溃导致分析未执行）；调度循环的未处理异常则直接调用。
2. 以完整堆栈的 MD5 为键查缓存，命中则复用上次报告，不再调 API。
3. 未命中时先写入占位文本（防并发重复分析），缓存超过 50 条整体清空；未配置 API Key 则告警返回。
4. 喂给 LLM 的内容是「最近 500 行日志 + 异常堆栈」，总预算约 64K 字符（日志 40K、堆栈 20K，超长从尾部截断保留最新），并不发送截图。
5. 经 OpenAI 兼容 `chat.completions`（60 秒超时）取回中文分析报告，用 `logger.hr` 分节输出并写入缓存。

失败一律静默降级：未安装 openai 库、调用异常、返回空结果都只记简短警告并回滚缓存占位，绝不影响任务恢复。模块日志固定携带「严禁提交此模块的相关日志」警示，因为其中含 API 配置上下文，防止用户把日志提交到群机器人或错误上报。

### 日志系统（module/logger.py）

全局 `logging.getLogger('alas')`，级别 INFO（模块常量 `logger_debug` 默认关闭）。导入即完成初始化：stdout/stderr 重配为 UTF-8、把 `logging.basicConfig` 替换为空函数（防 cnocr 在 root logger 上重复输出）、`os.chdir` 到仓库根目录、挂控制台处理器并执行首次 `set_file_logger()`。三个 sink 各自独立：

- **控制台**：`RichHandler`，本地调试用；Electron、TUI 与 WebUI 子进程用 `set_console_logger(False)` 关闭。
- **文件**：`RichTimedRotatingHandler`，每天午夜轮转到 `./log/<日期>_<实例名>.txt`；保留份数与过期处理方式读自 `./config/<实例>.json` 的 `General.Log`，过期文件在 daemon 线程中按 `LogBackUpMethod` 移入 `./log/bak/`（压缩/复制）或删除。每个进程只挂一次（幂等），Windows 下 SyncManager/MainProcess 等辅助进程跳过。WebUI 子进程用 `set_file_logger('webui')` 只写 `./log/<日期>_webui.txt`，不动 stdout/stderr，任务子进程照常继承控制台。
- **WebUI**：`set_func_logger(q.put)` 把每条日志渲染成 Rich 渲染对象塞进 multiprocessing 队列 → `ProcessManager` 消费线程存入 `renderables` 列表（上限约 400 条）→ API 的 `logs()` 方法用无色 Console 把渲染对象捕获为文本、正则提取日志级别，前端经 WebSocket `logs.get` 按游标增量拉取。

高频 API 的分级语义（全项目通用约定）：

| API | 语义 |
| --- | --- |
| `logger.hr(title, 0)` | 三层横线框住的大标题，仅进程启动等一次性事件 |
| `logger.hr(title, 1)` | `═` 横线 + 大写标题，任务级阶段（调度器每个任务开头） |
| `logger.hr(title, 2)` | `─` 横线 + 标题，任务内子阶段 |
| `logger.hr(title, 3)`（默认） | 行内 `<<< 标题 >>>`，细粒度步骤 |
| `logger.attr(name, text)` | `[名称] 值`，记录识别/决策结果 |
| `logger.error_context(title, reason, impact, action, exc)` | 统一错误四段式：错误/原因/影响/建议，可选附带异常与堆栈 |
| `logger.exception_context(title, exc, ...)` | 未知异常版本，固定保留完整堆栈 |

`logger.print()` / `logger.rule()` 绕过 logging 分级，直接向三个 sink 发送 Rich 渲染对象，用于表格等富内容。

#### 来源文字水印

来源文字水印始终启用，不提供配置开关。调度器启动时后台采集并输出 `[来源水印]`；保存错误
现场时，在 `[AzurPilot] 保存错误日志:` 提示之前立即输出最近采集快照，随后随原日志一起复制进
现场的 `log.txt`。信息包括实际 origin 源、实际分支、当前本地提交的前 12 位及是否有本地修改。
「本地修改」检查 Git 已跟踪文件的已暂存和未暂存修改，不把未跟踪的安装器或实例配置当作
代码修改；它不表示启用了某个修改许可开关。

采集由 `module/base/log_watermark.py` 的 daemon 线程执行，Git 命令共享三秒超时预算，不联网、
不拉取远程提交，不使用会保存配置或触发地区查询的部署配置初始化。来源地址移除用户名、密码、
查询参数和片段，本地目录只显示「本地仓库」。实际源不可读取时可回退到标明「配置」的更新源；
其余不可读取的字段显示「未知」，分离 HEAD 不伪装成配置分支。无 `.git` 的整包仅在
`BUILD_MANIFEST` 明确提供提交时使用该提交，修改状态保持未知。

错误保存前的输出标明「最近采集快照」；采集尚未完成时各字段为未知，不等待 Git。随后后台
静默刷新缓存供下次使用，不再向保存后的文件追加水印，也不额外输出本次刷新的结果，因此
快速退出不影响已输出的水印位置。快照可能早于本次错误，不能当作错误发生时的实时检测。
导入、线程启动或采集失败只跳过水印，不改变原有日志、截图、脱敏、过期处理、通知或恢复策略。
旧配置中的 `Alas.Error.LogWatermark` 不再生效，配置更新时移除；其他错误设置不变。关闭
「出错时，保存 Log 和截图」仍仅停止错误现场保存，不关闭启动水印。升级后需重新启动调度器。

### 服务器状态检查（server_status 与 server_checker）

两个文件刻意分层：`server_status.py` 是**协议层**——无状态、无缓存、无框架依赖，直接对各地区游戏网关发 10018 请求并解析 10019 响应（手写 protobuf varint 解码；cn_ios/渠道服走原始 HTTP JSON），把状态数字映射为 `normal/maintenance/full/reg_full/unopened`。`server_checker.py` 是**策略层**——`ServerChecker` 优先查公共 API（server-checker.nanoda.work，连接和读取超时各 3 秒，避免慢接口长时间阻塞任务启动），404 时回退本地服务器列表判定；连接失败、超时或返回 429/5xx 时记录切换提示，再直连游戏网关兜底，两者都不可达才进入快速重试（先探测百度区分「本机断网」与「API 故障」，再重试 3 次）。3 秒是单阶段超时，不是整个检查过程的总时限；游戏网关自身的超时及维护等待规则不变。

`alas.loop` 每轮取任务前调用 `checker.wait_until_available()`：服务器维护或 API 与网关都不可达时，检查间隔从 2 分钟逐步退避到 10 分钟，循环阻塞在此不推进任务；`is_recovered()` 在恢复瞬间返回一次 `True`，调度器随即刷新配置并注入 Restart 任务（阻塞期间游戏状态必然已失效）。`GamePageUnknownError` 处理路径也用它分流：服务器可用 → 当作页面识别问题重启游戏；不可用 → 等待维护结束。服务器配置为 `disabled`（默认值）时检查器恒返回可用。

## 7. 调用关系

### 上游

| 模块 | 关系 |
| --- | --- |
| 调度器 `alas.py` | 异常恢复链的主要消费方：各 except 分支双通道推送，错误现场触发 LLM 分析，循环头部做服务器检查 |
| 战役/委托/秘书舰等业务 | 收益与状态事件推送（委托奖励、秘书舰替换、作战委托冲突等） |
| 大世界智能调度 | `notify_push` 统一封装启动器推送与 OnePush（可独立渠道） |
| 日报服务 | 复用 `Error_Llm*` 配置生成日报，并经 `handle_notify` 推送（最多 3 次重试） |
| WebUI 进程管理 | worker 启动时调用 `set_file_logger` / `set_func_logger`，消费日志队列 |

### 下游

| 模块 | 用途 |
| --- | --- |
| onepush | 实际的外部推送实现（QQ/Telegram/Discord/钉钉/企业微信/飞书/Bark/Server 酱/SMTP 等） |
| openai（Python SDK） | LLM 分析与日报的 Chat Completions 调用 |
| Rich | 所有日志格式化与渲染 |
| `module/config/server.py` | 服务器名称到 region/server_id 的元数据解析 |

## 10. 配置

配置路径 `<Task>.<Group>.<Argument>`，代码经 `self.config.Group_Argument` 访问。

| 配置 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `Alas.Error.OnePushConfig` | YAML 文本 | `provider: null` | 全局推送渠道配置；留空或 provider 为 null 视为未配置 |
| `Alas.Error.LowPushMode` | checkbox | false | 低推送量模式；可恢复错误只记日志不推送，仅保留需要人工介入的错误推送 |
| `Alas.Error.LlmAnalysis` | checkbox | true | 启用 LLM 错误分析 |
| `Alas.Error.LlmApiKey` | 文本 | 空 | OpenAI 兼容 API Key，缺失时仅告警不分析 |
| `Alas.Error.LlmApiBase` | 文本 | `https://api.xiaomimimo.com/v1` | API 基地址，可指向任意 OpenAI 兼容服务 |
| `Alas.Error.LlmModel` | 字符串 | `mimo-v2.5-pro` | 模型名 |
| `Alas.Error.SaveError` / `SaveErrorRetentionDays` / `SaveErrorBackUpMethod` / `SaveErrorZipMethod` | checkbox / 数值 / 选项 | true / 30 / zip / zip | 错误现场保存；过期天数（0 = 不清理）、过期处理方式（delete/copy/zip）与压缩格式，备份落 `log/error/<实例>/bak/`；LLM 分析在保存流程最前执行 |
| `Alas.Emulator.ServerName` | 选项 | `disabled` | 服务器检查目标；disabled 跳过检查 |
| `Secretary.Secretary.Notify` / `OnePushConfig` | checkbox / YAML | true / `provider: null` | 秘书舰推送，专用配置留空回退全局 OnePushConfig |
| `OpsiGeneral.OpsiGeneral.LauncherPush` / `NotifyOpsiMail` / `IndependentPush` / `OpsiOnePushConfig` | — | true / true / false / `provider: null` | 大世界智能调度的启动器/OnePush 双通道与独立渠道 |
| `Commission.CommissionNotifyReward` / `GemNotify` | checkbox | false / true | 委托奖励、钻石委托推送开关 |
| `General.Log.LogKeepCount` / `LogBackUpMethod` / `ZipMethod` | — | 3 / zip / zip | 文件日志保留份数、过期处理（delete/copy/zip）与压缩格式 |

关联：LLM 分析与日报共用同一组 `Error_Llm*` 密钥；秘书舰和大世界都有「独立推送配置 + 回退全局」的层级；`Error_OnePushConfig` 是绝大多数业务推送的默认渠道。

## 11. 异常与错误处理

| 异常 | 原因 | 处理 |
| --- | --- | --- |
| YAML 解析失败 | OnePushConfig 格式错误 | 记 error，跳过发送，返回 False |
| onepush 返回 None / 非 200 | 推送服务器不可达 | 记 warning，返回 False；不抛出 |
| openai ImportError | 依赖未安装 | 记 error，回滚缓存占位，跳过分析 |
| LLM 调用异常 / 空结果 | 网络、配额、模型配置 | 简短警告 + 回滚缓存，静默降级，不影响任务恢复 |
| `ServerStatusQueryError` | 网关超时/协议错误/网络故障 | 检查器回退快速重试，再不行按 2→10 分钟退避 |
| `ScriptError`（检查器内部） | 公共 API 与网关均返回无效数据 | 检查器自我禁用（视为可用），绝不阻塞调度 |

设计原则：推送与 LLM 都运行在异常处理路径上，自身失败绝不能抛出二次异常掩盖原始错误；唯一会向上传播的是检查器收到的意外异常（交给调度器全局恢复）。

## 12. 并发与线程模型

- **logger.handlers** 由 logging 模块内部锁保护，多线程写安全；文件轮转的删除/压缩在独立 daemon 线程执行，避免阻塞日志写入。`set_file_logger` 设计为每进程启动时调用一次，自带幂等保护。
- **跨进程日志流**：worker 进程的 `RichRenderableHandler` 回调把渲染对象 `put` 进 multiprocessing 队列，管理端 `_thread_log_queue_handler` 线程消费进 `renderables` 列表；`run_id` 绑定轮次，旧轮线程的残留消息被丢弃。
- **推送线程**：秘书舰的 `notify()` 在独立 daemon 线程发送，不阻塞游戏状态循环；其他调用点（alas 异常链等）在当前线程同步发送，受 `(10, 30)` 秒超时约束。
- **LLM 调用**：在调度线程内同步执行（60 秒超时），分析期间调度暂停——这是有意为之，分析结果要在后续恢复动作前输出。
- 缓存 `_analyzed_errors_cache` 为模块级字典，仅调度线程访问；用「先写占位、完成覆写、失败回滚」避免并发重复调用 API。

## 16. 修改注意事项

- `Provider.request` 超时补丁有 `_timeout_patched` 防重复包装标志：模块被重复加载时二次包装会丢失原函数引用导致无限递归，改动这段必须保留该保护。
- `handle_notify` 的失败分支禁止改为抛异常，调用方依赖「只返回 False」的契约；同理不要在其中打印完整异常栈（内容可能含渠道 token）。
- llm.py 的日志文案（含「严禁提交」警示）与简化错误日志是防循环日志、防泄露的设计，改写时保留意图；不要改用 `logger.exception`。
- logger.py 是全项目的第一个导入（入口模块在游戏模块之前 import 它），导入副作用（chdir、UTF-8 重配、basicConfig 置空）不能移到函数里或删除；其顶部也不要 import 其他项目模块以免循环导入。
- `hr`/`attr`/`set_func_logger` 等方法是运行时 monkey-patch 到 logger 上的，类型提示在 `module/logger.pyi` 同步维护，改签名需两处同改。
- WebUI 日志链路依赖「渲染对象 → 无色 Console 捕获文本 → 正则提取级别」，调整 Rich 渲染配置（宽度、颜色系统、格式）会破坏 `logs()` API 的级别解析与前端游标协议。
- `server_status.py` 的网关地址与协议需与 AzurLaneServerStatus 项目保持一致；`module/config/server.py` 的服务器列表按数组下标持久化用户配置，只可追加不可重排。

## 19. 调试方法

- `logger.show()` 可在控制台预览各级别与 `hr` 样式（末尾会故意抛异常，仅用于观察输出）。
- 日志关键字：`[通知]`（推送结果）、`[LLM]`（分析过程与报告）、`[服务器检查]`（可用性判定及数据来源）、`[日报]`。
- 推送失败先确认 OnePushConfig 的 provider 已设置、required 参数齐全；「未收到推送服务器的响应」通常是网络或渠道服务不可达。
- LLM 三条固定警告对应三类故障：配置缺失、空返回、调用失败；按提示检查 Key/Base/模型/余额。
- 服务器检查问题看 `[服务器检查]` 行会标注判定来源（公共 API / 游戏网关 / 本地已验证）；`tests/test_server_checker.py` 覆盖 API 协议与故障恢复，可离线跑。

## 20. 相关模块

- [调度器（alas.py）](../entry/alas.md) —— 所有触发点所在的异常恢复链与调度循环。
- [WebUI 总览](../webui/index.md) 与 [API 服务](../webui/api.md) —— 日志流的消费端（`logs.get` 游标协议）与 `/api/notify` 接收方。
- [统计与数据提交](statistics.md) —— 日报服务复用 LLM 配置与 OnePush 推送。
- [配置系统](../config.md) —— `Error_*`、`General.Log.*` 等配置的定义与生成。
- [WebUI 启动器（gui.py）](../entry/gui.md) —— `notify_webui` 的端口来源（`WebuiPort`）。
