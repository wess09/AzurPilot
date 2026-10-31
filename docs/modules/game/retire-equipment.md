# 退役与装备（retire / equipment / auto_equip / storage）

> 船坞满载时的舰船退役与强化、舰船装备装卸与装备码配装、仓库开箱与装备拆解，以及面向独立任务的自动换装。

## 1. 模块概述

四个子模块共同覆盖「船坞与装备仓库」这一游戏界面的自动化操作，但分工不同：

- `module/retire`：退役与强化。核心类 `Retirement` 是 `Combat` 的 mixin（`module/combat/combat.py` 中 `Combat(Level, HPBalancer, Retirement, ...)`），因为「船坞已满」弹窗会在出击准备、战斗结算、地图行走等任意战斗流程中随机出现，以 mixin 挂入后所有战斗类无需额外接线即可处理。它同时是 `GemsFarming`/`Ambush11` 等换船任务的基座（保留普通航母、退役废弃旗舰）。
- `module/equipment`：装备管理。舰船详情页的装备装卸、按图像模板在仓库中找回装备、Base64 装备码（配装码）的导出与导入。被 `GemsFarming`（换旗舰时装回原配装）、演习与 META 作战（`Equipment.Config`）等复用。
- `module/auto_equip`：独立任务「自动换装」（`AutoEquip`）。遍历船坞，为每艘舰船的空装备槽从仓库填充装备，与 `module/equipment` 互不依赖（只共享 `Dock` 与滑动常量）。
- `module/storage`：装备仓库。开装备箱、拆解装备、处理「装备仓库已满」弹窗。`StorageHandler` 同时被科研模块（E 系列科研需先拆装备）和装备码处理器继承，因此任意装备操作遇到仓库满弹窗都能自动拆解腾位。

这些能力串成一条继承链 `Retirement → Enhancement → Dock → Equipment → EquipmentCodeHandler → StorageHandler → StorageUI → UI`，是项目中层级最深的 mixin 链。这样设计的原因：船坞、舰船详情、装备编辑、仓库是互相嵌套的同一批页面——退役要拆装备、拆装备会遇仓库满、装备码应用也要处理仓库满、强化要反选 GemsFarming 要保留的普通航母，扁平拆分会造成大量跨模块调用。

## 2. 模块职责

### 负责

- 船坞满载时的退役/强化决策（`handle_retirement()`）与一键退役、旧退役两种执行模式，含快速退役设置的自动兜底重置。
- 船坞页面通用操作：卡片加载等待、排序/收藏/筛选器设置、舰船选择、卡片网格与属性扫描（等级/情绪/稀有度/舰队/状态，`scanner.py`）。
- 舰队扫描任务（`FleetScan`）：扫描编入舰队的舰船并写入 `FleetInfo.FleetInfo.Result`。
- 舰船装备装卸（按舰队记录逐件）、装备模板记录与找回、装备码剪贴板导出/导入。
- 自动换装任务：快速换装面板填充空装备槽。
- 装备箱开启（数量 OCR + +/- 调节）、装备拆解（按稀有度筛选、翻页）、仓库满弹窗处理。

### 不负责

- 战斗流程本身；退役弹窗的触发时机由战斗/地图模块决定，本模块只提供 `handle_retirement()`。
- 大世界仓库（`module/os_handler/storage.py` 是独立同名类，服务大世界开箱/修理，与本模块无关）。
- 舰船强化材料之外的养成功能（觉醒 `module/awaken` 复用 `Dock` 但自行实现）。
- 页面跳转图谱（`module/ui`）与配置定义（`module/config`）。

## 3. 模块位置

```
module/retire/
├── retirement.py      # Retirement 主处理器：一键/旧退役、船坞满决策、保留普通航母
├── enhancement.py     # Enhancement：DFA 状态机驱动的按类型强化，强化后回退退役
├── dock.py            # Dock：船坞界面操作（排序/收藏/筛选/选择），卡片网格常量
├── setting.py         # QuickRetireSettingHandler：游戏内快速退役设置项（filter_1..5）
├── scanner.py         # ShipScanner/DockScanner 及子扫描器、DHash 去重、FleetManagementScanner
├── ship_name.py       # ShipNameMatcher：舰队 OCR 结果对舰船名的纠错
├── fleet_management.py# FleetManagement：FleetScan 任务，扫描结果持久化到配置
├── dock_scan.py       # DockScan：共享船坞扫描、完整范围证明和底账保存
└── assets.py          # 退役/船坞按钮与模板（assets/{cn,en,jp,tw}/retire）

module/equipment/
├── equipment.py       # Equipment：舰船详情页导航、滑动换船、装备装卸（舰队记录编码）
├── equipment_change.py# EquipmentChange：记录装备图像→仓库模板匹配找回→穿上
├── equipment_code.py  # EquipmentCodeHandler：装备码导出（剪贴板）与导入（ADB/u2 输入）
├── fleet_equipment.py # FleetEquipment：舰队页面批量进入详情、按舰队装卸
└── assets.py          # assets/{server}/equipment

module/auto_equip/
├── auto_equip.py      # AutoEquip：自动换装任务；快速换装面板操作
├── empty_slot_plus.png # 空槽「+」识别模板（模块内私有，不经 dev_tools.button_extract）
└── no_equipment.png   # 仓库「无可用装备」识别模板

module/storage/
├── storage.py         # StorageHandler：开箱、拆解、仓库满处理；StorageFull 异常
├── box_disassemble.py # StorageBox：BoxDisassemble 任务，按稀有度拆箱并保留阈值
├── ui.py              # StorageUI：仓库三栏（材料/装备/拆解）切换与装备筛选
└── assets.py          # assets/{server}/storage
```

