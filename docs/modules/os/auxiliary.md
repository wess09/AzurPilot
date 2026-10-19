# 大世界辅助模块（os_handler / os_ash / os_combat / os_shop / os_simulator）

> 环绕 `module/os` 的五个辅助包：弹窗与资源处理器、余烬信标、大世界战斗、大世界商店、行动力模拟器。

## 1. 模块概述

`module/os`（见[大世界核心](index.md)）编排任务流，但支撑它的识别与操作能力分散在五个辅助包里。它们的存在理由各不相同：

- **os_handler** 是「大世界版处理器层」。大世界的弹窗、行动力面板、仓库、任务列表与主包共用一套状态循环，但识别资源与行为差异极大，独立成包避免污染通用 handler。
- **os_ash** 处理余烬（META）体系：信标收集、信标攻击、信标协助。它与大世界联动（战斗结算会检查信标收集进度）但有自己的页面与调度节奏，因此单独成包。
- **os_combat** 只有一件事：把通用 `Combat` 适配到大世界的结算时序（连续战斗、S 评价自动点击、掉落收集）。
- **os_shop** 实现大世界两类商店（港口商店、明石商店）的货架扫描与购买策略，被 `PortHandler` 与智能调度的购买流程复用。
- **os_simulator** 是一个离线蒙特卡洛模拟器，估算不同侵蚀等级刷黄币的收益。WebUI 的「大世界模拟器 Alpha」页面通过 `opsi.simulator.*` 接口控制它，独立于游戏调度器。

前四个包作为 mixin 汇入 `OSMap` 或其任务类；模拟器由 WebUI 运行时服务独立管理。

## 2. 模块职责

### 负责

- **os_handler**：行动力面板（读取/购买/保留校验）、大世界弹窗与地图事件（`MapEventHandler`）、仓库（坐标/修理包/日志仪/调谐样本）、港口进出与维修、任务（mission）接取与区域识别、状态读取（黄币/紫币/上下文判断）、战略搜索（激光扫描）、目标（海域成就）、作战指令（map order）、雾天敌搜适配。
- **os_ash**：META 页面导航与状态机（`MetaState`）、信标攻击任务（`OpsiAshBeacon`）、信标协助（`AshBeaconAssist`）、战斗中信标进度的采集与任务触发（`handle_ash_beacon_attack`）。
- **os_combat**：`ContinuousCombat`（塞壬扫描装置连续战斗）异常、大世界战斗准备/结算的覆写（`_os_combat_expected_end`、`_handle_auto_battle_status_s`）。
- **os_shop**：港口/明石商店的 `ItemGrid` 扫描、货币判定（黄币/紫币）、购买循环与数量输入、货架策略（`Selector`）。
- **os_simulator**：Numba 加速的刷币收益模拟（`start()` 起后台线程、`interrupt()` 中断），参数从 `OpsiSimulatorParameters` 配置读取。

### 不负责

- 任务编排与导航——见[大世界核心](index.md)。
- 通用弹窗（登录、委托、退役）与普通地图事件——见[处理器层](../handler.md)。
- 大世界以外的商店（通用商店框架见[商店系统](../game/shop.md)）。
- 仓库箱子的拆解（`module/storage` 是普通仓库的同名 `StorageHandler`，与大世界的类**同名不同实现**，勿混淆）。

## 3. 模块位置

