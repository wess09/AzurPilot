# 部署与启动链路（deploy/ + 启动入口）

> 从「拿到一份源码」到「WebUI 起来、实例跑起来」的全部工程环节：安装器、启动脚本、Docker、依赖自举与前端构建。

## 1. 模块概述

`deploy/` 不是游戏业务，而是把仓库变成可运行系统的安装与启动工程。它要解决三件事：

- **自举**：用户机器上可能只有系统 Python。安装器先用它引导 `uv`，再由 `uv` 建出仓库内 `.venv/`，之后一切 Python、git、adb 都从 `.venv/` 取——系统环境零污染，依赖完全由 `pyproject.toml` + `uv.lock` 锁定。
- **安装**：git 拉仓库（含国内 CDN 兜底）、同步依赖、装 uiautomator2、连模拟器、构建前端，全部封装成 `python -m deploy.installer` 一个命令。
- **自更新**：WebUI 运行中可以替换源码与 `.venv`（父进程监督 + 更新事务，见 [WebUI 总览](../webui/index.md)）；安装器是冷启动路径，两者共享 `deploy/uv.py` 的依赖同步。

## 2. 模块职责

### 负责

- `installer.py`：安装总入口，组合五个管理器（git → 停调度器 → 依赖 → 前端 → adb）。
- `uv.py`：`.venv` 自举、uv 解析、依赖同步（`sync_project_venv`）、常驻依赖同步服务（`dependency_sync_service`，gui.py 运行期调用）。
- `git.py`：仓库更新（常规 git 与 GitOverCdn 兜底）、随机 User-Agent 绕镜像封禁。
- `adb.py` / `emulator.py`：adb 分发与自动连接；VirtualBox 系模拟器注册表扫描与端口发现。
- `frontend.py`：按源码内容摘要决定是否重建 `frontend/dist`。
- `atomic.py`：安装失败的原子清理（临时文件识别与回滚）。
- `patch.py`：安装前环境修补（运行目录检查、uiautomator2/apkutils2 补丁、证书链）。
- `launcher/Alas.bat`（打包为 `AzurPilot.exe`）：用户双击入口——跑安装器，成功后用 `pythonw` 拉起 `gui.py`。

### 不负责

- WebUI 的运行期进程管理——见[运行时服务](../webui/runtime.md)。
- 游戏识别资源与 OCR 模型——安装器只保证 adb/uiautomator2，模型随仓库分发。
- 配置内容（`config/deploy.yaml` 是部署参数，语义见第 10 节）。

## 3. 模块位置

```
deploy/
├── installer.py     # 总入口：Installer(GitManager, PipManager, AdbManager, AppManager, AlasManager)
├── config.py        # DeployConfig（config/deploy.yaml 的模型）+ ExecutionError
├── git.py / git_over_cdn/   # 仓库更新；CDN 客户端与端点表
├── pip.py / uv.py   # 依赖同步（实际是 uv sync，类名保留 pip 是历史）
├── adb.py / emulator.py     # adb 安装与模拟器探测（Windows 注册表 + VirtualBox）
├── frontend.py      # ensure_frontend：源码摘要 → npm ci + build
├── app.py           # AppManager：安装期前端构建步骤
├── patch.py         # pre_checks：路径检查、site-packages 补丁
├── atomic.py        # 失败清理（Windows 文件占用重试）
├── launcher/Alas.bat        # 双击入口（AzurPilot.exe 的本体）
├── Windows/         # Windows 专用 deploy 变体（模板 yaml 等）
├── docker/          # Dockerfile（含 cn 镜像源变体）与构建脚本
├── install/         # 平台辅助（模拟器探测）
└── AidLux/          # 安卓本地部署方案
```

## 4. 核心入口

| 入口 | 用途 |
| --- | --- |
| `python -m deploy.installer` | 全新安装/更新（Alas.bat 即调用它） |
| `AzurPilot.exe` / `deploy/launcher/Alas.bat` | 用户入口：安装器成功后 `pythonw gui.py` |
| `uv run python gui.py` | 开发态启动 WebUI（跳过安装器） |
| `python -m deploy.app` | 只重建前端产物 |
| `deploy/docker/Dockerfile` | 容器构建（多阶段，预装前端产物） |

### 茗交所持久化

股票接入 v2 须在交易所已提供 `/api/v2/instance/*` 后，配套更新 AzurPilot Python 后端与完整前端构建产物并重启 AzurPilot。默认交易所地址已改为 `https://stock.azurpilot.com`；若曾显式设置 `STOCK_EXCHANGE_URL`，更新对应环境变量后重启。交易账户在官方 QQ 群机器人命名注册，登录/强制改密在独立交易所，旧 `stock.request` 不再支持，新前端与旧 AzurPilot 后端不兼容。股票登记使用 `stocks-v2.json`；旧 `bindings.json` 保留但不用于新协议。没有改动脚本调度或普通业务数据库模型。