## 4. 核心入口

| 入口 | 用途 |
| --- | --- |
| `Retirement.handle_retirement()` | 战斗流程中检测到船坞满弹窗时调用，按配置执行退役或强化 |
| `Retirement.retire_ships_one_click()` / `retire_ships_old()` | 退役执行；换船任务（GemsFarming 等）经 `_retire_handler()` 进入 |
| `StorageHandler.handle_storage_full()` | 任意流程遇到 `EQUIPMENT_FULL` 弹窗时的通用处理（拆解腾位后返回原页面） |
| `StorageHandler.storage_disassemble_equipment()` / `storage_use_box()` | 科研等模块按数量拆解装备/开箱的组合入口 |
| `StorageBox.run()` | `BoxDisassemble` 独立任务（alas.py `box_disassemble`） |
| `AutoEquip.run()` | `AutoEquip` 独立任务（alas.py `auto_equip`，亦列于 submodule 可用功能） |
| `FleetManagement.run()` | `FleetScan` 独立任务 |
| `DockScan.run()` | 心智与科技页面共享的船坞扫描，按稳定群组保留同名舰及无科技舰 |
| `Equipment.equipment_take_on/off()` | 按 `fleet` 记录装卸装备的底层入口，困难模式等继续复用 |
| `EquipmentCodeHandler.code_apply()` / `code_clear()` | GemsFarming/Ambush11 换船时回装/卸下配装 |

### 舰队信息扫描

`FleetManagement.run(update_emotion=None)` 导航进入编队后即在第一水面舰队，不展开水面
舰队下拉列表，直接点舰位4进入选船页扫描前排；取消返回后直接点舰位1扫描后排。
再取消返回，只点击一次底部“潜艇舰队”右侧的舰队入口，确认潜艇类型已选中后点潜艇
舰位1。切换动画期间继续截图确认，不重复点击入口展开列表。水面有六队、每队六个舰位；
潜艇有两队、每队三个舰位。入口自带前后排限制，显式清空旧搜索、收藏和舰种筛选后，
以等级降序读取已编队候选；选船页由游戏固定显示心情。
独立工具任务创建的设备不一定已有首帧；扫描入口和 `fleet_enter()` 在任何图像判断前检查
`Device.has_cached_image`，缺图时先截图。不能假设调度器或调用方已经初始化 `image`。
进入选船页必须用已有 `DOCK_CHECK` 标题模板确认；编队标题的平均颜色也可能通过船坞
颜色判断，不能据此跳过舰位点击并开始清理筛选。

详情采集按水面1–6队、潜艇1–2队顺序进行：进入详情后采集固定列，再点左上返回，
确认编队视图后用右箭头切到下一队。通过底部大号舰队数字的原生字形模板核对编号，
未确认编号时不采集下一队，不为核对队号展开下拉列表。切换水面/潜艇时只点击一次
对应类型右侧的舰队入口。`_capture_formation(..., navigate=False)` 仅用于已确认队号的
顺序扫描；换船等调用保留默认通用切队。详情左侧金色“详情界面”是当前页签，不能作为
退出按钮；正常采集和中断后从详情恢复均点左上返回，以编队视图作为退出条件。

水面编队画面后排从左到右为 `3、1、2`，前排为 `4、5、6`；潜艇画面从左到右为
`3、1、2`。点击使用 `runtime/fleet_formation.py` 中固定坐标，不能依赖有角色后消失的
“添加”模板。详情卡片按水面左到右 `1、2、3、4、5、6`、潜艇左到右 `1、2、3`
直接对应舰位；舰位来源是页面几何位置，不是名称匹配或船坞卡片排序。

`FormationDockScanner` 复用已有舰名、等级、心情和舰队徽标识别器，动态定位完整卡片行，
只读取选船页底栏上方的区域。滚动后由公共 `ScanMerger` 核验实际图像位移并按物理卡位
合并，不按同名舰船合并。已编队置顶区域按水面最多18艘加离队入口、潜艇最多6艘加离队
入口确定覆盖范围，不用OCR结果决定是否翻页或提前停止。顶部/底部按滑块端点确认，
不能把距离底部5%的位置当作完整扫描结束。

`FormationDetailScanner` 在固定列读取参考舰名、等级，以原生卡片字形区域判断有无舰船；
文字识别错误只保留原文并标注 `review`，失败保留未知，不中断操作、不丢弃整个舰队。
心情从选船页参考信息补充，名称或归属读数无法对应时为未知。数据一次保存到
`FleetInfo.FleetInfo.Result` 和 `Record`，舰船包含
`name、level、emotion、slot、occupied、review`；潜艇也保存自己的1–3号舰位。