```
module/os_handler/    # 约 3000 行，12 个功能文件 + assets
├── action_point.py   # 行动力面板全套（读/买/限/溢出）
├── resource_state.py # 任务上下文、库存版本与运行期缓存失效
├── map_event.py      # MapEventHandler：地图事件、舰队锁开关、自动搜索收尾
├── storage.py        # StorageHandler：大世界仓库（隐秘坐标/修理/日志仪）
├── os_status.py      # OSStatus：黄币/紫币 OCR 与任务上下文判断
├── port.py           # PortHandler：港口进出、维修、接任务
├── mission.py        # MissionHandler：任务接取、is_in_opsi_explore
├── strategic.py      # StrategicSearchHandler：战略搜索（激光）
├── target.py         # OSTargetHandler：海域成就（TARGET_SWITCH 选择器）
├── map_order.py      # MapOrderHandler：作战指令（潜艇呼叫/侦察扫描冷却）
├── enemy_searching.py# 雾天敌情识别适配
├── target_data.py    # 成就目标数据
└── assets.py         # 生成产物

module/os_ash/
├── ash.py            # AshCombat + ash_collect_status + handle_ash_beacon_attack
└── meta.py           # Meta 基类、OpsiAshBeacon、AshBeaconAssist

module/os_combat/
└── combat.py         # Combat(Combat_, MapEventHandler) + ContinuousCombat

module/os_shop/
├── shop.py           # OSShop：购买循环/数量处理/补给采购
├── port_shop.py      # PortShop：港口货架扫描
├── akashi_shop.py    # AkashiShop：明石货架（按服务器 @Config.when 分支）
├── selector.py       # Selector：货架过滤策略适配层
├── ui.py             # OS_SHOP_SCROLL（AdaptiveScroll 实例）
├── item.py / preset.py
└── assets.py

module/os_simulator/
├── simulator.py      # OSSimulator：Numba njit 蒙特卡洛 + 后台线程
├── constants.py / logger.py / plotter.py
```

## 4. 核心入口

| 入口 | 所属包 | 用途 |
| --- | --- | --- |
| `ActionPointHandler.action_point_set(zone, cost, avoid_ap_overflow)` | os_handler | 进入面板并校验/购买行动力，几乎所有 os 任务的资源闸门 |
| `MapEventHandler.handle_map_event(drop)` / `os_auto_search_quit(drop)` | os_handler | 自律寻敌途中的事件清理与退出奖励 |
| `StorageHandler.storage_get_next_item('OBSCURE'/'ABYSSAL'/'REPAIR_PACK')` | os_handler | 从仓库取下一个坐标/修理包 |
| `OSStatus.get_yellow_coins()` / `is_running_cl1_leveling` | os_handler | 资源读取与代理身份判断（智能调度依赖） |
| `handle_ash_beacon_attack()` | os_ash | 战斗结算时检查信标收集并触发 OpsiAshBeacon 任务 |
| `OpsiAshBeacon.run()` / `AshBeaconAssist.run()` | os_ash | 两个独立调度任务 |
| `os_combat.Combat` | os_combat | `OSFleet` 的战斗基类 |
| `OSShop.os_shop_buy(select_func)` / `handle_port_supply_buy` | os_shop | 购买执行；港口扫货由智能调度与 OpsiShop 共用 |
| `OSSimulator.start()/interrupt()` | os_simulator | WebUI 模拟器页启动和中断离线计算 |

## 5. 核心组件

### os_handler

| 类 | 要点 |
| --- | --- |
| `ActionPointHandler(UI, MapEventHandler)` | 行动力核心。`ActionPointLimit` 异常携带 `current/total/cost/preserve`，`delay_minutes` 属性可按恢复速率换算延迟；`ActionPointBuyCounter` 把 OCR 结果 `05` 修正为 `0/5`（购买次数），JP 服字体单独分支。`handle_action_point(..., avoid_ap_overflow=True)` 在开箱会溢出时拒绝并抛 `ActionPointLimit`。智能调度在同一面板已安全首读且含箱口径一致时传 `skip_first_read=True`，只省掉补充前的重复读取，使用或购买后的确认读取保留 |
| `MapEventHandler(EnemySearchingHandler)` | 大世界地图事件总入口：掉落页、档案弹窗、游戏提示、余烬弹窗、剧情跳过、`FleetLockSwitch`（带 `handle_additional` 清理遮挡）、自动搜索选项与退出。雾天（enemy_searching）用 `is_in_map` 特判 |
| `StorageHandler(GlobeOperation, ZoneManager)` | 大世界仓库。注意与 `module/storage/storage.py` 的通用 `StorageHandler` 同名不同类。`RepairResult` 枚举表达修理结果；`storage_get_next_item` 是「取下一个隐秘/深渊坐标并进入」的封装；日志仪与调谐样本的一键使用 |
| `OSStatus(UI)` | 黄币/紫币 OCR（双读确认 + `_cache_lock` 缓存降级）；`is_in_task_explore`/`is_running_cl1_leveling` 等属性读取 `_bind_task_override`，是代理身份判断的唯一实现点 |
| `PortHandler(OSShop)` | 港口进出（`PORT_CHECK`）、任务接取、`port_dock_repair` 港口维修；被 `OSMap` 与大世界守护共用 |
| `MissionHandler` | `os_mission_overview_accept`（任务总览接取）、`MissionAtCurrentZone` 异常；`is_in_opsi_explore()` 在此定义（OpsiExplore 启用且 next_run 早于重置前 12 小时） |
| `StrategicSearchHandler` / `MapOrderHandler` / `OSTargetHandler` | 战略搜索流程、作战指令冷却、海域成就（`TARGET_SWITCH` 为三态选择器：all/unfinished） |

