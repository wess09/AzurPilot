# 公网直连、Cloudflare 回退与 AFA 配对

## 启用

AP 的「远程访问」页将模式选为 `auto` 或 `cloudflare`，设置 WebUI 密码并开启远程访问，重启 AP。
`CloudflareRegistry` 默认为 `https://remote.azurpilot.com`。
注册与配对使用 `/api/v1/*`，根路径为介绍页。已知旧试验地址会迁移到新域名，保留设备身份；自定义服务器不变。
AFA 在「设置 → Runtime」点击「试用 Quick Tunnel」，确认重启后使用同一套 AP provider；
已有 SSH / WebRTC 模式只有在用户选择试用时才切换。
仅作为客户端连接其他 AP 时，从 AFA 欢迎页、主页或本机部署页点击「连接远程 AP」；
不需要安装或启动本机 Runtime，也不需要 Shizuku。远程模式会保存，断连页保留配对入口。

设备身份保存在 `config/remote-access.json`：安装 ID 与注册密钥持久化，配对访问凭据只保存
SHA-256 摘要。AFA 第一次启用时将 Android ID 与随机安装因子的摘要作为设备 ID，
不上传 Android ID 原文；卸载后重新安装会获得新身份，避免丢失旧密钥后占用原设备入口。
`CloudflareDeviceId` 留空时自动生成；兼容部署解析器保留的 `""` / `''` 空值。
旧版若已将引号空值保存为身份，只修复未被服务器接受的 ID，保留原设备密钥与已保存授权。
备份身份文件才能在迁移后保留原固定入口；禁止把此文件作为用户实例、测试夹具或 Git 内容提交。

## 生命周期

`CloudflareRemoteAccessProvider` 在线程内调用 `pyflared==0.1.0` 的 `run_quick_tunnel()`。
上游库导入时创建的数据库目录定向到项目 `cache/cloudflare/pyflared/`，无需写入
Windows `AppData/Local/Azmain`。适配仅匹配 pyflared 的应用标识，导入后恢复通用目录函数。
AP 每十秒用设备密钥向独立 Go 服务续约，上报网卡上的公网 IPv4、IPv6 和对外端口；
私网、共享地址和带作用域的 IPv6 不参与注册。默认复用已有 HTTP WebUI 端口（通常为 25548），
挑战验证接口和设备健康检查也使用该端口。HTTPS WebUI 才默认另启端口 + 1 的 HTTP 入口。
`RemoteAccessPort` 可指定独立 HTTP 监听端口，`RemoteAccessPublicPort` 可指定路由器映射后的外部端口，
两者为 0 时分别使用上述默认值和监听端口。AP 不自动修改路由器或防火墙。

Go 服务以随机挑战和 HMAC-SHA256 验证各候选属于该 AP，通过后才发布直连地址；
后台每三分钟复检，候选变化立即重新验证。直连使用裸 IP 的 HTTP/WS，不申请设备域名或证书。
独立转发入口始终标记为远程请求，交给现有 WebUI 网关鉴权，不因回源是本机而绕过密码。
若独立端口无法监听或没有可达公网地址，仍走 Cloudflare 回退。

固定入口为 `<registry>/d/<device_id>/`。浏览器显示 IPv4、IPv6 和 Cloudflare 三类入口，
由用户选择，保留路径、查询参数和片段；注册服务不代理业务流量。
注册成功即开放固定入口和配对，不等待 Cloudflare 就绪；隧道故障不影响其他通道。
AFA 每次连接请求 `/api/v1/devices/{id}/resolve`，从当前网络检查直连设备身份，
没有可达直连时请求 `/fallback` 启动 Cloudflare。失败入口暂时排除，重连重新解析，动态 IP 不需要重新配对。
旧服务或旧客户端无直连时保留禁止缓存的 301 Tunnel 解析兼容路径。

无可用直连，或用户主动选择 Cloudflare 时，AP 才启动 Quick Tunnel；启动后保留该进程，
避免网络切换造成反复申请。每次启动分配新的 `*.trycloudflare.com` URL，通过公网健康检查后才上报。

优雅停止时上报离线并回收 cloudflared；异常退出后服务端租约 180 秒失效。
旧客户端的 Tunnel 跳转还会用四秒超时请求 `/healthz`，确认 AP 的协议健康状态；不跟随探测跳转或携带凭据。
设备不存在、离线或租约过期时，以 302 跳到同域 `/error`；连接选择页刷新时则显示离线状态。
cloudflared 沿用自动传输选择；网络须允许连接 Cloudflare 边缘的 7844 端口。
CLI 分配 URL 后还须通过公网 `/healthz` 协议检查，才注册并显示就绪。
公网探测与注册、续约、配对请求遵循 `HTTP_PROXY` / `HTTPS_PROXY`、`NO_PROXY` 及 Windows 系统代理。
只显式选取代理地址，不自动读取目标主机的 `.netrc` 认证信息，公网探测仍不携带 AP 凭据。
健康检查区分 DNS、代理、TLS、连接和超时错误；响应不是 AP 协议（含 HTML、无效 JSON 或数组）时
报告协议检查失败，不将其误报为 DNS 故障或销毁仍在运行的隧道。
探测或注册续约瞬断会退避重试，保留进程与 Tunnel；健康直连继续独立工作。
仅 cloudflared 退出或未分配 URL 时重建进程，以 30–300 秒退避避免频繁申请；
识别到 Quick Tunnel HTTP 429/1015 后至少等待十分钟，再尝试申请。
公网入口持续返回 HTTP 530 超过两分钟时，回收失效隧道并改用 HTTP/2 重建；短暂故障仍复用原进程。
`pyflared` 的流读取在 EOF 时返回 SKIP，本模块在 EOF 显式结束，避免进程退出后忙循环。
提供者不更改 cloudflared 以外的后台任务或游戏状态。

