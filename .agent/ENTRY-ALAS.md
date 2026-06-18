---
description:
alwaysApply: true
---

# alas.py 入口文件深度分析

## 1. 文件基础信息

| 项目 | 内容 |
|---|---|
| 文件路径 | `alas.py` |
| 总行数 | 1138 行 |
| 文件类型 | Python 脚本（主入口 + 核心调度器类） |
| 许可证 | GPL-3.0 |
| 修改注释 | 基于原版增加了自动尝试重启调度器的功能（rev: auto_restart, Last Updated: 2025-09-01） |

### 导入依赖

| 模块来源 | 具体导入 | 用途 |
|---|---|---|
| 标准库 | `json`, `os`, `re`, `shutil`, `threading`, `time`, `datetime`, `subprocess`, `tempfile` | 文件操作、正则、线程、时间、进程 |
| 第三方 | `inflection` | 驼峰/下划线命名转换（任务名 -> 方法名） |
| 第三方 | `cached_property` | 惰性属性缓存 |
| 项目内部 | `module.base.decorator.del_cached_property` | 清除缓存属性 |
| 项目内部 | `module.base.api_client.ApiClient` | Bug 日志上报 |
| 项目内部 | `module.config.config.AzurLaneConfig, TaskEnd` | 配置系统 |
| 项目内部 | `module.config.deep.deep_get, deep_set` | 嵌套字典操作 |
| 项目内部 | `module.config.utils.filepath_i18n, read_file` | i18n 路径和文件读取 |
| 项目内部 | `module.exception.*` | 全部自定义异常类（通配符导入） |
| 项目内部 | `module.logger.logger` | 日志系统 |
| 项目内部 | `module.notify.handle_notify, notify_webui` | 推送通知 |

---

## 2. 模块级全局变量与函数

### 2.1 `_i18n_task_names` 缓存 (L27)

```python
_i18n_task_names = None
```

全局模块级缓存，用于存储 i18n 任务名称映射字典。首次调用 `_get_task_display_name()` 时从文件加载并缓存。

### 2.2 `_get_task_display_name(task_command)` (L28-L53)

```python
def _get_task_display_name(task_command):
    """从 i18n 获取任务的本地化显示名，找不到则返回英文名"""
```

- **功能**: 根据任务命令名获取本地化显示名称
- **参数**: `task_command` (str) - 任务命令名（如 `'Research'`）
- **返回**: `str` - 本地化名称或原始命令名
- **执行流程**:
  1. 首次调用时，从 `config/deploy.yaml` 读取语言设置（默认 `zh-CN`）
  2. 加载对应的 i18n JSON 文件，提取 `Task` 节点下的 `name` 字段
  3. 构建 `{command: display_name}` 映射并缓存到 `_i18n_task_names`
  4. 后续调用直接查缓存
- **设计模式**: 模块级单例缓存模式
- **容错**: 所有异常均被静默捕获，失败时返回原始命令名

### 2.3 `RESTART_SENSITIVE_TASKS` (L56)

```python
RESTART_SENSITIVE_TASKS = ['Commission', 'Research']
```

重启敏感任务列表。当 `Error_StrictRestart` 启用且这些任务失败 >=1 次时，会触发程序终止请求人工接管。

---

## 3. `AzurLaneAutoScript` 类分析 (L59-L1137)

### 3.1 类定义与类属性

```python
class AzurLaneAutoScript:
    stop_event: threading.Event = None
```

- **类型注解**: `stop_event` 是类级别的 `threading.Event`，用于从外部（如 GUI 进程）通知调度器停止
- **设计**: 类属性默认为 `None`，由 GUI 层在创建实例时注入

### 3.2 `__init__(self, config_name='alas')` (L62-L74)

```python
def __init__(self, config_name='alas'):
```

- **参数**: `config_name` (str) - 配置实例名称，默认 `'alas'`
- **初始化状态**:
  - `self.config_name` - 配置实例名
  - `self.is_first_task` (bool) - 标记是否为首次任务（用于跳过启动时的 Restart）
  - `self.failure_record` (dict) - 任务失败计数器 `{task_name: failure_count}`
  - `self.consecutive_game_stuck` (int) - 连续游戏卡死次数
  - `self.consecutive_adb_offline` (int) - 连续 ADB 离线次数
  - `self.last_emulator_restart_time` (float) - 上次模拟器重启时间戳