`FleetInfo.FleetInfo.UpdateEmotion` 可在每次扫描前选择是否读取心情。关闭时跳过心情OCR，
保留已有舰位的心情参考，缺少旧舰位参考时为 `null`，不参与被动恢复相位学习。
开启时心情仅接受完整0–150整数，失败保留
未知，不截位猜数。WebUI 显示已记录舰位及未知读数；旧记录不会按数组下标猜测舰位。
非日服舰队心情读取同时核对数字左侧与卡片右侧的心情图标：两处均为红色时记为0，
两处均为黄色时按Lua定义只接受1–30，并清除短数字右侧的立绘和底部亮线干扰。
其他心情和日服保留原识别方式；空白、未确认的数字仍为未知，沿用已有的单次补扫。
日志中的“舰队心情OCR”为图标核验后的最终读数，`FLEET_EMOTION_OCR`为原始数字结果。

被动心情学习继续复用 `module/retire/fleet_emotion.py`，其对时间窗口、完整舰队、可靠
名称和数值的约束仅决定是否学习，不影响舰位互换。学到的恢复状态随本次保存事务提交；
时间窗口及共享舰队映射语义见[战斗心情](../combat.md)。

### 智能换船联动自动换装备

同一舰队详情已经打开且底部实际队号确认一致时，直接点击下一个详情舰位，不退出编队再重开详情。
换装前逐舰位实读培养候补时，`FleetShipDetail.reuse_details()`让同批、同队读取复用详情页，
换队或结束该批次时统一返回；正常读取、身份核实、卸装与装备码分配规则不变。

WebUI“舰队管理 → 自动换装备”是独立配置页，不注册调度任务。`FleetInfo.FleetEquipment.Enabled`
默认`false`，关闭时不创建装备处理器、不卸装、不改变原有换船或返回路径。开启时仍仅联动
智能换船已支持的普通主线、活动水面舰队；不是全船坞自动换装或潜艇轮换。

`FleetInfo.FleetEquipment.Codes`保存舰种到最多三个装备码的JSON数组映射，页面为每种舰种提供
三个独立输入框，标题旁显示“装备码”。旧单字符串只放入第一格，第二、三格留空；保存后
使用数组格式，不覆盖其他舰种的方案。支持DD、CL、CA、CB、BC、
BB、CVL、CV、BBV、SS、SSV、AR、BM、AE、IX共15项。潜艇及潜母可配置，但只有当前轮换实际
访问的角色会应用。国服角色详情左上角金色徽标通过原生模板识别，连续两张新截图一致才采用；
未知或不唯一时停止，不复用低耗换船中“未知默认驱逐”的回退。目前仅启用国服模板。

流程在`prepare_rotation()`完成1位后排扫描、心情复核和候补排序之后接入：

1. 候补及待换舰位确定后，关闭选船页，进入原目标队详情，按固定详情列逐艘卸下所有待换出
   舰船的装备；空舰位跳过。所有卸装完成后才调用原有`rotate_slot()`。
2. 按原有同号舰位互换全部舰船并逐排更新数据，不重复设置船坞等级排序。
3. 再进入目标队详情，按实际舰位顺序识别舰种。每队前后排独立计数，同舰种第1、2、3艘
   分别使用第1、2、3格。为计入未换船和已完成的同舰种角色，会检查本排起始舰位到最后
   待处理舰位的已占用位置，但只对本轮待换装舰位操作装备。
   对应格有码时先清空该舰船，再输入并应用；空格保留换入舰船当前装备，不回用第一格，
   不把第三格向前压缩。换出舰船仍按步骤1统一卸装。
4. 完成后回到主界面，再交回原任务选关和心情检查。装备交接不改心情阈值、候补排序、任务
   范围或战后扣减。

`module/equipment/fleet_rotation.py`复用紧急委托使用的`_code_enter()`和`_code_apply()`状态
流程，沿用其控制方式、仓库满、确认和输入支持；不导出原装备码，不覆盖紧急委托的方案、
暂存码或名称识别。已填写的全部方案在卸装前校验，配置API也拒绝未知舰种及无效码。

`FleetInfo.FleetEquipment.State`独立保存待完成的目标`fleet/slot`，在任何卸装前落盘。
应用前记录已识别舰种和方案序号；应用成功、空位或明确跳过的舰位逐一移除。失败保留余项，
不被换船自动清理错误记录覆盖。恢复时仍计入本排已完成或未参与换船的较前舰位，因此第二、
第三艘不会从第一套重来；每队及每排的计数不互相影响。
下次两个开关仍开启时，先离开已知装备页，重新扫描实际编队并补完当前舰位的装备，再判断
心情是否需要换船，避免已换入高心情舰船漏装。关闭功能保留原行为，不自动处理这些记录。
每次出击前读取开关；已开始卸装的本轮先处理完当前舰位，再响应下一轮开关设置。
用户主动点击换船调度的“刷新状态”时，也清空这些未完成的换装待办，无需先恢复；装备方案仍保留。
刷新不会操作游戏或还原已卸装的装备，之后不再按旧待办续接。

原生徽标及截图时间见`tests/fixtures/fleet_equipment/README.md`。页面桌面及手机效果见
`docs/modules/webui/images/fleet-equipment-desktop.png`和`fleet-equipment-mobile.png`。
以上测试使用原图、模拟设备和临时配置，不代表真实账号换装验收。

### 按源舰队和源舰位互换

操作入口为：