股票实例本地数据统一持久化在 `config/stock-exchange/`：`game.key` 是随机游戏密钥，`registry.json` 保存加密实例登记、文件摘要和历史检查点，同目录保存密文身份、绑定与补传日志。它们不绑定主机、运行用户或项目绝对路径，不需要额外挂载用户 HOME 或提供 Linux `machine-id`。仓库的 Compose 与 Docker 运行示例挂载完整项目目录；迁移完成后只挂载配置目录也能保留实例股票身份与历史。例如使用 `/app/AzurPilot` 镜像时：

```yaml
volumes:
  - ./config:/app/AzurPilot/config:rw
```

国内 Dockerfile 的工作目录是 `/app/AzurLaneAutoScript`，挂载目标需使用对应路径。新容器运行用户须有数据目录的读写权限；备份、迁移或恢复应停掉服务和 worker，再整体复制配置、中央 SQLite、旧 CL1 统计库与上述游戏数据，避免不同时刻的检查点和历史混用。包含 `game.key` 的备份可解密交易凭据，按私有数据管理。每日自动备份不会覆盖全部交易数据，不能替代这份完整备份。

首次升级须让旧 `cache/stock-exchange/` 可见且可写。检测到旧目录后仅移动文件到 config，支持不同磁盘或容器挂载间的移动；同名冲突静默以默认加载的 config 数据为准，旧 cache 副本被覆盖。搬运后统一执行常规读取、格式升级与校验，文件有问题只在茗交所提示，不阻断正常配置操作。

已有本机保护数据在常规读取时认证并升级，保留原 UUID、私钥、绑定和检查点。旧版应先在原项目路径下升级，再移动部署；升级前需保留原用户密钥目录中的游戏 `.game` 登记和配套 `.key`。Windows 旧密钥须由原用户 DPAPI 解封，Linux 需旧密钥目录可见且文件可读取，容器的 machine-id 变化不阻止升级。若旧容器已被删除且这些文件没有备份，程序无法恢复其加密密钥；可恢复原密钥/登记，也可使用 `stock.rebuild` API 查看实际范围并显式确认重建股票身份。重建保留 `config/backup/stock-rebuild-*/` 原件备份；共享数据损坏时须确认所有本地股票身份范围，不改变独立交易所的交易账号。

macOS 本机部署（Apple Silicon 与 Intel）使用相同的游戏密钥存储，不要求 Keychain、TPM、DPAPI 或机器标识；POSIX 文件权限与跨进程文件锁用于保护持久化读写。`GameDataProtector` 统一解析项目物理路径，兼容 macOS `/var` 等系统路径别名，不放开受保护目录内自定义符号链接的检查。Windows/Linux 数据须先按上述流程升级，再整体迁移 config 到 Mac，继续沿用身份和账户绑定。macOS 上的 Docker 部署同样持久化配置目录。CI 的 `game-data` 任务分别在原生 Apple Silicon、Intel macOS、Windows 与 Linux 执行 `tests.test_game_data`、`tests.test_stock_exchange`、`tests.test_stock_exchange_history` 和 `tests.test_stock_exchange_recovery`；平台专属用例只在对应系统运行。

完整运行环境仍按 `pyproject.toml` 与 `uv.lock` 安装：当前 Apple Silicon 的 ONNX Runtime wheel 最低为 macOS 14，较旧系统不能直接安装这份锁定环境。跨平台依赖预检使用 `MACOSX_DEPLOYMENT_TARGET=14.0 uv sync --frozen --dry-run --python-platform aarch64-apple-darwin`；这只验证安装计划，不替代原生 Mac 上的安装、测试或模拟器验收。茗交所密钥方案本身没有这项 ONNX 系统版本要求。

## 6. 工作流程

### 安装器链条

```
Alas.bat → python -m deploy.installer
  patch.pre_checks()          # 运行目录、site-packages 补丁
  git_install()               # git pull / GitOverCdn 兜底
  alas_kill()                 # 停掉本实例的 alas 进程
  pip_install()               # 实为 uv sync（--frozen），失败抛 ExecutionError
  app_update()                # ensure_frontend()：摘要变化才 npm ci + build
  adb_install()               # adb 就位、替换系统 adb、自动连接、装 uiautomator2
失败 → atomic_failure_cleanup → 退出码 1 → bat pause
成功 → start pythonw gui.py --electron
```

`GitManager.git_install()` 按本地配置直接执行 Git/CDN 更新，不再请求云端更新总开关。云端仅保留运行期间的强制更新开关，其访问失败不阻止正常版本检查。

### 统一云 API 入口

核心云接口地址集中在 `deploy/api_endpoints.py`，统一使用 `https://api.azurpilot.com`：

| 用途 | 路径与协议 |
| --- | --- |
| CL1 月度累计上报 | `POST /api/v2/post/cl1`，UUID、采集时间、原始计数与设备头；派生指标由服务端计算 |
| 公告 | `GET /api/v2/get/notice/data.json`，读取 `announcement`，撤回时清除本地公告缓存 |
| 强制更新 | `GET /api/v2/get/update/data.json`，读取布尔字段 `force_update` |
| 停服维护 | `GET /api/v2/get/maintenance?server=cn`，按当前区服查询；其他服不回退国服 |
| 单服状态 | `GET /api/v2/get/server?region=cn&server_id=1`，保留网关直连后备逻辑 |
| 截图 | `/api/v1/uploads/init` 获取 C 的 307 → 直接向 A 登记、逐文件 `PUT /api/v1/uploads/{id}/files/{index}` → `POST /api/v1/uploads/{id}/complete` |