---

### 3.3 惰性缓存属性

#### `config` (L129-L139)

```python
@cached_property
def config(self):
    config = AzurLaneConfig(config_name=self.config_name)
    return config
```

- **类型**: `AzurLaneConfig`
- **惰性加载**: 首次访问时从 `config/{config_name}.json` 加载配置
- **错误处理**: `RequestHumanTakeover` 致命退出，其他异常记录后退出

#### `device` (L141-L152)

```python
@cached_property
def device(self):
    from module.device.device import Device
    device = Device(config=self.config)
    return device
```

- **类型**: `Device`（多重继承：`Screenshot + Control + AppControl + Input`）
- **惰性导入**: 内部导入避免启动时就连接设备
- **依赖**: 需要 `self.config` 先初始化

#### `checker` (L154-L162)

```python
@cached_property
def checker(self):
    from module.server_checker import ServerChecker
    checker = ServerChecker(server=self.config.Emulator_ServerName)
    return checker
```

- **类型**: `ServerChecker`
- **功能**: 游戏服务器可用性检查器，调用外部 API 检测服务器状态

---

### 3.4 核心方法 `run(self, command, skip_first_screenshot=False)` (L168-L347)

```python
def run(self, command, skip_first_screenshot=False):
```

**这是整个调度器的任务执行核心方法。**

- **参数**:
  - `command` (str) - 任务方法名（下划线格式，如 `'research'`）
  - `skip_first_screenshot` (bool) - 是否跳过首次截图
- **返回值**:
  - `True` - 任务成功完成
  - `False` - 任务失败且不可恢复（计入失败限制）
  - `'recoverable'` - 任务失败但可恢复（不计入失败限制）

**执行流程**:
1. 截图（除非 `skip_first_screenshot=True`）
2. 通过 `self.__getattribute__(command)()` 动态调用对应任务方法
3. 根据异常类型进行分级错误处理

**异常处理矩阵**:

| 异常类型 | 处理策略 | 返回值 | 是否通知 | 是否重启 |
|---|---|---|---|---|
| `TaskEnd` | 正常结束 | `True` | 否 | 否 |
| `GameNotRunningError` | 调度 Restart 任务 | `'recoverable'` | 是 (onepush + webui) | 游戏重启 |
| `GameStuckError` / `GameTooManyClickError` | 保存日志，尝试重启模拟器 | `'recoverable'` | 是 | 可能模拟器重启 |
| `GameBugError` | 重启游戏修复客户端 bug | `'recoverable'` | 是 | 游戏重启 |
| `GamePageUnknownError` | 检查服务器状态，等待恢复 | `False` 或 `exit(1)` | 是 | 视情况 |
| `ScriptError` | 开发者错误，终止 | `raise` | 是 | 否 |
| `EmulatorNotRunningError` | 尝试重启模拟器 | `'recoverable'` 或 `exit(1)` | 是 | 模拟器重启 |
| `RequestHumanTakeover` | 不可恢复，终止 | `exit(1)` | 是 | 否 |
| `AutoSearchSetError` | 配置错误，终止 | `exit(1)` | 否 | 否 |
| 其他 `Exception` | 保存日志，终止 | `raise` | 是 | 否 |

**关键设计点**:
- `'recoverable'` 返回值不计入失败次数限制，这是可恢复错误的核心机制
- `GameStuckError` 和 `GameTooManyClickError` 有专门的连续卡死计数器，达到阈值时尝试重启模拟器而非仅重启游戏
- 所有错误处理路径都包含 `handle_notify`（onepush 推送）和 `notify_webui`（WebUI 通知）双重通知

---

### 3.5 `_try_restart_emulator(self)` (L76-L127)

```python
def _try_restart_emulator(self):
```

