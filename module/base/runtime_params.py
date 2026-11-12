"""运行参数集中定义。

本文件只包含纯字面量常量，零 import——部署与启动入口（deploy/、gui.py
及其 --tui 分支）在依赖尚未就绪的最早期阶段也需要导入其中部分常量，
因此这里不能引入任何模块，包括标准库。

两类内容：
1. 进程级参数：启动器与跨实例运行时服务使用，不存在“当前实例配置”
   的读取上下文，不开放到 WebUI 配置，直接 import 使用。
2. 配置兜底默认值：「运行参数」页（RunParams）各参数在配置读取失败
   或缺失时的回退值，与 module/config/argument/argument.yaml 中对应
   参数的 value 保持一致；修改默认值时两边同步。

各域以注释分节，搜索参数时优先按常量名全局搜索。
"""

# ==================== 配置兜底：调度与运行监护（RunParams.Watchdog） ====================

# 守护线程每 N 秒检查一次任务运行状态；任务执行期间若超过配置的
# 超时时间，则判定任务逻辑死循环，强制杀死模拟器进程以中断任务。
# 运行监护仅在任务执行阶段（self.run() 期间）激活，空闲等待（wait_until、
# 服务器维护检查）期间自动暂停，避免误触发。
WATCHDOG_CHECK_INTERVAL = 30
# 日报定时线程每 N 秒检查一次触发时刻，只有秒级精度的等待，取小值。
DAILY_SUMMARY_CHECK_INTERVAL = 1
# EmulatorManagement.RestartIntervalHours 读取失败时的兜底小时数
EMULATOR_RESTART_INTERVAL_HOURS_DEFAULT = 4
# Error.WatchdogTaskTimeout 读取失败时的兜底分钟数（0 表示禁用）
WATCHDOG_TASK_TIMEOUT_DEFAULT = 120

# ==================== 配置兜底：登录与重启（RunParams.Reboot） ====================

# 应用重启恢复策略：连续 N 次启动失败后进入观察阶段，观察期间仍无恢复
# 则由上层调度器执行模拟器重启，避免长时间无效重试。
RESTART_TRIES = 3
RESTART_FIRST_TRY_WAIT_SECONDS = 30
RESTART_SUBSEQUENT_TRY_WAIT_SECONDS = 20
RESTART_OBSERVE_SECONDS = 180
RESTART_OBSERVE_INTERVAL = 15
# 单次 app_stop/app_start 操作的硬超时秒数。
# 仅作为配置读取失败的兜底默认值；实际值从配置 Error.RestartOperationTimeout
# 读取，可在 WebUI「调试设置」中修改。
# atx-agent 自恢复可能耗时 70 秒以上，给 120 秒余量；超过则判定模拟器或
# atx-agent 卡死，立即抛出 EmulatorNotRunningError 触发模拟器重启，
# 避免 u2 调用无限挂起导致 LoginWaitTimeout / GameStuckRestart 等保护机制
# （依赖 screenshot() 中的 stuck_record_check）均无法触发的死锁。
RESTART_OPERATION_TIMEOUT = 120

# ==================== 配置兜底：设备与模拟器（RunParams.Device） ====================

# 启动监视期间打印进度的间隔（秒）。监视最长可达 480 秒且期间日志是静默的，
# 不打印进度的话，用户无法判断 ALAS 是在耐心等待还是已经卡死。
EMULATOR_START_PROGRESS_INTERVAL = 30
# 启动监视期间检查 MuMu 错误对话框的间隔（秒）。枚举窗口开销较大，不每次循环都做。
EMULATOR_START_DIALOG_CHECK_INTERVAL = 2
# 查询 MuMu12 实例状态的轮询间隔（秒）。同时用作无法查询状态时的兜底等待，
# 与旧版“等待2秒让进程状态稳定”保持一致。
MUMU12_STATE_POLL_INTERVAL = 2
# 确认 MuMu12 实例真正关闭的最长等待（秒）。
MUMU12_STOP_WAIT_TIMEOUT = 60
# 深度重启后等待全部 MuMu 进程退出的最长秒数（实测 5 秒内就干净了，留足余量）。
MUMU12_DEEP_WAIT_TIMEOUT = 30

# ==================== 进程级：设备连接重试 ====================

# ADB/u2 调用的重试次数与基础重试延迟（秒）。位于设备连接层装饰器与
# 独立工具函数内，不存在 config 读取上下文，且改动直接影响连接稳定性，
# 不开放到 WebUI 配置。
RETRY_TRIES = 5
RETRY_DELAY = 3
# 图像截断连续出现多少次后尝试恢复连接。
IMAGE_TRUNCATED_THRESHOLD = 3

# ==================== 配置兜底：录屏调试（RunParams.ScreenRecord） ====================