```python
FleetManagement(config=config, device=device).swap_slots(
    source_fleet=1, source_slot=4,
    fleet=4, slot=5,
    fleet_type='surface',
    update_emotion=False,
)
```

此入口由普通主线/活动的智能换船策略复用；尚未提供手动指定互换的WebUI按钮或装备更换。
水面只能在主力组内或先锋组内
交换；潜艇使用 `fleet_type='submarine'`、队号1–2、舰位1–3。同一舰队内也可互换已有
舰位。空位只能按组内顺序加入，跨队移入后来源组按游戏规则向前压缩；不把点击空舰位
当作已经形成允许跳号的编队。

交换路径与OCR分离：

1. 用下拉列表的高亮行定位源/目标舰队，目标队号只点一次；随后确认菜单自行收起、
   底部原生队号正确且点击后已过0.5秒，不为核验再次展开并关闭菜单。
   菜单收起箭头模板只保留白色箭头，排除随背景变化的斜线。`fleet_enter(..., method='arrows')`
   保留左右箭头切换及列表高亮核对，不读取舰队编号OCR。
2. 从源舰位的固定详情列采集卡面，用SIFT特征和几何关系在选船页定位对应卡片；
   名称、等级、心情OCR不作为点击、确认或交换的前置条件。
3. 第二次滚动重新定位物理卡位，避免复用滚动前的坐标。选中后以单选计数区域的图像
   变化确认界面响应，不调用数字OCR；随后确认本次已允许的跨队交换。
4. 比较双方舰位卡面，再返回主界面提交，以共享`is_in_main()`确认传统或白色主题的主界面，
   重新进入编队再次核对。意外提交弹窗不自动
   确认，避免误确认清空不完整编队。
5. 根据已核验的位置变更移动已有参考记录。没有旧参考信息时保留未知名称、等级和
   心情，不猜测身份；其他舰队记录保留。`update_emotion=True` 时交换后再刷新参考
   信息；参考OCR不可用不改变已经完成的交换结果。

同立绘候选可参考已有的舰队徽标图像模板消歧；卡面本身无法区分时在点击前报告图像
歧义。画面未就绪、滚动位移不明、或交换后的实际卡面不符属于操作状态问题，使用
`FleetManagementError` 停止，不能用重启重复换船；OCR错误不会触发这条操作失败路径。

定向验证入口为 `tests/test_fleet_formation.py`（原生选船/详情/舰队菜单图片、无OCR
卡面定位、源/目标舰位计划及模拟交换状态）、`tests/test_fleet_emotion.py`、
`tests/test_fleet_ship_names.py` 和 `frontend/e2e/fleet-info.spec.ts`。
图片测试和模拟状态流程不连接设备，不能代替真实模拟器操作验收。

### 换船配置与换船调度