- **功能**: 尝试重启模拟器
- **前置条件**: `Error_AdbOfflineRestart` 配置启用且未达到重试上限
- **返回**: `bool` - 是否成功重启
- **执行流程**:
  1. 检查配置是否启用重启
  2. 递增 `consecutive_adb_offline` 计数器
  3. 检查是否超过阈值 `Error_AdbOfflineThreshold`
  4. 尝试复用现有的 `self.device` 对象（含 `emulator_instance` 缓存）
  5. 若 device 未初始化，根据平台回退创建 `PlatformWindows` 或 `PlatformMac`
  6. 调用 `device.emulator_stop()` -> sleep(5) -> `device.emulator_start()`
  7. 清除 device 缓存以强制重建连接
- **平台适配**: 区分 `sys.platform == 'darwin'` (macOS) 和其他平台 (Windows)

---

### 3.6 `keep_last_errlog(self, folder_path, n=30)` (L349-L366)

```python
def keep_last_errlog(self, folder_path, n: int = 30):
```

- **功能**: 保留错误日志目录中最后 n 个子文件夹，删除旧的
- **参数**: `folder_path` (str) - 目录路径, `n` (int) - 保留数量
- **行为**: `n <= 0` 时不执行任何操作

### 3.7 `save_error_log(self)` (L368-L420)

```python
def save_error_log(self):
```

- **功能**: 保存错误现场（截图 + 日志）到 `./log/error/<config-name>/<timestamp>/`
- **执行流程**:
  1. **LLM 分析优先** (L379-L387): 如果启用了 `Error_LlmAnalysis`，先调用 `module.llm.analyze_exception()` 进行 AI 错误分析（避免后续保存截图时二次崩溃导致分析未执行）
  2. **截图保存** (L395-L403): 从 `device.screenshot_deque` 获取最近截图，进行敏感信息遮罩后保存
  3. **日志保存** (L405-L418): 读取日志文件，提取最后一个分隔线之后的内容，进行敏感信息遮罩后保存
  4. **清理旧日志** (L420): 调用 `keep_last_errlog()` 限制日志数量

**安全性**: 使用 `handle_sensitive_image` 和 `handle_sensitive_logs` 处理敏感信息

---

### 3.8 基础任务方法 (L422-L441)

#### `restart()` (L422-L425)
```python
def restart(self):
    LoginHandler(self.config, device=self.device).app_restart()
    self.config.task_delay(server_update=True)
```
重启游戏应用并设置下次运行时间。

#### `start()` (L427-L429)
启动游戏应用（不等待完成）。

#### `goto_main()` (L431-L440)
导航到游戏主页面。如果应用已运行则直接导航，否则先启动。

---

### 3.9 游戏任务方法 (L442-L737)

共 **55 个任务方法**，每个方法遵循统一模式：

```python
def task_name(self):
    from module.xxx.xxx import TaskClass
    TaskClass(config=self.config, device=self.device).run()
```

**任务分类与模块映射**:

| 类别 | 方法名 | 处理器模块 | 说明 |
|---|---|---|---|
| **科研** | `research` | `module.research.research.RewardResearch` | 科研项目 |
| **委托** | `commission` | `module.commission.commission.RewardCommission` | 委托收发 |
| **战术** | `tactical` | `module.tactical.tactical_class.RewardTacticalClass` | 战术学院 |
| **宿舍** | `dorm` | `module.dorm.dorm.RewardDorm` | 宿舍管理 |
| **指挥喵** | `meowfficer` | `module.meowfficer.meowfficer.RewardMeowfficer` | 指挥喵 |
| **大舰队** | `guild` | `module.guild.guild_reward.RewardGuild` | 大舰队 |
| **奖励** | `reward` | `module.reward.reward.Reward` | 奖励收取 |
| **觉醒** | `awaken` | `module.awaken.awaken.Awaken` | 觉醒系统 |
| **商店** | `shop_frequent` / `shop_once` | `module.shop.shop_reward.RewardShop` | 商店（频繁/一次性） |
| **活动商店** | `event_shop` | `module.shop_event.shop_event.EventShop` | 活动商店 |
| **船坞** | `shipyard` | `module.shipyard.shipyard_reward.RewardShipyard` | 船坞 |
| **建造** | `gacha` | `module.gacha.gacha_reward.RewardGacha` | 建造系统 |
| **免费福利** | `freebies` | `module.freebies.freebies.Freebies` | 免费福利 |
| **小游戏** | `minigame` | `module.minigame.minigame.Minigame` | 小游戏 |
| **私人休息室** | `private_quarters` | `module.private_quarters.private_quarters.PrivateQuarters` | 私人休息室 |
| **岛屿** | `island` | `module.island.island.Island` | 岛屿系统 |
| **每日** | `daily` | `module.daily.daily.Daily` | 每日任务 |
| **困难** | `hard` | `module.hard.hard.CampaignHard` | 困难模式 |
| **演习** | `exercise` | `module.exercise.exercise.Exercise` | 演习 PvP |
| **SOS** | `sos` | `module.sos.sos.CampaignSos` | SOS 任务 |
| **作战档案** | `war_archives` | `module.war_archives.war_archives.CampaignWarArchives` | 作战档案 |
| **突袭** | `raid_daily` / `raid` / `raid_scuttle` | `module.raid.*` | 突袭任务 |
| **活动** | `event_a/b/c/d/sp` | `module.event.campaign_abcd/sp` | 活动战役 (A-D, SP) |
| **护航** | `maritime_escort` | `module.event.maritime_escort.MaritimeEscort` | 海上护航 |
| **大世界** | `opsi_*` (12个) | `module.campaign.os_run.OSCampaignRun` | 大世界各种任务 |
| **主线** | `main/main2/main3` | `module.campaign.run.CampaignRun` | 主线战役（3个槽位） |
| **活动战役** | `event/event2/event3` | `module.campaign.run.CampaignRun` | 活动战役（3个槽位） |
| **联动** | `coalition/coalition_sp` | `module.coalition.*` | 联动活动 |
| **医院** | `hospital/hospital_event` | `module.event_hospital.*` | 医院活动 |
| **守护** | `daemon/opsi_daemon` | `module.daemon.*` | 守护模式 |
| **剧情** | `event_story` | `module.eventstory.eventstory.EventStory` | 活动剧情 |
| **拆箱** | `box_disassemble` | `module.storage.box_disassemble.StorageBox` | 箱子拆解 |
| **特殊** | `azur_lane_uncensored` | `module.daemon.uncensored.AzurLaneUncensored` | 去遮罩 |
| **测试** | `benchmark/ocr_benchmark` | `module.daemon.*` | 性能基准测试 |
| **管理** | `game_manager/emulator_manager` | `module.daemon.game_manager/手动SSH` | 游戏/模拟器管理 |

**注意**: `main/main2/main3` 和 `event/event2/event3` 以及 `c72_mystery_farming`、`c122_medium_leveling`、`c124_large_leveling`、`gems_farming`、`three_oil_low_cost` 都是调用同一个 `CampaignRun.run()`，通过配置区分具体战役。

---

### 3.10 `emulator_manager()` (L738-L851) - 特殊方法

```python
def emulator_manager(self):
```

这是唯一一个不遵循统一模式的任务方法，直接在 `alas.py` 中实现了完整的 SSH 远程命令执行逻辑。

- **功能**: 通过 SSH 远程执行模拟器管理命令
- **配置来源**: 优先 `EmulatorInfo_*` 配置，回退到 `EmulatorManager.EmulatorManager.*`
- **SSH 参数**: `-n -T -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=10`
- **密钥处理**: 支持内联私钥（长度 > 50 时写入临时文件），Windows 上使用 `icacls` 设置权限
- **执行**: 使用 `subprocess.Popen`，30 秒超时，分离的 stdout/stderr 收集线程
- **安全**: 临时密钥文件在 `finally` 块中清理

---

### 3.11 `wait_until(self, future)` (L853-L877)

```python
def wait_until(self, future):
```