# 启动后等待录制进程存活的时间（秒）：立刻退出说明设备上根本跑不起来。
# 这里只拦「一行命令都跑不起来」的情况（例如设备没有 nohup），编码器起不来
# 会在收尾时通过设备端 stderr 报出来，所以不必在这里等太久。
SCREEN_RECORD_START_TIMEOUT = 0.6
# SIGINT 后等待 recorder 写完文件并退出的上限（秒）
SCREEN_RECORD_STOP_TIMEOUT = 6.0
# 轮询录制进程状态的间隔（秒）
SCREEN_RECORD_POLL_INTERVAL = 0.2
# 转码超时：按片段长度放宽（base + 时长×2），但不超过上限（秒）
TRANSCODE_BASE_TIMEOUT = 60.0
TRANSCODE_MAX_TIMEOUT = 600.0

# ==================== 进程级：录屏清理安全阀 ====================

# 残留临时文件（本地）的保留秒数；配小了会误删正在生成的录像，
# 清理节流同理，二者作为防误删安全阀不开放配置。
SCREEN_RECORD_TMP_MAX_AGE = 3600
# 清理节流：两次扫描目录至少间隔这么久
SCREEN_RECORD_CLEANUP_INTERVAL = 3600
# 单条 adb 命令的超时（秒）
ADB_TIMEOUT = 20

# ==================== 配置兜底：界面等待（RunParams.UiWait） ====================

# 岛屿地图跳转目的地的确认等待（秒）
ISLAND_MAP_CONFIRM_WAIT = 3
# 低端设备从岛屿地图跳转目的地时，场景加载可能明显超过 20 秒，
# 放宽进入目的地前的等待上限，避免加载稍慢即被误判为失败。
ISLAND_MAP_DESTINATION_WAIT = 45
# 目的地确认按钮只允许在点击后前 10 秒内补点重试，
# 防止地图一直停留在确认弹窗时反复点击同一按钮触发 GameTooManyClickError。
ISLAND_MAP_CONFIRM_RETRY_WAIT = 10
# 角色确认（选人页确认按钮）补点的最小间隔。必须大于云手机上「选人页→选餐页」的
# 转场时间，否则上一次点击已经生效、页面正在切换时仍会补点一次确认按钮，
# 而选餐页的确认按钮与角色页确认按钮坐标重叠，会把默认餐品直接下单。
ISLAND_CHARACTER_CONFIRM_RETRY_WAIT = 3
# 岛屿入口重试等待（秒）
ISLAND_ENTRY_RETRY_WAIT = 3
# 私人小屋交互各阶段的超时与点击间隔（秒）
PQ_INTERACT_BUTTON_TIMEOUT = 24
PQ_INTERACT_CLICK_WAIT = 8
PQ_INTERACT_START_TIMEOUT = 24
PQ_INTERACT_END_TIMEOUT = 40
PQ_INTERACT_EXIT_TIMEOUT = 24
# 建造数量面板的等待参数（秒）。帧数下限见下方 *_FRAMES：
# 云手机等慢设备上一帧截图要 2~4 秒，面板淡入本身也要几秒：
# 点击「开始建造/提交订单」后立刻再点一次，会点到面板外面（等同于点遮罩）
# 把面板关掉，形成「开面板 → 关面板」的交替，永远等不到 +/-。
# 因此重新点击必须同时满足秒数和帧数两个下限，整个等待另有超时兜底。
GACHA_PREP_SUBMIT_WAIT = 10
GACHA_PREP_TIMEOUT = 90
# 渠道服悬浮球拖拽的终点停留（秒）与最大尝试次数
CHANNEL_FLOAT_HOLD_DURATION = 0.2
CHANNEL_FLOAT_MAX_ATTEMPTS = 4
# 公会后勤：补给点击与兑换 BUG 处理的重试上限
GUILD_SUPPLY_MAX_RETRY = 2
GUILD_EXCHANGE_BUG_RETRY = 5
# 家具店检查间隔（天）
CHECK_INTERVAL = 6
# 换装完成后等待画面稳定的时间（秒）
AUTO_EQUIP_AFTER_EQUIP_WAIT = 3
# 委托：单个委托收到的绝对超时（秒）与奖励截图保留数量
COMMISSION_SKIP_TIMEOUT = 90
COMMISSION_REWARD_SCREENSHOT_KEEP = 50

# ==================== 配置兜底：作战交接（RunParams.Handover） ====================

# 消耗类作战委托执行失败后，推迟多少分钟重试。每次重试都要重新进一次
# 游戏，间隔过短会反复进游戏失败、白耗时间。
HANDOVER_CONSUME_RETRY_MINUTES = 30
# 维护开始前多少分钟做最后一次交接运行
HANDOVER_MAINTAIN_LEAD_MINUTES = 10
# 维护时间无法确认时，按多少分钟一轮反复核对
HANDOVER_MAINTAIN_CHECK_MINUTES = 120
# 交接冲突时推迟多少分钟重试，避免把任务排到过去
HANDOVER_CONFLICT_RETRY_MINUTES = 15