公告和更新策略读取 Worker 的 v2 文档；动态 v2 查询携带 `X-AzurPilot-ID`。已移除的 `/api/updata` 总开关不恢复。

`掉落记录 → 云端统计上报` 控制截图上报（默认开启），具体类型仍按“上传 / 保存并上传”选项决定。科研同时采集五项项目列表与领奖截图；通用掉落沿用既有采集点，侵蚀1练级只保留独立 CL1 统计。云端开关关闭不影响本地统计。临时文件位于 `log/cloud_upload/<匿名实例ID>/`，单文件最多10 MiB、单组500 MiB、暂存512 MiB且最多128组。失败保留同一组ID，下次采集启动工作线程时恢复旧任务；完成回执成功后删除暂存，超过7天的失败任务清理。

源码更新 CDN、远程连接注册、ATX 下载和交易所由各自服务配置管理，使用各自的地址。

### 启动后的依赖自举

仓库的 `[tool.uv] cache-dir` 与启动器的 `UV_CACHE_DIR` 统一指向项目内 `.uv-cache/`，
直接执行 `uv run gui.py` 和启动器内部同步均不依赖 Windows 用户全局缓存目录的写权限。
该目录由 uv 管理并已忽略；不需要修改系统缓存 ACL 或重建 `.venv`。用户显式设置的
`UV_CACHE_DIR` 或 `--cache-dir` 仍可覆盖项目默认值。

`gui.py` 不直接信任 `.venv`：启动时用 `deploy/uv.py` 的 `dependency_sync_service` 做带超时与重试的依赖同步（pending 状态记录在 `module/runtime/setting.py`，崩溃后下次启动重做）。WebUI 服务有 120 秒就绪超时与最多 3 次重启；运行期检测到依赖标记时同样先同步再拉服务。

### 前端构建判据

`ensure_frontend` 对 `package.json`、`vite.config.ts`、`src/**`、`public/**` 做内容哈希（不依赖 git 检出时间），摘要变化才重建。这就是「改前端源码后不重启构建，界面不更新」的原因。

## 10. 配置

部署参数在 `config/deploy.yaml`（模型见 `deploy/config.py`）：git 仓库/分支/代理/SSL、Python 与 uv、镜像源、adb 替换与自动连接、OCR 服务器、更新检查间隔与自动重启时刻。安装器读它，WebUI 的部署设置页写它——两边经同一份文件交互。

## 11. 异常与错误处理

| 情况 | 处理 |
| --- | --- |
| 任一管理器抛 `ExecutionError` | 安装器 `exit(1)`，bat `pause` 停留展示日志 |
| uv sync 失败 | 输出 uv 日志（敏感文本经 `redact_sensitive_text` 脱敏）后中止 |
| git 418/镜像封禁 | 随机 git User-Agent + GitOverCdn 端点轮换兜底 |
| Windows 文件占用 | `atomic.py` 按重试上限等待后清理 |
| `.venv` 损坏 | `uv.py` 检测 python 不可用 → 自举重建 |

## 16. 修改注意事项

- **`PipManager` 名字是历史遗留**：它调用 `uv sync`，不要在其中加 pip 逻辑；依赖问题先查 `deploy/uv.py`。
- **`deploy/Windows/` 是旧布局副本**，主流程已用顶层 `deploy/*.py`；改安装逻辑改顶层，勿两边都改。
- **前端产物摘要机制**：只改 `dist/` 不改源码会被下次启动重建覆盖；发布产物请走正常构建。
- **随机 User-Agent、CDN 兜底是可用性关键**（国内网络），不要当可疑代码清理。
- `Alas.bat` 转 `AzurPilot.exe` 由外部工具完成，仓库只维护 bat。

## 17. 已知限制

- 模拟器自动探测仅支持 Windows 注册表可见的 VirtualBox 系模拟器；其他场景手动填 serial。
- 安装器假设能访问 git 远端或 CDN 端点；完全离线的首次安装不可行。

## 20. 相关模块

- [WebUI 启动器](../entry/gui.md) —— gui.py 的监督与依赖同步运行期行为
- [WebUI 总览](../webui/index.md) —— 更新事务与进程监督全貌
- [运行时服务](../webui/runtime.md) —— updater 与 installer 共享的依赖同步
- [外部桥接与开发工具](submodule-tools.md) —— dev_tools 中的生成器（CI 侧的对应物）

股票注册/删股联动版本需要同时更新 Python 与前端：新注册要求 noticeVersion 告知确认，股票被交易所删除后保存删除墓碑并停止上报。旧四类实例签名不变，reconcile 仅在能力已声明时启用。发布前备份完整 config/stock-exchange（包含 stocks-v2.json 与 stocks-retired-v2.json）；不要用回退旧同步代码恢复已删股票上传。仅更新上述股票接入组件，不更新调度或游戏脚本核心。