- **功能**: 等待直到指定时间，同时监控配置变更和停止事件
- **参数**: `future` (datetime) - 目标时间
- **返回**: `True` (等待完成), `False` (配置已更改，需要重新加载)
- **轮询间隔**: 5 秒
- **特性**:
  - 加 1 秒缓冲 (`future + timedelta(seconds=1)`)
  - 使用 `ConfigWatcher` 检测配置文件变更
  - 检查 `stop_event` 响应外部停止信号

---

### 3.12 `get_next_task(self)` (L879-L934)

```python
def get_next_task(self):
```

- **功能**: 获取下一个待执行的任务
- **返回**: `str` - 任务命令名
- **执行流程**:
  1. 调用 `config.get_next()` 获取优先级最高的任务
  2. 绑定任务配置 (`config.bind(task)`)
  3. 释放非当前任务的资源缓存 (`release_resources()`)
  4. 如果任务的 `next_run` 在未来，进入等待逻辑
  5. 等待期间根据 `Optimization_WhenTaskQueueEmpty` 设置执行不同策略：
     - `close_game` - 关闭游戏释放资源，等待后重启
     - `goto_main` - 导航到主页面，等待后继续
     - `stay_there` - 停留在当前页面，等待后继续
  6. 等待过程中持续监听配置变更（`wait_until()` 返回 `False` 时重新开始循环）

**任务优先级** (按代码注释): `Restart > OpsiCrossMonth > Commission > Tactical > Research > Exercise > Dorm > Meowfficer > Guild > Gacha > Reward > ShopFrequent > ... > Main > Main2 > Main3 > GemsFarming`

---

### 3.13 `loop(self)` (L936-L1137) - 主调度循环

```python
def loop(self):
```

**这是整个程序的主入口循环，实现了完整的任务调度、错误恢复和生命周期管理。**

- **功能**: 无限循环调度任务，处理错误，监控状态
- **常量**:
  - `MAX_GLOBAL_FAILURES = 3` - 全局最大连续失败次数
  - `RESTART_DELAY = 20` - 重启等待秒数
  - `LONG_WAIT = 300` - 长等待秒数（第 4 次及以上连续失败）

**执行流程**:

```
loop()
  ├── 检查 OOBE (首次配置)
  ├── while True:
  │   ├── 检查 stop_event (GUI 更新信号)
  │   ├── checker.wait_until_available() (服务器维护检测)
  │   ├── 检查计划的模拟器重启 (EmulatorManagement_ScheduledEmulatorRestart)
  │   ├── get_next_task() 获取下一个任务
  │   ├── 初始化 device
  │   ├── 跳过首次 Restart 任务
  │   ├── 清除卡死/点击记录
  │   ├── run(task) 执行任务
  │   ├── 每任务推送通知 (Scheduler_PushNotification)
  │   ├── 失败计数管理:
  │   │   ├── success=True -> 重置计数
  │   │   ├── success='recoverable' -> 不计入
  │   │   └── success=False -> 递增计数
  │   ├── 连续失败 >= 3 次 -> RequestHumanTakeover
  │   ├── success=True -> 继续下一个任务
  │   └── success=False -> 退出循环
  │
  └── except Exception (全局异常捕获):
      ├── 递增 consecutive_global_failures
      ├── LLM 错误分析
      ├── 达到 MAX_GLOBAL_FAILURES -> 保存日志, exit(1)
      └── 未达到 -> 注入 Restart 任务, 等待后重试
```

**关键设计**:

1. **双重错误恢复**: 单个任务的 `run()` 方法处理任务级异常，`loop()` 的 `try/except` 处理未预期的全局异常
2. **分级等待策略**: 连续失败 < 4 次等 20 秒，>= 4 次等 300 秒（防网络波动）
3. **计划模拟器重启**: 在任务间检查是否需要定时重启模拟器，不中断正在运行的任务
4. **服务器维护检测**: 通过 `ServerChecker` API 检测游戏服务器状态
5. **配置热重载**: 通过 `del_cached_property(self, 'config')` 清除缓存，下次访问时重新加载
6. **LLM 错误分析**: 全局异常时第一时间调用 AI 分析崩溃原因

---

### 3.14 `__main__` 入口 (L1135-L1137)