# ==================== 进程级：界面等待帧数下限 ====================

# 以下帧数与对应的秒数参数成对使用（Timer(sec, count=frames)）：
# 重新点击必须同时满足秒数和帧数两个下限，防止慢设备上截图太慢
# 导致「秒数还没到但画面早已变化」的误点击。帧数是截图节奏的内部
# 语义，与秒数强耦合，不开放配置。
GACHA_PREP_SUBMIT_WAIT_FRAMES = 2
GACHA_PREP_TIMEOUT_FRAMES = 20


# ==================== 进程级：调度器（alas.py） ====================

# 模拟器 stop/start 单次操作的硬超时秒数。
# 必须覆盖 PlatformWindows.emulator_start() 的完整预算，一次调用最多：
#   关闭 30 + 深度清场 90（关全部实例≤60 + 等进程退出≤30） + 等实例真正关闭 60
#   + 启动监视 300（阶梯上限） = 480 秒
# 普通路径没有深度清场那 90 秒（实测 390 秒封顶），但按最坏情况取。
# 取 600 秒：宁可慢，也不能在模拟器正在启动时放弃——超时被放弃的
# worker 线程仍会继续对模拟器执行关/开操作，是历史上“模拟器永远起不来”
# 的根因（原值 120 秒 < 内层 180 秒监视超时，必然超时、必然残留）。
# 残留线程由 PlatformWindows 的启停互斥锁兜底：它结束之前，任何新的
# 启停操作都会抛 EmulatorOpBusy 被跳过，不会再打断正在进行的启动。
RESTART_EMULATOR_OP_TIMEOUT = 600

# ==================== 进程级：WebUI 启动器（gui.py） ====================

# 等待 WebUI 后端就绪的超时（秒）
WEBUI_READY_TIMEOUT = 120
# WebUI 子进程启动/运行异常时的重试次数上限
WEBUI_START_RETRY_LIMIT = 3
WEBUI_RUNTIME_RETRY_LIMIT = 3
# 子进程连续稳定运行超过该秒数后，重试计数归零
WEBUI_STABLE_RUNTIME = 60
# 启动阶段依赖同步（uv sync）的重试次数上限
DEPENDENCY_SYNC_START_RETRY_LIMIT = 3

# 注：deploy/ 包保持零项目依赖（无 module 包的独立运行环境，如安装器/
# 引导阶段），其常量（WINDOWS_MAX_ATTEMPT 等）留在 deploy/ 原处，不收拢。

# ==================== 进程级：运行时服务（module/runtime/、module/api/） ====================

# 本地控制命令（launcher → 子进程）的请求超时（秒）
COMMAND_TIMEOUT = 10
# 控制连接的空闲过期时间（秒）
CONNECTION_EXPIRE = 45
# 免密令牌有效期（秒），短时一次性
TOKEN_TTL_SECONDS = 60
# worker 注册表文件锁的等待超时（秒）
REGISTRY_LOCK_TIMEOUT = 10.0
# 注册表文件锁的重试间隔（秒）
REGISTRY_LOCK_RETRY_INTERVAL = 0.05
# 已鉴权 SSE 会话的有效期（秒），每次成功 POST 滑动续期：12 小时
SESSION_TTL_SECONDS = 12 * 3600
# SSE 断开后的宽限期（秒），避免客户端最后一帧 POST 被误拒
SESSION_DISCONNECT_GRACE_SECONDS = 60
# 会话登记表容量上限，超出按插入顺序淘汰
SESSION_MAX_ENTRIES = 512
# 远程访问 P2P 打洞的建连超时（秒）
P2P_SETUP_TIMEOUT = 60
# SSH 隧道重连的初始等待（秒），指数退避
SSH_RECONNECT_DELAY = 2
# SSH 隧道重连等待的上限（秒）
SSH_RECONNECT_MAX_DELAY = 30
# 更新触发重启的标记文件有效期（秒）：30 分钟
UPDATE_RESTART_TTL = 1800
# 资源统计拉取外部资源时的单请求超时（秒）
DOWNLOAD_TIMEOUT = 10

# ==================== 进程级：统计与清理（module/statistics/、module/base/） ====================

# 日报统计的保留天数
DAILY_SUMMARY_KEEP_DAYS = 35
# 日报 LLM 生成与通知推送的尝试次数
DAILY_SUMMARY_LLM_ATTEMPTS = 3
DAILY_SUMMARY_NOTIFY_ATTEMPTS = 3
# 掉落截图目录清理的节流间隔（秒）
DROP_SCREENSHOT_CLEANUP_INTERVAL = 3600
# 配置/数据库备份的保留天数
BACKUP_KEEP_DAYS = 7
# 茗交所存储迁移文件锁的等待超时（秒）
MIGRATION_LOCK_TIMEOUT = 20.0
# 茗交所存储解密失败后的重试等待（秒）
DECODER_RETRY_INTERVAL = 60.0