公网 Host 保留到现有网关，由既有本机判定与 WebUI 密码策略鉴权。无有效 WebUI 密码时
拒绝启动 Quick Tunnel。自签名本机 HTTPS 证书不会自动跳过证书校验。

## 配对

1. AP 远程访问就绪后点击「配对」。AP 生成独立的客户端凭据，将它交给注册服务暂存。
2. 服务器生成六位数字码（保留前导零）、128 位扫描密钥和五分钟有效期。AP 将 128 位密钥编码为
   `azurpilot://pair?secret=<secret>` 矢量二维码，并在界面提供六位验证码及一键复制。
   二维码使用标准 M 级纠错与白底高对比留白，兼容移动端暗色/亮色环境下的快速扫码。
3. AFA 扫描二维码或输入六码，向服务领取固定入口和独立凭据。领取在 SQLite 事务内执行，
   只成功一次；已领取凭据从配对记录清空。数字码和扫描 secret 仅存摘要。
4. AFA 扫码解析 `azurpilot://pair?secret=...` 协议或校验六位码后，用扫描密钥向服务领取配对。
   手动六码与二维码扫码共享原子领取状态，一种方式成功后另一种不能重放。
5. AFA 用 Android Keystore AES-GCM 保存固定入口和独立凭据。点击已配对 AP 后，现有
   `AzurPilotGateway` 重新解析固定入口，以 WS 直连或 WSS Tunnel 调用 `auth.login`；认证完成才对原生页面发布就绪。
   现有总览、实例选择、配置、日志和统计均复用原生仓库与主题订阅。
   切换来源先等待编辑保存，关闭旧连接并清理缓存；返回本机恢复原监听地址。
   本机 PRoot、悬浮窗和设备控制链不随远程网关改址，远程部署设置也不会同步到本机偏好。

AP 的「已授权的配对」可撤销单个凭据。已连接客户端在下一次请求（含 15 秒心跳）时停止授权，
不需要更改 WebUI 主密码。AFA「移除」只删除本机保存的入口，服务器授权应从 AP 撤销。
重新生成配对码会替换服务器上该设备尚未领取的码。
创建、领取和状态轮询均使用 `/api/v1/pairings` 命名空间；AP 状态查询通过
`remote.pair.status` 调用 `/api/v1/pairings/{id}`。
注册服务返回配对过期时，AP 将其转为 `expired` 状态，停止轮询并允许重新配对；
其他注册错误保留 HTTP 状态和路由，设备或配对标识在错误提示中脱敏。

注册服务源码、Docker 和部署说明位于独立私有仓库 [AzurPilot-Remote](https://github.com/wess09/AzurPilot-Remote)。它不保存 WebUI 主密码，
不代理 AP 的 WebSocket、截图或业务数据。配对凭据只有未领取阶段以明文暂存于 SQLite，
因此数据库和服务端私钥需使用服务自己的私有目录。

## 试验与验证

Python 定向测试：`uv run python -m pytest tests/test_remote_direct.py tests/test_remote_cloudflare.py`。
前端定向测试覆盖 `src/api/client.test.ts`、`src/app/remoteStatus.test.ts` 与远程页面。
Go 测试覆盖设备 ID 防冒用、URL 限制、301 更新、离线租约、配对单次领取、过期与限流。
测试使用临时身份和模拟游戏服务，真实账号与调度器不参与网络试验。

AFA 自身开启 Tunnel 需要包含本次 AP 实现和锁定依赖的 Runtime；仅安装新 APK 不会修改旧
Runtime 中的 Python 业务代码。构建 Runtime 时通过 `AZURPILOT_REPO` 与 `AZURPILOT_REF`
指向包含本次 AP 提交的源码，再按 AFA 的 `doc/runtime-provisioning.md` 构建和部署。
`tools/remote-gateway-check` 在 JVM 上直接编译生产网关和配对验证模块，验证鉴权顺序、重连解析、
来源切换、旋转镜像、曝光偏移、纠错与随机噪声拒绝，不运行 AFA 既有孤立测试源集。
扫码、相机权限、后台断网恢复与 PRoot 内 cloudflared 需要在实际 Android 设备上验收。

Quick Tunnel 用于测试和开发，Cloudflare 不提供可用性保证，并限制并发请求、SSE 等能力。
AP 的业务通道使用 WebSocket，固定入口不会消除 Quick Tunnel 的服务限制。
参阅 [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
和 [pyflared](https://pypi.org/project/pyflared/)。