```python
if __name__ == '__main__':
    alas = AzurLaneAutoScript()
    alas.loop()
```

默认创建 `'alas'` 配置实例并启动调度循环。

---

## 4. 数据结构分析

### 4.1 内部状态数据结构

```python
# 任务失败记录
failure_record: Dict[str, int] = {}
# 示例: {'Commission': 2, 'Research': 0}

# i18n 任务名缓存
_i18n_task_names: Dict[str, str] = {}
# 示例: {'Research': '科研', 'Commission': '委托'}
```

### 4.2 配置数据结构 (通过 `AzurLaneConfig` 访问)

```python
config.data: Dict[str, Dict]  # 原始 JSON 配置
# 结构: {TaskName: {Group: {Arg: Value}}}

config.modified: Dict[str, Any]  # 修改追踪
# 结构: {path: value} 如 {'Scheduler.NextRun': '2025-01-01 00:00:00'}
```

---

## 5. 模块内部调用关系

```
alas.py
  ├── AzurLaneConfig (module.config.config)
  │   ├── ConfigUpdater - 配置更新和模板合并
  │   ├── ManualConfig - 手动配置
  │   ├── GeneratedConfig - 自动生成的配置属性
  │   └── ConfigWatcher - 文件变更监控
  │
  ├── Device (module.device.device) - 惰性加载
  │   ├── Screenshot - 截图捕获
  │   ├── Control - 设备控制
  │   ├── AppControl - 应用管理
  │   └── Input - 输入模拟
  │
  ├── ServerChecker (module.server_checker) - 惰性加载
  │
  ├── 55 个任务处理器 (module.*.*) - 全部惰性加载
  │   └── 每个处理器继承 ModuleBase, 实现 run()
  │
  ├── LoginHandler (module.handler.login)
  │
  ├── handle_notify / notify_webui (module.notify)
  │
  ├── ApiClient (module.base.api_client)
  │
  └── LLM 分析 (module.llm) - 可选
```

---

## 6. 设计模式与架构分析

### 6.1 设计模式

| 模式 | 应用位置 | 说明 |
|---|---|---|
| **命令模式** | `run(command)` + 55 个任务方法 | 通过方法名动态分发任务 |
| **策略模式** | `get_next_task()` 中的 `Optimization_WhenTaskQueueEmpty` | 空闲时不同行为策略 |
| **惰性初始化** | `config`, `device`, `checker` 的 `@cached_property` | 按需加载重资源 |
| **观察者模式** | `ConfigWatcher` + `stop_event` | 监听配置变更和停止信号 |
| **模板方法** | 所有任务方法遵循相同模式 | 统一的 `import -> 实例化 -> run()` |
| **装饰器模式** | `@cached_property`, `del_cached_property` | 属性缓存管理 |

### 6.2 架构风格

- **调度器架构**: 中心化的任务调度循环，基于优先级的任务选择
- **模块化**: 每个游戏功能独立为一个模块，通过统一接口集成
- **事件驱动**: 通过 `threading.Event` 实现进程间通信
- **防御式编程**: 多层异常处理，分级错误恢复

---

## 7. 性能分析

### 7.1 性能瓶颈

| 位置 | 瓶颈 | 原因 | 优化建议 |
|---|---|---|---|
| `device.screenshot()` | 截图捕获 | ADB 传输延迟 ~350ms | 已使用 deque 缓存 |
| `run()` 中的任务执行 | 任务处理 | 图像匹配 + OCR | 模块级优化 |
| `wait_until()` | 空闲等待 | 5 秒轮询间隔 | 可接受 |
| `emulator_manager()` | SSH 命令 | 30 秒超时 | 已有超时控制 |

### 7.2 资源管理

- **截图缓存**: `device.screenshot_deque` 存储最近截图用于错误日志
- **资源释放**: `release_resources(next_task=task.command)` 在任务间释放非必要资源
- **缓存清除**: `del_cached_property()` 强制重新加载配置和设备连接

### 7.3 内存考虑