### os_ash

| 类 | 要点 |
| --- | --- |
| `AshCombat(Combat)` | META 战斗中的战斗状态、战前检查及完成信号处理 |
| `OSAsh(UI, MapEventHandler)` | 地图侧读取信标持有量与每日进度；`AshDigitCounter` 核对持有量的计数格式、范围和完整字形数量，`DailyDigitCounter` 裁掉每日进度左侧文字 |
| `Meta(UI, MapEventHandler)` | META 页面基类；`MetaState` 枚举（INIT/ATTACKING/COMPLETE/UNDEFINED）驱动页面状态机 |
| `OpsiAshBeacon(Meta)` | 信标攻击任务：`ui_ensure(page_reward)` → 攻击 → `MetaReward` 领奖 → `task_delay(server_update=True)` → **必须 `ui_goto_main`**（MetaReward 停在 META 页，不回主界面会让下一个任务页面识别失败） |
| `AshBeaconAssist(Meta)` | 协助好友信标：成功领奖延迟到服务器刷新，失败 `task_delay(minute=(10, 20))` 重试 |
| `handle_ash_beacon_attack()` | 在大世界战斗链路中调用：持有量通过字形校验、≥100 且可调度时 `task_call('OpsiAshBeacon')`；读数不可信时不覆盖 META 排期。`AttackMode=current_dossier_only`（只打档案）时不触发——该模式下信标数据永不消耗，触发条件会永久成立并反复打断智能调度 |

地图持有量不能只信任 OCR 文本：两位数若被补出百位，会反复召回数据不足的 META 任务，并中断正在执行的自动搜索。`AshDigitCounter` 用同一原生字图的完整连通字形数核对文字长度，拒绝不一致或越界结果，不截掉首位猜数；下一张地图截图可重新识别。持有量无效时仍独立读取每日进度，已达每日上限的状态继续用于侵蚀一行动力保留判断。离线回归与匿名原生字图见 `tests/test_opsi_ash_status.py`、`tests/fixtures/opsi_beacon/`。

`OpsiAshBeacon.AssistRequestLimit` 替代原「一击即走」开关：`0`（默认）打一刀后持续每半小时求援；`-1` 自行连续出击，是否求援仍由 `RequestAssist` 控制；正整数在求援指定轮数、最后等待半小时后，若信标仍未击破则自行连续打完。首次战斗前的求援计入，好友/大舰队/世界的一次操作合计一轮。正整数模式将轮数及下次检查时刻保存到隐藏的 `AssistRequestState`，防止首刀后立即重复计数，并在重启后继续；确认信标为空或本信标奖励领取完毕时清除。META 主入口、每日刷新和档案信标不会自行清零该记录。旧布尔值迁移为 `true → 0`、`false → -1`。离线回归见 `tests/test_meta_beacon.py`。

### os_combat

- `ContinuousCombat`：塞壬扫描装置触发的连续战斗控制流异常，守护与任务循环捕获后继续。
- `Combat(Combat_, MapEventHandler)` 覆写四个关键点：`_handle_auto_battle_status_s`（S 评价页自动点击，`battle_status_s_autoclick_delay` 可被子类改短）、`_os_combat_expected_end`（预期结束判定，大世界守护优先点 AUTO_SEARCH_REWARD）、`combat_status` 的结束判定、`handle_exp_info`。普通守护任务若用 `expected_end='no_searching'` 在大世界永不成立，会卡死在奖励页——`os_daemon` 的注释记录了这个坑。
- `auto_search_combat()` 在加载和执行阶段优先确认战斗执行状态，暂停按钮可见时不处理地图自律开关。自动搜索中断后仍确认 S/A/B/C/D 经验页，与 `OpsiGeneral_RepairThreshold` 无关；点击使用结算冷却，并由下一张截图确认返回地图。关闭修理不能关闭结算处理，否则会在经验页等待至卡死重启。离线回归见 `tests/test_opsi_auto_search_combat.py`，覆盖脱敏原始截图、连续敌人清理及下一轮搜索。