等级/好感调度复用同一舰位、卡面互换和可选装备流程。角色详情导航提取到
`module/retire/fleet_detail.py::FleetShipDetail`，装备子类沿用原入口、状态循环和返回条件；
培养读取不会初始化装备码或卸装。等级复用大世界识别，好感按固定位置打开信息并读取
当前数值，可靠数据不足时不记录完成。完整组合、持久状态及延时语义见
[战役培养调度](../campaign.md#等级好感培养调度)。
等级/好感使用小时检查间隔，心情调度到现有保留要求时独立触发。检查时先从勾选舰位进入选船页，只读取该实际出战舰队的舰名和心情，
再进角色详情读已开启的培养条件；不能以详情等级代替心情实读。此读取不受`SelectedOnly`开关限制。
等级/好感未毕业则等待下次检查；心情临时换船不要求毕业，也不重置等级/好感检查时间。
确认需要换船后直接完整扫描全舰队，再在内存中排序候补并回到目标舰位换船，没有额外扫描间隔。换后复用刚确认的候补
培养读数，只核对互换双方；中断互换与装备恢复仍按原规则处理。详见[战役培养调度](../campaign.md#等级好感培养调度)。

`module/campaign/fleet_rotation.py` 在普通主线/活动出击前调用本模块。策略配置保存在
`FleetInfo.FleetRotation`，不是调度任务：“换船配置”仅编辑共享舰位与候补规则；
“换船调度”统一保存三个调度开关及共享的`SelectedOnly`。`Enabled`仍表示心情调度、默认关闭，`Rules`默认JSON空对象，
表示所有舰位不变。规则以实际水面舰队号为键，例如
`{"1":{"slots":[3,4,5],"sources":[3,4,5,6]}}`。六队各舰位独立勾选，来源队可多选，
但不能包含目标队自己；服务器校验舰队号、舰位、重复值与字段类型。

候补依据舰船信息中的实际舰位和实测心情排序：默认比较整队最低心情，按降序排列，
同值按队号升序。例如3队最低138、4/5/6队最低150时，顺序为4→5→6→3。
间隔到期先实测目标队，实测充足只校正账本，不换船；候补缺失同号舰位、心情未知
或不足出击线时不选用。一轮只从选定来源完成全部勾选舰位，4/5/6严格对应来源4/5/6，
不再调用`highest_morale_slot()`选同排其他角色。仍通过源舰位卡面、来源队徽标和
交换前后双方卡面核对实体，不以名字近似匹配决定点击。
目标队的培养换船条件始终只取勾选舰位最低心情，固定角色不足只能等待，不能误换培养舰船。
默认关闭的`SelectedOnly`由心情、等级、好感三种调度共用。开启时，心情调度的候补也只比较对应勾选舰位；培养账本按战斗扣减，
沿用任务心情控制与单图预留作为换船要求。整队最低心情仍同步原有账本，但开启时不作为
等待或红脸确认的依据，固定低心情允许出击；关闭时沿用原全队出击检查。两种模式都计算培养心情。
仅开启等级/好感时，此选项同样控制等待和固定红脸处理；低心情只延时，不会临时换船。
心情轮换不会记录为培养完成；装备、固定舰位、身份核验及失败恢复机制不变。
智能换船的入口扫描和换船前后复核始终读取实际心情；手动舰队扫描的“更新心情”选项
仍只控制手动扫描，关闭智能换船不增加自动扫描。

智能换船使用`prepare_rotation()`：常规检查通过`slots`从勾选舰位开始，`fleets`限制实读舰队；
默认调用仍依次从舰位4、1读取前后排。候补已核实时传`scan=False`复用本轮卡面池，
打开实际目标舰位直接开始互换。`rotate_slot()`复用
舰船信息中的固定舰位和进程内卡面，在选船页定位来源角色；确认后只更新本排的互换双方，下一舰位
继续从目标队进入。通用`swap_slots()`仍保留单独的双方详情及提交核验，普通互换不再调用它；
目标空位需添船时仍复用该通用路径，保留来源压缩、空位顺序及提交校验。
整个舰队扫描及本轮换船只准备一次等级降序，离开选船页不重置排序和筛选。前后排快照
逐排更新并保存，最后一个舰位的更新就是本轮最新信息，不再重扫前后排或详情。读取全部
实际占用舰位，包括未勾选角色；双方最低心情用于任务同步。原始读数未知时保存未知，
不能用已换入角色的高心情覆盖仍留在队内的低心情。
完整扫描及单队心情刷新在卡面对应后检查未知读数，只对相关前排、后排或潜艇候选补扫
一次，仍须唯一卡面对应；仅补齐未知项，已确认心情不被补扫失败覆盖。补扫后仍未知则
保持未知，不无限重扫。船坞为空须匹配提示字形，不能因滚动中卡面平均颜色相近而早停。
详情阶段点击切队箭头或切换类型后，继续截图并确认目标队号，至少间隔0.5秒才进入详情；
即使队号提前更新也不立即点击，动画尚未结束则继续等待正向页面状态。

`State`保存来源、本轮已完成舰位和正在操作的舰位。失败时以`rescan`标记替代旧错误，
下次自动清理旧进度并强制完整扫描；进程中断遗留的待确认、旧版记录也走同一流程。
恢复轮次只互换仍低于出击线的已勾选舰位，已换入且心情足够的舰位不会重换，不要求
手动清空记录。手动清空按钮仍保留。实测快照也同步关联来源队，其他任务不会沿用旧心情。

运行中关闭开关，会在当前互换确认完成后停止后续舰位，保留部分进度并更新双方心情；
再次开启继续本轮。轮换结束后按实际舰队映射同步普通主线和活动任务的最低心情、
记录时间和恢复相位，再回到原关卡。仍然心情不足时沿用原有延迟，不连续换队。
困难图、C/D/HT/EX活动图、作战档案、低耗特殊任务和大世界不接入该策略。
启用后，切换任务时先完整扫描一次舰队；同一任务连续周回不重复入口扫描。
舰队扫描和智能换船暂不支持区分多艘同名舰船，请避免在参与舰队中放入同名舰船。
卡面和来源不能唯一确认时停止互换，不能用相似名字猜测实体。

定向验证：`tests/test_fleet_rotation.py`、`tests/test_fleet_formation.py` 和
`frontend/e2e/fleet-rotation.spec.ts`，包含真实临时配置事务、原生跨队确认图及模拟设备。

### 舰队舰船名称确认

`FleetNameScanner` 先使用现有白色/婚舰粉色预处理读取名称，再交给 `ShipNameMatcher` 确认。
名称名单使用 `assets/ship/ship_names.json`，不再依赖可能过期的舰船属性表。
通过 `uv run python -m dev_tools.ship_data_extractor --lua-repo <Lua仓库路径> --names-only`
更新名单：复用现有 Lua 解析器读取 CN/EN/JP/TW 的 `ship_data_statistics`、`name_code`
和 `ship_skin_template`（含 sublist），解析名称引用，仅加入 `skin_type=2` 的改造皮肤名称，
不加入普通皮肤标题。只生成轻量名称表，原有属性提取功能与 `ship_data.json` 保持不变。
生成结果按服去重排序，可重复生成；运行时不访问 Lua 仓库，也不跨服猜测名称。

完整名称只接受唯一规范化精确匹配；仅在游戏名称尾部有 `..`、`…` 或 `⋯` 截断标记，
且至少保留两个字符、补全候选唯一时补全。短名称、歧义或无匹配均保留 OCR 原文，
不按字符串相似度强行替换，不删掉 `.改`、`META` 等身份信息。

未确认的名称在同一截图、同一名称区域追加一次原彩色批量 OCR，既不放大也不重扫页面。
只有彩色结果精确命中名单，且保留首轮可读前缀（空白首轮除外）时采用；已有精确身份、
改造身份或 META 身份不能被彩色结果覆盖。失败仍保留首轮原文，日志记录确认依据或拒绝原因。
等级、心情和结果格式保持不变；更新代码后需重新运行 FleetScan，历史错误名称不会自动改写。

编队扫描在上述读取后，额外使用`ShipNameMatcher.approximate()`校正Lua名单中的唯一
标点变体、长前缀及有明显优势的近似名称；不跨改造/META身份猜测，不猜单字短名。
未确认名称显示为空并保留`raw_name`供核对。第一轮同时保留内存中的卡面，第二轮按同队
同排卡面把已确认的名称、等级与心情对应到详情固定列，详情OCR误读不能覆盖第一轮
已确认名字。卡面保存在进程内的任务上下文中复用，切换任务或错误重扫时更新，不写入
用户配置。其他共享名称扫描入口仍保持
原来的保守规则。

`tests/test_fleet_ship_names.py` 验证名单引用解析、普通皮肤排除、名单不可用、保守匹配、
复识别条件以及三张匿名卡片区域截图的真实扫描与配置落盘。夹具只保留名称、舰队编号、
等级和心情区域，不含账号信息；离线测试不操作真实账号。

## 6. 工作流程

### 退役（module/retire）

战斗流程循环中调用 `handle_retirement()`，其返回 `True` 表示已操作完一轮（需 continue），`False` 表示刚点了入口等弹窗出现：

```mermaid
flowchart TD
    A[船坞满弹窗 retirement_appear] --> B{Retirement_RetireMode}
    B -- enhance --> C[点强化入口进入船坞<br>_enhance_handler 按类型强化]
    C --> D{无可强化或剩余空位&lt;3?}
    D -- 是 --> E[_unable_to_enhance = True<br>下轮转退役]
    D -- 否 --> F[结束]
    B -- one_click_retire / old_retire --> G[点退役入口进退役界面]
    E --> G
    G --> H{模式}
    H -- one_click_retire --> I[retire_ships_one_click<br>失败时逐级重置快速退役设置]
    H -- old_retire --> J[retire_ships_old 按稀有度颜色选卡]
    I --> K{退役到船?}
    J --> K
    K -- 否 --> L[RequestHumanTakeover]
    K -- 是 --> M[retire_gems_farming_flagships 退役废弃旗舰]
    M --> N[退出并置 DOCK_FULL_TRIGGERED]
```

- **一键退役**：不需加载船坞，直接点 `ONE_CLICK_RETIREMENT`，客户端一次退完，一轮结束。关键风险是游戏内「快速退役」设置不当导致退不出船，因此有四级兜底：重置船坞筛选器 → 重置前 4 个快速退役设置 → 第五项改为「保留突破」→（仅当配置为 `do_not_keep`）改为「全部」；每级都重新执行一轮。支持兜底的服务器为 cn/en/jp。
- **旧退役**：`dock_filter_set` 按等级排序 + 目标稀有度过滤，然后每轮用 `CARD_RARITY_GRIDS` 采样卡牌顶边颜色判稀有度、选最多 10 张、确认，循环到目标数量；结束时恢复筛选器。
- 两条路径都汇入 `_retirement_confirm()`：按显示层级处理 SR/SSR 确认、舰船确认（一键/旧两套按钮）、装备拆解确认、获得物资弹窗，并以 10 秒超时兜底（GemsFarming 的船无装备可拆，弹窗可能永不出齐）；退出后还要补一次截图，防止拆解的「获得物资」弹窗延迟弹出卡死后续流程（#838 #418）。
- `retire_keep_common_cv` 为真（GemsFarming 或 ThreeOilLowCost 任务启用）时，确认前调用 `keep_one_common_cv()` 滚动查找并反选一艘普通航母，供换船任务持续获得新旗舰。
- 全程无一船可退时抛 `RequestHumanTakeover` 并提示用户配置游戏内一键退役；成功后置 `config.DOCK_FULL_TRIGGERED = True`。

### 强化（Enhancement）

`enhance_ships()` 按 `General.Enhance.Filter` 的舰种顺序（`>` 分隔，非法项随机替换）依次进入船坞，每类内用 DFA 状态机（check/ready/recommend/attempt/confirm/fail/success/exit 八态）驱动「推荐材料 → 确认 → 失败滑动到下一艘」。状态机循环超 30 次抛 `GameStuckError`；对战斗中舰船与无材料两种卡死路径，主动剔除点击记录避免 `GameTooManyClickError`。GemsFarming 启用时强化前会反选材料槽中的普通航母（`_enhance_deselect_cv`），误入船坞页面时点返回并最多重试 3 次。

### 装备（module/equipment）

`Equipment.equipment_take_on/off(enter, out, fleet)` 用 `'9'.join` 把舰队记录 `[3,1,1,1,1,1]` 编码为槽位序列：`9` 表示滑动到下一艘船，其余数字表示在预设栏穿/脱第 N 套。`EquipmentChange` 走另一条路：先把舰船当前装备截为模板（`ship_equipment_record_image`），再在仓库页滚动做模板匹配找回并穿上，适合「原装备可能已被换下」的场景。`EquipmentCodeHandler` 处理 Base64 装备码：导出走剪贴板（先 ADB `cmd clipboard`，失败再 uiautomator2），输入优先 ADB `input text`（需 FastInputIME），失败回退 u2 `send_keys`；应用前先清空预览，仓库满时调 `handle_storage_full()`。装备码存放在任务配置的 YAML 文本字段（如 `GemsFarming.GemsFarming.EquipmentCode`），`GemsEquipmentHandler` 通过覆写 `equipment_code_config_key` 把存储位置指向该键。`EquipmentConfigHandler` 作为 `Combat` 基类，在 `BATTLE_PREPARATION` 界面点击 `FLEET_REORGANIZE` 进入整编，按 `Equipment.Config`（六个舰船站位的 `before`/`after` 装备码）在首次出击前执行 `equipment_handle_before()`，并在演习、余烬信标与信标协助任务收尾时执行 `equipment_handle_after()`。

任务换装的配置与恢复约定：

- 仅启用任务的 `Equipment.Enable` 且存在非空 `before` 时执行；省略的站位或阶段按空值处理，字符串去除首尾空白。`before` 为空的站位不处理；`before` 非空且 `after` 为空时，战后卸下该舰船的全部装备。未知站位、未知阶段、非字符串装备码及格式错误在进入整编、卸装之前统一拒绝，战后方案也同时预检。
- 控制方式沿用 `EquipmentCodeHandler.equipment_code_supported()` 的能力判定，不支持时在导航前抛 `RequestHumanTakeover`。启用 `Equipment.ClearBeforeApply` 时，先清空所有目标舰船，再依次应用方案，以便共用装备在舰船间转移；关闭时仍保留 `after` 为空就卸装的语义。
- 站位方案使用私有 `_equipment_config_apply/clear()`，不覆盖通用 `code_apply(name)` / `code_clear(name)`，因此命名方案、导出备份和 `last_code` 交接保持原语义。
- 整编与保存操作采用 2 秒点击间隔，以 10 秒双重计时器适配慢截图；退出以目标按钮正向出现为准，超时抛 `GameStuckError`。首次换装完成后先获取新截图，再决定是否点击出击。
- `_equipment_handle_before_flag` 只在战前方案保存成功后置位，战后方案保存成功后清除；失败不提前清除待恢复状态。它是当前处理器的内存状态，不保证进程中断后自动恢复。
- META 普通信标结束后若显示「模拟战斗」，恢复流程会点击该入口并确认弹窗，进入战斗准备页应用战后方案后返回。协助任务也可借用此入口，恢复后回到协助页；档案独立编队不参与恢复。入口选择与超时语义见[大世界辅助模块](../os/auxiliary.md)。

离线回归：`uv run python -m unittest tests.test_equipment_config tests.test_meta_beacon tests.test_equipment_transfer tests.test_equipment_clear_failure`，覆盖预检、命名接口兼容、跨舰卸装顺序、保存失败和 META 借用入口的恢复路径，不连接真实账号。

### 自动换装（module/auto_equip）

`AutoEquip.run()` 进船坞 → 进入第一艘非 NPC 舰船，循环：打开快速换装面板 → 模板匹配找出空槽（`empty_slot_plus.png`）→ 逐槽点开仓库，优先选第一件，灰色不可用时选第二件（`no_equipment.png` 判定无可用装备则跳过）→ 滑动到下一艘。`AutoEquip_ShipLimit` 限制舰船数（0 为一直换到手动停止），运行中持续检查 `config.stop_event`，置位即抛 `TaskEnd`。

### 仓库（module/storage）

- 开箱 `_storage_use_one_box`：点箱子 → 设数量（OCR + +/-）→ 确认 → 处理获得物品/装备确认 → 遇 `EQUIPMENT_FULL` 关弹窗后抛 `StorageFull`。`StorageBox`（拆箱任务）在其上增加保留阈值：某稀有度箱子存量 ≤ 阈值（`BoxDisassemble_*BoxLimit`）就跳过。
- 拆解 `_storage_disassemble_equipment_execute`：按稀有度筛选装备，用 `ItemGrid` 点选并累计数量（OCR 校验），逐次最多 40 件，翻页直到达标或列表空。
- `storage_disassemble_equipment` 组合两者：先开箱（2025.05 起开箱装备自动拆解），`StorageFull` 时转拆解腾位；`handle_storage_full` 则是给外部的通用弹窗处理器，处理完返回原页面。

## 10. 配置

| 配置 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `General.Retirement.RetireMode` | select | `one_click_retire` | `one_click_retire` / `enhance` / `old_retire`；`enhance` 失败时以一键退役兜底 |
| `General.OneClickRetire.KeepLimitBreak` | select | `keep_limit_break` | 一键退役对未满破重复船的保留策略；`do_not_keep` 时兜底链最后一步可重置为「全部」 |
| `General.OldRetire.N / R / SR / SSR` | checkbox | True / True / False / False | 旧退役的目标稀有度 |
| `General.OldRetire.RetireAmount` | select | `retire_all` | `retire_all` / `retire_10`，映射为数量上限 3000 / 10 |
| `General.Enhance.Filter` | textarea | None | 强化顺序，`>` 分隔舰种（dd>cl>…），非法项从剩余类型随机补 |
| `General.Enhance.ShipToEnhance` | select | `all` | `all` / `favourite` |
| `General.Enhance.CheckPerCategory` | input | 5 | 每类检查的舰船数 |
| `AutoEquip.AutoEquip.ShipLimit` | input | 0 | 换装舰船上限，0 为不设限 |
| `AutoEquip.AutoEquip.EnableSlot1..5` | checkbox | True | 参与自动换装的装备槽 |
| `BoxDisassemble.BoxDisassemble.UseWhiteBox / UseBlueBox / UsePurpleBox` | checkbox | True / False / False | 是否拆解对应稀有度箱子 |
| `BoxDisassemble.BoxDisassemble.*BoxLimit` | input | 2000 / 1000 / 100 | 各稀有度保留数量阈值 |
| `GemsFarming.GemsFarming.CommonCV / CommonCVFilter / CommonDD / CommonDDFilter` | select / textarea | `any` / 预设串 | 保留航母驱逐的筛选，过滤器无效时写回默认值（`cross_set`） |

另有两类跨任务状态写入配置（`module/config/config_manual.py` 定义）：`DOCK_FULL_TRIGGERED`（本轮退役已完成）与 GemsFarming 的 `EquipmentCode` YAML 文本（装备码存取目标）。`config_updater` 会为每个任务自动生成隐藏的 `Storage.Storage` 组，供任务运行期保存状态（如大世界商店的已购标记）。

## 11. 异常与错误处理

| 异常 | 原因 | 处理 |
| --- | --- | --- |
| `RequestHumanTakeover` | 一键/旧退役在多级兜底后仍无船可退 | 上抛终止任务，日志提示用户配置游戏内快速退役设置或开启对应稀有度 |
| `StorageFull` | 开箱时装备仓库无空间 | `storage_use_box` / `storage_disassemble_equipment` 内部捕获并转入拆解流程，不外泄 |
| `GameStuckError` | 强化状态机循环超 30 次 | 上抛，由调度器恢复机制处理 |
| `ScriptError` | 未知退役模式/状态函数/箱子稀有度，快速换装面板 10 秒内打不开 | 上抛，属编程错误 |
| `TaskEnd` | AutoEquip 响应 `stop_event` | 调度器按任务正常结束处理 |

退役确认循环以 `Timer(10)` 超时兜底（假设完成）而非无限等待；`handle_retirement` 内部捕获退役/强化异常并复位 `_unable_to_enhance`，防止同一弹窗反复触发造成死循环。

## 16. 修改注意事项

- **继承链顺序不可随意调整**：`Retirement → … → StorageHandler → UI` 的 MRO 决定了弹窗处理的可见性（例如装备码应用遇仓库满直接调 `handle_storage_full()`）。新增能力优先写为新 mixin 组合进任务类，而非加深这条链。
- **退役确认弹窗的层级是硬约束**：`EQUIP_CONFIRM` 可能无黑背景、`GET_ITEMS_1` 可能与 `IN_RETIREMENT_CHECK` 同屏，处理顺序（SR/SSR → 舰船确认 → 拆解确认 → 获得物资）经多个 issue（#838 #418）打磨，改动前先查历史。
- **快速退役设置只动 filter_5**：前 4 项被强制为 R/E/N/不留重复船，兜底重置时先保留用户已有 filter_5，逐级放宽；`server_support_quick_retire_setting_fallback()` 限 cn/en/jp，TW 不支持。
- **普通航母保留的状态位**：`_have_kept_cv` 在退役入口重置、确认前消费；`retire_gems_farming_flagships` 用保存/恢复现场的方式避免污染外层状态，且扫描时显式关闭稀有度子扫描器（颜色采样异常的 'unknown' 卡不能被漏掉）。
- **服务器差异**：JP 的船坞等级/情绪网格与 OCR 颜色不同（`dock.py`、`enhancement.py` 按服务器分支）；TW 的船坞筛选按钮布局不同（`@Config.when(SERVER='tw')`）；`SR_SSR_CONFIRM` 直点仅限 cn/jp/tw。资产按 `assets/{cn,en,jp,tw}/` 分服维护，改按钮后须跑 `uv run -m dev_tools.button_extract`。
- **auto_equip 的两张模板是模块私有资源**（`cv2.imread` + `lru_cache`），不进 `assets.py`，不走按钮提取流程。
- **拆解行为随游戏版本变化**：2025.05 起开箱装备自动拆解、拆解不再弹 `GET_ITEMS`，流程里的注释标注了版本节点；调整时注意兼容旧弹窗路径的注释依据。
- `FleetEquipment.fleet_equipment_take_on_preset()` 会调用父类中不存在的方法（当前无调用方），启用前需先补实现。

## 20. 相关模块

- [战斗系统](../combat.md)——`Combat` 组合 `Retirement`，船坞满弹窗由战斗流程触发。
- [其他游戏功能模块](misc.md)——科研（拆装备）、Awaken 等复用 `Dock`/`StorageHandler` 的模块。
- [基础层](../base/index.md)——`Filter`、`ButtonGrid`、`Scroll`、`Switch`、`Setting` 等本模块大量使用的基础组件。
- [UI 导航](../ui.md)——页面跳转与 `ui_ensure`/`ui_back`；仓库页 `page_storage` 注册于此。
- [OCR 系统](../ocr.md)——船坞数量、箱子数量、拆解计数、舰队名纠错均依赖 `Digit`/`Ocr`。
