# 启动器与后端通信协议 v2

后端提供 `ws://127.0.0.1:<WebuiPort>/api/v2/launcher/ws`，启动器主动建立一条双向连接。它承载控制、通知、状态和登录票据，不访问外部服务器，不依赖浏览器窗口是否打开。

## 建连与生命周期

- 握手请求头为 `Authorization: Bearer <AP_WEBUI_TRUST_SECRET>`。密钥由启动器生成并通过环境变量交给自己启动的 Python 后端，不放入 URL、页面或日志。
- 后端同时检查回环来源、Host、Origin 和转发标记；非本机或密钥无效在升级前拒绝。未配置密钥时禁用启动器通道。
- 升级后 5 秒内必须发送 `session.hello`。同一应用只有一个活动连接，新连接鉴权成功后替换旧连接。
- 单条 JSON 最大 64 KiB；后端每连接最多 30 条消息/秒；发送缓冲 128 条。
- 启动器每 15 秒发送 `system.ping`，45 秒没有有效消息断线。按 1、2、5、10、30 秒退避重连。
- 停止后端或退出启动器时主动关闭 socket，并结束当前会话线程；旧会话不能修改新会话。

## 消息格式

请求：`{"type":"request","id":"唯一ID","method":"方法名","params":{}}`。

成功：`{"type":"response","id":"对应ID","ok":true,"result":{}}`。

失败：`{"type":"response","id":"对应ID","ok":false,"error":{"code":"错误码","message":"说明"}}`。

通知：`{"type":"event","id":"通知ID","topic":"notification","data":{"instance":"alas","title":"标题","content":"正文"}}`。

不包含旧浏览器协议的 `v` 字段。未知字段和非法类型被拒绝；请求 ID 最长 100 字符。后端命令还携带 `deadline`（Unix 秒）；过期命令不得执行。

## 方法与方向

| 方向 | 方法 | 参数与结果 |
| --- | --- | --- |
| 启动器 → 后端 | `session.hello` | 参数：`protocolVersion:2`、`launcherVersion`、`platform`（win32/darwin/linux）、`capabilities`（autostart/notifications/login）、`autostart:{supported,enabled}`；结果：`{protocolVersion:2,heartbeatSeconds:15}` |
| 后端 → 启动器 | `autostart.get` | 空参数；返回 `{supported:boolean,enabled:boolean|null}` |
| 后端 → 启动器 | `autostart.set` | `{enabled:boolean}`；返回实际自启状态 |
| 启动器 → 后端 | `state.report` | `{autostart:{supported,enabled}}`；返回 `{accepted:true}` |
| 启动器 → 后端 | `notifications.ack` | `{ids:[通知ID]}`，最多 100 个；返回 `{accepted:true}` |
| 启动器 → 后端 | `login.issue` | 空参数；返回 `{ticket,ttl:60}` |
| 启动器 → 后端 | `system.ping` | 空参数；返回 `{pong:true}` |
| 启动器 → 后端 | `scheduler.state` / `scheduler.pause` / `scheduler.resume` | 空参数；托盘「暂停 / 继续任务」。pause 停止所有运行中的实例并记住它们，resume 恢复这些实例（无记录时启动全部实例）；均返回 `{running:[实例名],paused:[实例名],errors:[说明]}`。在线程池中执行，不阻塞同一连接的其它消息 |

握手成功响应先发送，再补发缓存通知。启动器在本机会话内保留最近 128 条命令响应与通知 ID；相同命令 ID 返回已完成的结果，不重复执行。修改命令在断线后不自动重放；同一 ID 携带不同参数返回 `DUPLICATE_REQUEST`。

后端最多 32 个在途命令，10 秒超时，保留最近 128 条命令状态。命令状态为 pending/succeeded/failed/expired；超时或断线不代表系统操作一定未执行，重连时以启动器上报的实际状态为准。

通知按 ID 确认，最多缓存最近 100 条；启动器去重后再确认。后端重启不持久化通知。缓冲溢出时丢弃最旧通知，慢客户端会被断开。

## 页面与任务进程

浏览器通过现有 `/api/v1/ws` 调用 Python 后端的 `launcher.status`、`launcher.autostart.set`、`launcher.command.get`。这些方法仅允许本机直连，写操作受 DEMO 只读保护。`launcher.autostart.set` 立即返回 `{commandId,status:"pending"}`，页面通过全局 `launcher` topic 接收后端状态与执行结果。

任务进程 POST `/api/v2/internal/notifications`，正文仅接受字符串 `instance/title/content`。后端分别送到启动器 WS 和浏览器已有的 notifications topic。

启动器打开 `/?launcherTicket=<ticket>`。浏览器立即移除地址中的票据，再通过现有业务 WS 的 `auth.launcher({ticket})` 消费它；票据有效期 60 秒、只能消费一次且不能跨应用使用。此过程不传输 WebUI 密码，也不写入密码存储。

旧 `/api/launcher/*`、`/api/notify`、`/api/notify_stream`、`/launcher-login` 返回 404，不提供旧协议回退。

## 验证

后端执行 `uv run python -m unittest tests.test_launcher_api tests.test_notify_api tests.test_launcher_trust`；启动器执行 `cargo test --locked --test launcher_ws`。

跨语言联调：先构建启动器的 launcher_ws 测试，将测试可执行文件的绝对路径设为 `AZURPILOT_LAUNCHER_TEST_BINARY`，在后端执行 `uv run python -m unittest tests.test_launcher_interop`。测试启动临时配置的 Python 服务，使用真实 Rust WS 客户端验证命令执行、通知确认和票据签发。