### os_shop

| 类 | 要点 |
| --- | --- |
| `OSShop(PortShop, AkashiShop)` | 购买主循环：扫描货架 → `Selector` 筛选 → 逐项购买（数量输入、确认弹窗）→ 货币耗尽退出。`get_currency_coins` 区分黄/紫币，`is_coins_both_not_enough` 提前止损 |
| `PortShop` | 港口货架 `ItemGrid`（按钮网格 + 滚动），`OS_SHOP_SCROLL = AdaptiveScroll(...)` 适配背景多变的商店界面 |
| `AkashiShop` | 明石商店货架定义按 `@Config.when(SERVER='tw'/'en'/None)` 三分支——三服货架布局不同 |
| `Selector` | 策略适配层：把「侵蚀等级偏好、紫币保留、数量上限」等配置翻译成对货架条目的过滤与排序；港口/明石共用 |

`OSShop.handle_akashi_supply_buy()` 返回购买及返回地图是否完成，不能将入口失败计为明石成功。普通任务的近距离入口处理舰队菜单和误入的总览、仓库、情报、指令页面，点击三次后停止重试，连续十二秒无进展后交回上层；已在商店时直接执行购买，不受入口超时限制。侵蚀一中相邻明石直接进入商店，较远时使用只发送一次移动指令的事件循环，行军中不补点，剧情透出地图也不再定位。其安全定位、换队、完整强制移动与中断续查由 `module/os/event_recovery.py` 编排，详见[大世界核心](index.md#侵蚀一随机事件安全交互与续查)。

### os_simulator

`OSSimulator` 用 Numba `@njit` 加速蒙特卡洛，`start()` 起后台线程跑模拟、`stop_event` 在批次边界中断，参数读 `OpsiSimulator.OpsiSimulatorParameters.*`（Cl1Coin/Meow3Coin/Meow5Coin/明石概率等）。`module/runtime/os_simulator.py` 按实例管理只读配置快照、独立日志与图表，`module/api/opsi_simulator_service.py` 校验实例并提供 WebSocket 接口。页面刷新不终止模拟，服务关闭时请求中断并回收线程。

初始行动力、黄币、耗时和总时长为 0 时沿用原来的仪表盘、统计及月末默认值；无短猫耗时统计时使用 3 级 100 秒、5 级 200 秒。模拟器提供不绘图、单样本轨迹、多样本平均轨迹三种模式。中断只汇总已完成样本，不将未计算的数组尾部计入结果。

明石商店按 28 个选项不放回抽取 6 个，其中行动力奖励为 20、40、50、100、100、200，其余 22 个选项的行动力收益为 0。随机模式对实际抽样所得行动力扣除每点 40 黄币的购买费用；确定性模式按同一奖池计算每次遭遇的期望行动力 `510 × 6 / 28 ≈ 109.29`，再乘以明石遭遇概率，同时扣除对应购买费用。

## 6. 工作流程

### 行动力校验（所有 os 任务的共同前置）

```
action_point_enter(进面板) → action_point_safe_get(读当前/总 AP，容错动画)
  → handle_action_point(zone, cost, avoid_ap_overflow)
      ├─ AP 足够 → 通过
      ├─ 可买月卡/油箱且不溢出 → 购买后通过
      └─ 不足/会溢出 → 抛 ActionPointLimit(current, total, cost, preserve)
→ action_point_quit(退出面板) / check_and_notify_action_point_threshold(阈值通知)
```

### 信标攻击链

```
大世界战斗结算 → handle_ash_beacon_attack()
    ├─ OpsiAshBeacon 未启用 → 仅更新 _ash_fully_collected（CL1 靠它决定忽略 AP 保留）
    ├─ AttackMode=current_dossier_only → 不触发（防永久触发循环）
    └─ 收集 ≥100 → task_call('OpsiAshBeacon')
OpsiAshBeacon.run() → META 页攻击 → MetaReward 领奖 → task_delay(server_update) → ui_goto_main
```

### 港口商店购买

`os_shop` / 智能调度月末清理都调 `perform_port_shop_purchase()`：找最近友方港口 → `port_shop_enter` → `os_shop_get_items`（ItemGrid 扫描 + 滚动翻页）→ `Selector` 过滤 → 逐项 `os_shop_buy`（金额确认、黄/紫币校验）→ 退出。返回「是否买到了东西」，任务层据此决定延迟策略。

智能调度的 `OpsiScheduling.OpsiScheduling.BuyActionPoint` 默认关闭，独立于两种开荒任务；仅本月每月开荒达到 100% 或智能开荒第一轮完成后允许执行。专购通过 `perform_port_shop_purchase(action_point_only=True)` 只买全部行动力箱，正常退出港口即在 `OpsiScheduling.Storage.Storage` 的 `ActionPointPurchase` 中记录本月完成，不修改普通商店购买状态。购买中断保留断点；恢复时已无可购行动力也正常收尾。进入商店失败、购买异常或跨月不会记录完成。

行动力箱在普通海域开满 25 个后全部解锁，智能第一轮开完 29 个海域已满足条件（本地 Lua `world_newshop_data.lua` 的行动力商品 `unlock_num` 为 0、10、25）。其他商品仍可能未解锁，不能在购买后复扫全商店、要求所有货架都有可识别商品来确认行动力购买完成；旧版由此留下的购买失败计数也不应阻止恢复。

## 7. 调用关系

### 上游

| 模块 | 关系 |
| --- | --- |
| [大世界核心](index.md) | `OSMap` 与全部 tasks 组合本页全部包（os_simulator 除外） |
| [战役执行](../campaign.md) | `ActionPointLimit` 的延迟换算（`delay_minutes`）被 `delay_opsi_tasks_after_ap_limit` 消费 |
| [守护模式](../infra/daemon.md) | `os_daemon` 组合 `OSFleet + PortHandler`，用 `port_dock_repair` 与 `click_nearest_object` |

### 下游

| 模块 | 用途 |
| --- | --- |
| [商店系统](../game/shop.md) | `module/shop` 的 `ShopClerk` 框架、`VoucherShop` 被白票商店复用 |
| [UI 导航](../ui.md) | Switch（TARGET_SWITCH/FleetLockSwitch）、AdaptiveScroll、`ui_click` 通用点击 |
| [战斗系统](../combat.md) | os_combat 覆写其结算；`MetaReward`（module/meta_reward）领信标奖励 |
| [OCR 系统](../ocr.md) | 行动力数字、黄币、信标进度、META 伤害等 OCR |

## 8. 数据流

石油购买缓存按实例与服务器周记录实际已购数，配置上限增减不重置实际次数；已达上限或月末封锁直接跳过石油选项，无效计数不当作买满。`OpsiHazard1Leveling.ActionPointCheckInterval` 与 `SkipStrategicSearchCheck` 位于献祭流血量开关下方，旧通用配置值自动迁移。常规行动力仅在定时到期时从已有地图帧后台读取；0 关闭定时读取。未到期不截图、不 OCR，按已确认的出击扣减库存下界；奖励增加箱子不强制开面板。首次确认、补给和恢复仍实时读取，开箱与购买后确认实际值。

侵蚀一与短猫的事件检索通过 `wait_until_walk_stable(allow_event_finish=True)` 在商店正常退出、最终领奖、档案领取或战斗处理完成后，用新截图确认地图及计划作战入口并快速收尾。后续选项会撤销旧完成标记，意外页面恢复仍要求重新定位；下一轮保留任务收尾、EMP、修理和任务切换检查；同一海域完成事件后复用刚确认的地图位置，省略开工前重复的海域名称 OCR，随即进入计划作战。

地图黄币使用 `resource_read.py` 的有界后台队列识别固定截图，两张有效地图帧同值才接受；每次最多一个待识别帧。地图不显示商店紫币栏，不识别或记录该区域，也不以紫币结果阻塞黄币。侵蚀一与短猫都会验收结果，数字变化后重新采样。识别器状态与按钮坐标在提交时复制，实例、服务器、货币修订不匹配，以及数字变化或同步确认之前采样的结果均丢弃；在途任务保留队列槽，完成后排空，不堆积替代任务。

`get_routine_yellow_coins()` 只有在当前数字区域、实例、服务器、页面及交易修订均与已确认值相同时才复用；变化后先同步双读再决定补币或返回侵蚀一，不能直接返回 `_last_yellow_coins`。到期时后台同帧附带当前行动力，扣除采样后的已知消耗，补给后拒绝旧结果。当前行动力只更新运行判断、库存观察和仪表盘；只有本次完整面板确认的含箱总量进入行动力与资产统计，不能用旧配置或缓存箱子补齐。海里数独立记录，不附带估算行动力。商店预算及开箱决策保留同步识别。

代理任务可能已经结算奖励或购买物品，但运行器仍保留进入任务前的截图。`OpsiScheduling._run_with_opsi_task_context()` 因此在 `finally` 中更新货币修订，使旧预算和在途结果失效；覆盖正常返回、`TaskEnd`、异常及防溢出嵌套代理。下一次黄币预算必须通过新截图重新确认，不能只比较旧截图上的数字区域。独立隐秘、深渊、要塞等不启用常规缓存，直接沿同步预算读取。

资源观察、收支复核及仪表盘保存由 `resource_write.py` 串行提交；固定采样时间和任务上下文，后台只事务合并仪表盘字段，不修改运行中的配置对象。收支复核按采样时间计算已发生交易，旧观察不能覆盖新读数。后台确认侵蚀一黄币低于当前保留值时，由主线程通过 `interrupt_auto_search(goto_main=False, end_task=False)` 返回地图，智能调度下一轮立即执行补币决策；补币任务不被自己的低黄币状态打断。后台正常采样使用 `ocr_batch(..., show_log=False)`，不输出逐帧批量结果和黄币确认日志；`[大世界-资源后台]` 仅保留识别异常与低币切换提示。离线回归见 `tests/test_opsi_background_resources.py`。

```
行动力面板截图 → OCR(当前/总/购买次数) → ActionPointLimit 或放行
货架截图 → ItemGrid(名称/价格/数量) → Selector 过滤 → 购买点击 → 货币 OCR 校验
战斗结算帧 → ash_collect_status(DigitCounter) → _ash_fully_collected / task_call
META 页截图 → MetaState 状态机 → 攻击/领奖循环
（os_simulator）配置参数 → Numba 蒙特卡洛 → 收益曲线绘图（不回流生产流程）
```

## 10. 配置

| 配置 | 说明 |
| --- | --- |
| `OpsiGeneral.BuyActionPointLimit` 等行动力参数 | 决定 `action_point_buy` 的行为 |
| `OpsiHazard1Leveling.ActionPointCheckInterval` | 非负整数分钟，默认 0 关闭定时读取；侵蚀一、智能调度和短猫共用 |
| `OpsiAshBeacon.*`（Enable/AttackMode/EnsureFullyCollected） | 信标任务开关与触发条件 |
| `OpsiMeowfficerFarming.OpsiShopFilter` 等货架策略 | 经 `Selector` 生效 |
| `OpsiSimulator.OpsiSimulatorParameters.*` | 模拟器参数（仅模拟器读取） |
| `OpsiDaemon.RepairShip/SelectEnemy` | 大世界守护使用 port/os_handler 能力的开关 |

## 11. 异常与错误处理

| 异常 | 来源 | 处理 |
| --- | --- | --- |
| `ActionPointLimit` | action_point | 上抛任务入口，换算 `delay_minutes` 延迟任务（语义见[大世界核心](index.md)异常表） |
| `ContinuousCombat` | os_combat | 扫描装置连续战斗的控制流信号，循环捕获后继续 |
| `MissionAtCurrentZone` | mission | 当前海域任务异常时由调用方换区重试 |
| OCR 超时/双读失败 | os_status | 黄币回退缓存值；行动力 `action_point_safe_get` 内部重试后上抛 |

## 12. 并发与线程模型

- 辅助包自身均无线程，随宿主任务单线程运行。
- `OSStatus._cache_lock` 是唯一的显式锁（保护黄币缓存）。
- `OSSimulator` 自起后台线程（`_thread` + `threading.Event`），线程内读取配置快照、只写自己的 logger/plotter；它不与调度器共享状态。

## 13. 缓存与持久化

- `_last_yellow_coins`（内存，线程安全）：OCR 失败降级。
- `_ash_fully_collected`（内存）：由 `ash_collect_status` 维护，CL1 据此决定是否忽略 AP 保留；每次任务重建。
- 商店货架扫描无缓存，每页现扫。

## 14. 生命周期

全部作为 mixin 随 `OSMap`/任务类实例化，无独立创建销毁；`OSSimulator` 由使用者显式 `start()/interrupt()`，线程随 stop_event 结束。

## 15. 扩展方式

- **新地图事件**：在 `map_event.py` 补 `handle_map_event` 分支 + assets 新按钮。
- **新商店货架条目**：更新对应 `preset.py`/`item.py` 定价与筛选规则；明石货架按服务器分支同步。
- **新成就目标**：`target_data.py` 加数据，`target.py` 的 `TARGET_SWITCH` 无需改动。
- **新 META 玩法**：继承 `Meta` 基类，复用页面状态机与领奖收尾。

## 16. 修改注意事项

- **两个 `StorageHandler` 不要混改**：`module/os_handler/storage.py`（大世界仓库，依赖 `GlobeOperation`）与 `module/storage/storage.py`（普通仓库，依赖 `StorageUI`）是同名异构类，改名或提取公共基类前先确认两处调用面。
- **`handle_ash_beacon_attack` 的「只打档案」例外**是修 bug 的产物：不判断 AttackMode 会导致 OpsiAshBeacon 每轮被触发并打断智能调度的自动搜索。
- **`MetaReward` 领奖后必须回主界面**：`OpsiAshBeacon.run`/`AshBeaconAssist.run` 末尾的 `ui_goto_main` 有注释说明——删掉会让下个任务在 META 页启动而卡识别。
- **明石货架是 `@Config.when(SERVER=...)` 三分支**，新服务器适配要新增分支而不是改默认分支。
- **`ActionPointLimit.delay_minutes` 的换算依赖行动力恢复速率**，修改恢复速率常量（如游戏改动）时同步检查大世界核心的延迟逻辑。
- **os_simulator 独立于游戏调度**：保留配置兼容，WebUI 只用配置快照和已有统计模拟，不运行实际游戏任务；启动前需等待页面参数保存完成。

## 17. 已知限制

- `OSSimulator` 沿用 Alpha 收益模型，结论只具参考价值；中断需等待当前计算批次（或首次 JIT 编译）结束，部分结果以已完成样本为分母。
- 行动力 OCR 对面板动画敏感，`action_point_safe_get` 的重试能容忍常见动画，但极端卡顿时仍会把动画帧读成错误值。
- 商店货架识别依赖固定阈值与模板，游戏改版后需重新采集资源离线验证。
- 信标数字 OCR（`MetaDigitCounter` 左裁剪）与 META 伤害 OCR 按 JP 服单独调色，其他服务器改版需补分支。

## 18. 示例

取下一个隐秘海域坐标并进入：

```python
if self.storage_get_next_item('OBSCURE', use_logger=True):
    ...  # 已进入隐秘海域，继续清理
```

港口维修（守护模式节选）：

```python
if self.appear(PORT_ENTER, offset=(20, 20), interval=30):
    self.port_enter()
    self.port_dock_repair()
    self.port_quit()
```

## 19. 调试方法

- 日志前缀：`[大世界处理-状态]`（os_status）、`[大世界处理-存储]`（storage）、`[大世界-智能调度]` 中引用的行动力/黄币数值。
- 商店问题先看 `scan_all` 输出的条目列表（名称/价格/数量），确认是识别错还是策略错。
- 信标不触发：按 `handle_ash_beacon_attack` 的三个条件逐项查（任务启用？AttackMode？收集 ≥100？）。

## 20. 相关模块

- [大世界核心](index.md) —— 消费本页全部能力的主控
- [处理器层](../handler.md) —— 通用弹窗/登录处理（本页 handler 的非大世界对照）
- [商店系统](../game/shop.md) —— 通用商店框架与 `ShopClerk` 的复用关系
- [战斗系统](../combat.md) —— `Combat_` 基类与本页 `os_combat` 的适配关系
- [统计与数据提交](../infra/statistics.md) —— 黄币/紫币写入 LogRes 的去向

配置页效果（模拟服务）：

![侵蚀一资源检查配置](images/cl1-resource-settings.png)