- `_i18n_task_names` 全局缓存仅在首次调用时加载一次
- 任务处理器通过惰性导入避免启动时加载所有模块
- 错误日志限制保留数量 (`Error_SaveErrorCount`)

---

## 8. 安全性分析

### 8.1 已实现的安全措施

| 措施 | 位置 | 说明 |
|---|---|---|
| 敏感信息遮罩 | `save_error_log()` | 使用 `handle_sensitive_image` 和 `handle_sensitive_logs` |
| SSH 密钥临时文件权限 | `emulator_manager()` | Windows: `icacls`, Unix: `chmod 0o600` |
| SSH 超时控制 | `emulator_manager()` | 30 秒超时 + BatchMode |
| SSH StrictHostKeyChecking | `emulator_manager()` | `=no` (接受所有主机密钥) |
| 错误日志数量限制 | `keep_last_errlog()` | 防止磁盘空间耗尽 |

### 8.2 潜在安全风险

| 风险 | 位置 | 严重程度 | 说明 |
|---|---|---|---|
| SSH 主机密钥未验证 | `emulator_manager()` L772 | 中 | `StrictHostKeyChecking=no` 可能遭受 MITM 攻击 |
| 临时密钥文件残留 | `emulator_manager()` L847-L851 | 低 | `except: pass` 静默忽略删除失败 |
| 通配符异常导入 | L22 | 低 | `from module.exception *` 可能引入意外名称 |
| LLM API 密钥暴露 | `save_error_log()` | 中 | 错误日志中可能包含 API 密钥 |

---

## 9. 代码质量评估

### 9.1 优点

1. **完善的错误恢复机制**: 分级异常处理，可恢复/不可恢复错误区分明确
2. **模块化设计**: 每个任务独立模块，通过惰性导入避免启动开销
3. **双重通知系统**: onepush + webui 确保用户不会错过重要事件
4. **配置热重载**: 通过 `ConfigWatcher` 实现无需重启的配置更新
5. **资源管理**: 任务间资源释放，空闲时多种策略
6. **LLM 集成**: AI 错误分析提高问题诊断效率

### 9.2 问题与不足

1. **`run()` 方法过长** (180 行): 异常处理逻辑可以提取为独立的错误处理策略类
2. **`loop()` 方法过长** (200 行): 全局异常处理和任务调度逻辑可分离
3. **通配符导入** (`from module.exception *`): 不利于代码分析和 IDE 支持
4. **硬编码字符串**: 日志消息中的 emoji 和口语化表达可能影响国际化
5. **`emulator_manager()` 内联**: SSH 逻辑直接嵌入任务方法，违反单一职责原则
6. **注释不一致**: 部分使用英文，部分使用中文
7. **类型注解不完整**: 大多数方法缺少返回值和参数类型注解

---

## 10. 潜在问题与改进建议

### 10.1 潜在 Bug

1. **`run()` 返回值类型不一致**: `True`/`False`/`'recoverable'` 混合，建议使用枚举
2. **`emulator_manager()` 中的 `subprocess.Popen`**: 未在 Windows 上正确处理信号传播
3. **`save_error_log()` 中的 `sys.exc_info()`**: 在异步上下文中可能返回 `(None, None, None)`
4. **`loop()` 中的 `del_cached_property(self, 'config')`**: 在某些异常路径下 config 可能未初始化

### 10.2 改进建议

1. **引入任务结果枚举**:
   ```python
   class TaskResult(Enum):
       SUCCESS = 'success'
       FAILURE = 'failure'
       RECOVERABLE = 'recoverable'
   ```

2. **提取错误处理器**:
   ```python
   class ErrorHandler:
       def handle_game_stuck(self, error): ...
       def handle_emulator_offline(self, error): ...
       def handle_game_bug(self, error): ...
   ```

3. **使用依赖注入**: 替代 `self.__getattribute__(command)()` 的动态分发

4. **添加类型注解**: 提高代码可维护性

5. **分离 SSH 逻辑**: 将 `emulator_manager()` 中的 SSH 代码移到 `module/device/platform/` 下

6. **使用结构化日志**: 替代当前的字符串格式化日志
