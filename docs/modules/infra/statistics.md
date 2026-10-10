# 统计与数据提交（module/statistics、module/azur_stats、module/log_res）

> 把游戏运行期产生的掉落、战斗、资源与委托数据落成本地统计库，供 WebUI 统计页、LLM 日报与遥测提交消费。

## 1. 模块概述

AzurPilot 在执行任务时天然经过大量战斗结算与资源画面。这些画面里藏着用户关心的数字：打到了什么掉落、练级效率多少、行动力循环是否为正、委托攒了多少钻石。`module/statistics` 及其两个伴生目录就是把这些瞬时画面沉淀为可查数据的统计层。

这一层由五条相对独立的链路组成：

- **掉落统计链路**：战斗结算截图经 `AzurStats` 保存或解析入库。实时侧（`azurstats.py`）在战斗结束的上下文里收集截图；离线侧（`drop_statistics.py`）对历史截图文件夹做批量模板匹配与 OCR，导出 CSV。大世界掉落（除侵蚀1练级外）在「保存」与「上传」两个档位都会解析入库，`opsi_drop_stats.py` 把它们按窗口聚合成「大世界掉落」页的金菜与彩图纸收益。
- **CL1 统计链路**：`Cl1Database` 按「实例 × 月份」记录大世界侵蚀 1（CL1）与耄耋相接的战斗、明石、行动力等指标；`Cl1DataSubmitter` 把当月汇总匿名化后提交到官方遥测端点。
- **日报链路**：`DailySummaryStore` 持续采集任务运行与侵蚀 1 战斗事件，`DailySummaryService` 在触发窗口聚合事实、调用 LLM 生成文案并经 OnePush 推送。
- **仓库快照链路**：独立 `StorageStatistics` 任务进入普通仓库材料页，单遍完整扫描及同页核对通过后，把指定物品数量原子保存到 `config/azurpilot.db`。统计页面只读最近快照及成功扫描的历史趋势，刷新不启动游戏扫描。
- **资源收支链路**：`resource_flow.py` 在现有本地统计库中维护实例隔离的交易账本与库存基线；`resource_tracking.py` 旁路解析任务已有奖励画面，并记录已确认购买和科研启动的明确消耗。`LogRes` 对库存差额扣除已记交易，同一运行范围内的净变化归给任务，离线、跨任务及活动重置单列待归因。独立资源管理页按完整区间聚合来源、用途及依据，规则与扩展入口见 [资源管理](../webui/resource-management.md)。

`module/azur_stats/` 是掉落解析的场景层（原远程 AzurStats 上传的遗留名），复用 `module/statistics` 的物品识别原语；`module/log_res/` 则是资源变动的写入口，游戏代码通过属性赋值声明「资源变了」，由它决定写配置还是写快照库。

被动采集的统计不得影响游戏调度：落库失败不应中断正在进行的游戏业务。独立仓库统计则把完整性作为任务成功条件，识别或写入失败时保留旧快照、设置失败间隔并返回任务失败，不为此重启游戏。

## 2. 模块职责

### 仓库统计任务

入口为 `alas.py::storage_statistics()` → `module/storage/statistics.py`，默认关闭；可从统计页「仓库」分类手动运行，也可启用原生定时任务。任务复用 `StorageUI` 导航到材料页，不打开物品或消耗材料。

原调度直接放行仓库统计，不为这个只读任务执行石油控制的战役页观察；待执行的清油检查保留给下一项业务，系统恢复仍优先。

启用任务后，每次成功完成会将下次运行安排在 `StorageStatistics.StorageStatistics.RunIntervalDays` 天后，默认 7 天，可设置 1–3650 的整数天数；统计页面仍可手动执行。成功调度只传入换算后的 `minute`，不同时传 `success=True`，避免 `task_delay()` 取较近时间而覆盖自定义天数。失败仍使用原有 60 分钟失败间隔，保留旧快照。配置变更在下一次成功扫描后用于计算后续运行时间，保留已有预约时间及任务开关。

`statistics_recognition.py` 从完整方框动态定位物品，结合图标模板相似度、次优差距和稀有度底色确认身份，不读取物品名称文字。数量在图标右下角逐位匹配，并先核对全部首末位、字高、基线与间距；残缺首位不能被当成噪声删除。只有几何完整但二值字形匹配失败时，才使用 `amount_glyphs.py` 的原生灰度模板补充：以基线锚定 24×20 画布，保留抗锯齿，不随滚动后的二值包围盒变化缩放。灰度均方误差必须小于 0.006，与次优数字的差距必须大于 0.006；粘连字形仍使用已有的有界拆分，不强取灰度候选。灰度仍不确定时才尝试有限二值阈值，至少两个合格读数一致且无冲突才接受，不改变通用数字匹配门槛。

鱼雷研发图纸 UR 型补充了原生仓库模板 `GearDesignPlanTorpedoT5_warehouse.png`，来源见 `assets/stats/storage_items/README.md` 与独立原始帧回归。该变体解决奖励图与仓库采样相位的临界分数，身份匹配不包含数量，不降低相似度或次优差距门槛。

仓库专用模板位于 `assets/stats/storage_items/amount_digits.png` 和 `amount_glyphs.png`。灰度模板由 `uv run -m dev_tools.storage_amount_templates` 从人工核对的 125 个滚动数量切片与 25 个原始目录样本生成，覆盖金材料等不同原生字形。只合成横纵各四种有限采样相位，不使用 OCR 输出作标签；独立失败帧不参与生成。模板及生成机制不影响科研或大世界数字识别。

其他设备的抗锯齿可能使二值基线偏移一个像素。灰度直接匹配未通过时，在完整性检查之后，将原生字形在横纵 ±1px 内以 0.5px 步长对齐；每种数字在相同采样范围内取最小误差，仍要求误差小于 0.006、次优差距大于 0.006。此补充不缩放数字、不删笔画，也不将用户失败帧加入模板训练。

仓库目录只登记实际物品的同一身份变体，不能直接沿用共享掉落模板的别名。`PlateGeneralT4_2.png` 的 ALL 图案是定向部件 T4（Lua 30114/30900，使用后选择一类部件），与通用部件 T4（17004）不同，因此不作为仓库通用部件模板；未使用的定向道具不读取数量，不折算或合并统计。

材料列表使用右侧 `MATERIAL_STATISTICS_SCROLL` 翻页。按钮源区域须包含滑块在顶部和底部的完整范围，不能裁掉滑块端部。滑块有最小长度，不能直接用滑块长度推算列表长度。开扫时先回顶部，做一次有完整材料格核对的距离标定，再回顶部开始读取；标定要求七列完整且至少五列通过既有单格图像匹配，所有合格重叠行的位移必须一致（误差不超过 2px）；不能仅凭相似边框或降低单格阈值标定。此约束容许个别彩色格的动画变化，仍拒绝不足五列或多个矛盾位移。标定计算真实行距及「内容位移 / 滑块位移」。随后根据累计行号设置绝对滑块位置，每次前进三行，仅读取三行完整物品；成功分页再用首行位置修正累计比例，消除滑块像素取整误差。滑块位置、首行纵坐标与标定行号必须一致，缺行或行号偏差超过 0.12 行时拒绝拼接；滑块长度相对标定变化超过 2px 时拒绝沿用旧比例。到底后的短末页按实际行号核对目标物品和数量，不重复累计。

标定时尚未读取数量。优先使用包含数量细节的整格匹配；仅在没有合格重叠行时，额外核对排除边框和数量的图标主体：用 7×7 与 31×31 高斯差分去除低频动画，主体相似度仍须达到 0.985，底色差异不超过 45，并满足至少五列及唯一位移约束。整格已确认位移时不增加主体候选，避免相同图标排列、不同数量的行制造歧义。这个补充分支只用于测量运动；统计身份仍走目录模板，旧重叠去重中的完整数量约束不变。

每页先等待网格纵坐标和完整滑块位置稳定（`Timer(1.5, count=2)`，至少三个稳定后续帧），只做一次全目录模板匹配和完整数量读取。`Timer(.8)` 从首帧读取前开始计时，识别计算时间也计入两帧间隔，不在计算完成后重复等待。后续新截图仅匹配已确认目标自身的模板变体（相似度仍须至少 0.90）并核对完整数量，不重复遍历目录，不读取紫色或未知物品数量。模板和各采样相位在匹配前转为 `float32`，保留原有缩放、搜索范围、最高分、次优差距及底色约束。同页边框横坐标允许最多 2px 的轮廓抖动，纵坐标、滑块位置、目标模板、完整数量和空格仍须一致；超过边界立即停止并记录具体行列和前后位置，非目标物品的闪光动画不参与核对。完成一遍金/彩区域扫描后，由 `storage_snapshot.save_snapshot()` 在单个 SQLite 事务中提交，不再回顶扫描第二遍。

金/彩范围的结束依据国服 Lua `storehousescene.lua::sortItems()`：材料按 `order` 降序、稀有度降序、id 升序排列；当前目录目标均为 `order=0`、稀有度 4/5。活动礼物可能以更高 order 放在顶部，其中的紫色格不能作为终点。只有已读取普通目录目标，且下一组三行全部确认是紫色底时，才结束金/彩范围；否则继续按三行浏览直到滚动条底部。目录新增其他 order 或稀有度时须同步检查这个结束条件。

紫色过滤同时核对图标左上角与右上角的背景，每个角至少半数像素符合紫色条件才跳过；不能用平均混色判断紫色，也不因少量图案遮挡丢失背景确认。虹彩物品某一个角接近紫色时仍进入正常目标筛选，避免漏计彩色图纸或提前结束。

未运行显示「未扫描」，完整扫描未发现的目标显示未知数量，均不能推断为零。扫描或落库失败不会覆盖旧快照；数据库按实例隔离并纳入备份。目录版本包括清单、图标和数量字形，资源变化后旧快照会提示重新运行。

`recognize_rows(..., target_only=True)` 是任务使用的识别范围；`verify_targets()` 在已验证物理行号及同页位置后核对已确认目标；`same_targets()` 用于末页重叠校验，两者均不读取未知物品数量。离线兼容调用仍可使用默认识别及 `StorageTraversal.append()` 的唯一重叠模式：未知格的完整数量只作 `comparison_amount`，不赋予身份或计入统计；只有独立数量一致才能使用强虹彩去背景主体补充，仍须主体匹配，不能凭数量或共同边框判同物品。开扫标定使用 `same_card()` 核对完整物品图像的多列一致位移，不用未知格的猜测数量建立比例。

每页等待页面及滑块稳定的窗口为 `Timer(30, count=2)`；身份、完整数量、网格或行号识别一旦报错，立即停止整次扫描，不在原页反复识别，不继续翻页或启动第二遍。后续帧的目标模板、数量、位置或页面矛盾也立即失败，不清空已读数据再重跑目录。滚动条未到达同一指定位置时，最多重试三次定位；每次实际手势后重新开始页面等待窗口，慢后端也须获得完整的后续观察机会。不支持拖拽的控制后端只使用滑动，避免设备层拖拽回退额外点击。只有页面成功核对并拼接后才清除连续操作记录；失败保留旧快照并按任务失败间隔延后，不跳过首行或残缺数量。

`storage_snapshot.get_storage_timeline()` 在只读连接中用单条 SQL 查询成功扫描历史，按实例、完成时间窗口与条数过滤。仓库分类复用资源趋势的指标选择、折线/K 线、采样粒度、缩放、起止时间、原始记录与导出，支持最近 1/7/30/90/365 天。图表仅使用已确认数量，不补零或在区间边缘补造点；最新清单仍展示最近完整扫描。没有历史扫描时不会创建数据库。

当前模板仅经过国服 1280×720 截图验证。离线验证入口为 `tests/test_storage_statistics.py`、`tests/test_storage_amount_glyphs.py`、`tests/test_storage_statistics_recovery.py` 、`tests/test_storage_statistics_paging.py` 和 `tests/test_storage_overlap_history.py`，覆盖三行标定、紫色边界、行号完整性、独立数量失败帧及采样相位、单遍扫描、错误立即退出、同页快速核对及旧重叠兼容。合成相位与离线回放不能代替整仓实机验收；真实验证需指定实例与任务范围，并使用设备内置原生截图。

### 负责

- 战斗/搜索结算截图的保存（`DropRecord_SaveFolder`）与本地解析入库（SQLite `config/azurpilot.db`）
- 物品识别原语：`Item`/`ItemGrid`/`AmountOcr`（模板匹配 + 带上限验证的数量 OCR）——商店、委托、仓库等模块都复用这一层
- CL1 月度统计库（`config/azurpilot.db`）的读写与旧数据迁移
- 侵蚀 1 遥测提交（`Cl1DataSubmitter` → `ApiClient`）
- 日报运行时事件采集、周期去重、LLM 文案生成与推送
- 资源快照记录（`resource_stats`）与资源变动入口（`LogRes`）
- 掉落截图按保留天数清理，过期后删除或备份到 `bak/`（`drop_cleanup`）
- 大世界运行期统计事件的统一落库入口（`opsi_runtime`）
- 大世界统计的原生存储与旧加密数据只读迁移（`module.persistence`）
- 离线批量掉落分析工具（`DropStatistics`，独立运行）

### 不负责

- 掉落截图的实时采集时机——由战斗/地图流程决定（`drop.handle_add()`），统计层只被动接收
- WebUI 的图表渲染与 API 编排——`module/api/statistics_service.py` 只是聚合查询本层导出的函数
- 推送通道实现——OnePush 由 `module/notify` 承担，日报只调用 `handle_notify()`
- 经验表数据本身——`LIST_SHIP_EXP` 来自 `module/os/ship_exp_data.py`
- 设备识别——`get_device_id()` 属于 `module/base/device_id.py`

## 3. 模块位置

```
module/statistics/
├── azurstats.py              # AzurStats：掉落记录提交、指挥喵 farming 汇总
├── cl1_database.py           # Cl1Database：月度统计库（单例 db）
├── cl1_data_submitter.py     # CL1 遥测提交器
├── daily_summary.py          # DailySummaryService：日报触发与生成
├── daily_summary_store.py    # DailySummaryStore：日报事件库
├── daily_summary_text.py     # 日报 system prompt
├── commission_income_stats.py# 委托收益聚合（day/week/month/interval）
├── research_drop.py          # 科研掉落解析（队列页角标读期数 + 收获帧识别）
├── research_stats.py         # 科研掉落聚合（按期 / 心智物资两种口径）
├── resource_stats.py         # resource_snapshots 快照与区间摘要
├── storage_snapshot.py       # 独立仓库扫描的完整快照与只读查询
├── ship_exp_stats.py         # ShipExpStats：战斗计时与经验效率
├── opsi_month.py             # OpsiMonthStats：月度大世界汇总与时间线
├── opsi_runtime.py           # 大世界运行期事件 → 落库的集中入口
├── opsi_drop_stats.py        # 大世界掉落聚合（部件、图纸、材料、计划及突破部件）
├── opsi_secure.py            # 旧统计数据解码原语，仅用于迁移或显式旧工具
├── drop_statistics.py        # 离线批量掉落分析（可独立运行）
├── drop_cleanup.py           # 掉落截图保留天数清理与备份
├── get_items.py / item.py / battle_status.py / campaign_bonus.py
│                             # 物品/敌人识别器（被 azur_stats 与离线分析复用）
├── amount_digits.py          # 原生数量字形匹配与有界粘连拆分
├── utils.py                  # pack/unpack、ImageError、load_folder
└── assets.py                 # 识别资源（button_extract 生成，勿手改）

module/azur_stats/
├── scene/base.py             # SceneBase：加载截图、parse_scene 骨架
├── scene/operation_siren.py  # SceneOperationSiren：大世界完整场景解析
├── image/base.py             # ImageBase：classify_server 多服务器识别
├── image/get_items.py        # 战斗结算「获得道具」识别（AutoSearchAmount 数量 OCR 也在这里）
├── image/auto_search_reward.py # 自律寻敌奖励页识别（AutoSearchItemGrid）；AutoSearchAmount 从本模块导入
├── image/opsi_reward.py / opsi_zone.py # 大世界奖励/区域识别
└── assets.py                 # 识别资源（生成文件）

module/log_res/
└── log_res.py                # LogRes：Dashboard 资源赋值入口
```

模板资源：`assets/stats_basic/`（基础物品模板，掉落统计启动时复制到用户目录）、`assets/stats/`（opsi_items、opsi_reward_items 等场景模板）。

**两个模板集不能互相顶替**：`opsi_reward_items`（自律寻敌结算页）与 `opsi_items`（获得道具页）里的图标缩放不同。`SceneOperationSiren.ITEM_TEMPLATE_FOLDER` 用的是 `opsi_items`；舰载机部件 T4 的原生弹窗变体为 `PlatePlaneT4_2.png`，通用部件、军用电子元件和彩色原型部件也有原生弹窗模板。通用装备研发图纸 `GearDesignPlanT4/T5` 与舰炮、鱼雷、防空炮、舰载机专用图纸是不同物品，名称按 Lua 物品定义确认，不能合并。

大世界掉落页固定展示部件 T4、舰炮/鱼雷/防空炮/舰载机研发图纸 SSR/UR 型、通用装备研发图纸 UR 型，以及特种钢材、军工级电子元件、HBX炸药、氟橡胶、超导铜、钛合金、机密/绝密实验计划和特装型突破部件。范围在 `opsi_drop_stats.py`，名称和稀有度在 `assets/stats/opsi_item_names.json`；这些物品进入收益、明细、记录和总计，仍受实例、时间与任务筛选。已入库的物品直接纳入查询，不重写数据库；尚未识别的数字编号不会自动改名。

实验计划模板统一按图标稀有度命名：紫色 T3、金色 T4、彩色 T5，与英文物品名称中的 T1/T2/T3 不同。获得道具页原来的 `OrdnanceTestingReportT1/T2` 模板改为 `T3/T4`，历史金计划 `OrdnanceTestingReportT2` 在展示时归入 T4，避免分成两行。两类奖励页都按底色排除错误等级的图纸、实验计划和突破部件；两种布局仅对纸类同级候选放宽匹配阈值，突破部件保持原阈值，并接收第三种 Boss 奖励布局。

新增模板来源记录在 `assets/stats/opsi_template_sources.json`。机密计划与突破部件的弹窗模板来自 `screenshots/opsi_abyssal/1790326881455.png` 和 `screenshots/opsi_month_boss/1790872111832.png` 的原始 1280×720 帧。绝密计划未在本地掉落截图及归档中找到，暂复用已有 1280×720 仓库原图中的模板并归一为 96×96；它的真实结算识别仍待获得样本后验证，不能把仓库参考图验证当作实机掉落验证。

**保留完整数量，再排除图标干扰**：科研、委托与大世界弹窗的默认数量区为 `(50, 72, 94, 94)`；大世界图纸/实验计划为 `(50, 76, 94, 94)`，作战补给凭证为 `(28, 72, 94, 94)`。自律寻敌原生 64px 格使用 `(15, 49, 63, 63)`，容纳五位凭证数量。数字由 `amount_digits.py` 按字高、基线、间距和模板逐位匹配，既保留重复数字与首尾位，也排除纸角、齿轮等残影；匹配不确定时才使用配置中的 OCR 后端。普通战斗的 `GetItemsStatistics` 默认数量区保持原值，科研通过实例属性覆盖。

**大世界的稀有度与单格上限**：白纸图标先根据金/彩/紫底色限定等级，再匹配图案；降低到 0.6 的阈值只适用于纸类候选，其他物品保持原阈值。`SceneOperationSiren` 在两种布局中均将彩色装备研发图纸和原型部件的单格数量限制为 2，多格、多帧仍按真实数量累加。特装原型是另一种物品，不能套用此上限。数量无法确认只跳过该格，保留同页其他有效物品。

**复用解析器时保留已知物品身份**：`ItemGrid` 先在达到阈值的已知模板中选择最佳匹配；只有没有合格的已知候选时，才查询数字编号的临时未知模板。前一张动画画面生成的未知模板即使与当前像素更接近，也不能覆盖已确认的物品名。

## 4. 核心入口

| 入口 | 用途 |
| --- | --- |
| `ModuleBase.stat`（`module/base/base.py` 的 cached_property） | 游戏任务获得 `AzurStats` 实例的唯一途径；`stat.new(genre, method=...)` 开启一次掉落记录 |
| `AzurStats.new()` → `DropImage` | 上下文管理器：战斗流程内 `drop.add()`/`drop.handle_add()` 收集截图，退出时自动 `commit()` |
| `Cl1Database.db`（模块级单例） | 各任务写入月度统计；同步方法 + `async_*` 系列（走 `async_executor`） |
| `opsi_runtime.record_*` / `start_/finish_battle_timer` | 大世界任务上报战斗、明石、吊机等事件的规范入口，避免任务代码直接写库 |
| `LogRes(config).<Res> = value` | 资源变动的声明式入口：写 `Dashboard.<Res>` 配置 + 触发资源快照 |
| `alas.py _start_daily_summary_scheduler` | 日报独立检查线程（启用时随调度器启动） |
| `statistics.report` / `statistics.refreshLoot` / `statistics.resources`（API 方法） | WebUI 统计页读取本层数据 |
| `python -m module.statistics.drop_statistics` | 离线批量掉落分析脚本 |

## 5. 核心组件

### 掉落识别（module/statistics）

| 组件 | 职责 |
| --- | --- |
| `Item` | 单个物品：模板匹配名 + 数量。名称 setter 自动剥离数字后缀（`Javelin_2` → `Javelin`）；`__eq__`/`__hash__` 基于名称，支撑两页掉落的去重合并 |
| `ItemGrid` | 物品网格：按 ButtonGrid 定位槽位，模板匹配（优先命中频率高的模板，未命中自动建数字编号新模板）+ 数量/价格 OCR + 标签颜色识别 |
| `AmountOcr` | 场景可启用逐位字形匹配和严格上限；模板不确定时回退 OCR 与碎片过滤。科研、委托、大世界超限仍无法确认时返回 0，不截断猜值；未启用的旧调用方保留原行为 |
| `DigitTemplates` | 匹配 `assets/stats/amount_digits/` 的原生普通/粗体数字模板，有界拆分粘连字形；候选接近或相似度不足时返回 `None` |
| `GetItemsStatistics` / `CampaignBonusStatistics` / `BattleStatusStatistics` | 三个离线统计器：获得物品页（1/2/3 行网格自动判断奇偶布局）、战役加成弹窗（金币数量校验截图有效性）、敌方舰队名 OCR |
| `DropStatistics` | 离线批量处理器：两步工作流（`extract_template` 提模板 → 手动重命名 → `extract_drop` 导出 CSV） |

### 实时掉落记录（azurstats.py）

| 组件 | 字段/方法 | 说明 |
| --- | --- | --- |
| `DropImage` | `save` / `local` | 两个布尔决定退出时是否存图 / 是否解析入库；`__bool__` 为 False 时整个上下文零开销 |
| `DropImage` | `handle_add(main, before)` | 处理信息栏遮挡后等待 `WAIT_BEFORE_SAVING_SCREEN_SHOT` 秒再截图加入 |
| `AzurStats` | `commit(images, genre, save, local, combat_count)` | 垂直拼接截图，save 走后台线程，local 持 `_record_lock` 同步解析 |
| `AzurStats` | `_database().path` | 普通总库中的掉落明细；`LOCAL_DB` 仅保留为旧路径迁移入口（opsi_items 表，带 device_id/genre/hazard_level 维度） |
| `AzurStats` | `get_meowofficer_farming()` | 从明细库重算 6 侵蚀等级的「平均黄币/轮、平均金菜/轮……」在事务中写入 `farming_aggregates`，WebUI「大世界掉落」页读取对应实例范围；普通读取不改变刷新时间 |
| `AzurStats` | `is_opsi_drop_genre()` | 判定某个 genre 是否要解析入库：大世界任务都算，唯侵蚀1练级除外（它的收益在「大世界总结」页看） |
| `AzurStats` | `load_opsi_drop_rows()` | 按实例/时间窗口/任务读明细，供 `opsi_drop_stats.collect()` 汇总；任务范围直接由上面那套常量生成 |

大世界采集必须把同一个 `DropImage` 传入自律守护的地图事件、`interrupt_auto_search(drop=...)` 和 `map_exit(drop=...)`。隐秘海域使用 `run_auto_search(exit_map=True)`，将退出时的奖励一起提交；深渊与月度 Boss 在 `boss_clear()` 内退出。`SceneOperationSiren` 接收三种获得道具布局；单帧出现信息栏遮挡等 `ImageError` 时只跳过该帧，保留同包其他奖励。海域 OCR 失败不丢物品，展示可根据独立任务确定来源类型，但不猜海域编号或侵蚀等级。

统计页仍按金菜（部件 T4）与彩图纸（研发图纸 T5，包括通用装备研发图纸）展示。独立或共用掉落开关的任务始终可筛选；任务次数取完整时间窗口，筛选仅影响收获明细。窗口内没有这两类物品的奖励不显示在掉落记录表。`/opsi-items/` 先查 `opsi_reward_items`，缺图时回退到 `opsi_items` 同名模板；`/research-items/` 先查 `research_items`，再查 `stats_basic`。图标回退只影响展示，不改变识别模板选择。

### 普通总库与旧数据迁移

普通数据统一进入实际配置目录的 `azurpilot.db`，资源、掉落、仓库、月度事件、舰船与日报均使用原生列及关联表。自由参数和无法无损投影的兼容字段使用类型化树，不在数据库保存整行 JSON。完整结构、公开字段位序、迁移和恢复流程见 [普通业务数据存储](persistence.md)。

首次启动在业务 worker 之前锁定旧源，先通过 SQLite 备份接口保存含已提交 WAL 的源库及安全恢复材料，再在临时总库中转换、对照业务快照和检查完整性，成功后切换。`OPSIV1.`/`OPSIV2.`、旧 AES 月份及包装文件使用只读解码，不调用自动改写、隔离或撤销密钥的旧初始化。失败保留原件并停止启动，不以空数据替代。正式库丢失且完成标记仍在时必须恢复备份。

日常查询不再读取旧普通库、JSON 或 CSV。资源趋势的 `include_opsi=False` 仍保留原返回规则，从原生列排除大世界字段。交易认证历史继续使用独立安全库，不从普通观察值重建身份或认证链。

### CL1 月度库（cl1_database.py）

`cl1_months` 以 `(instance, month)` 为主键；计数、事件、分桶样本及收益分别投影到关联表。适配器继续返回原月度快照，字段存在标记保留部分记录、显式空值与空集合。公开快照的关键字段：

| 字段 | 说明 |
| --- | --- |
| `battle_count` / `akashi_encounters` / `akashi_ap` | CL1 战斗次数、明石遭遇、明石购得行动力 |
| `ap_snapshots` / `asset` | 行动力快照；资产 = 总体力 × 56.67（CL5 效率）+ 黄币 |
| `yellow_coin_snapshots` / `coins_snapshots` | 凭证分时快照（后者上限 500 条） |
| `meow_battle_raw_count` / `meow_battle_count` | 耄耋真实战斗场次 / 有效轮数（侵蚀 2-3 每轮 2 场、4-6 每轮 3 场折算） |
| `meow_hazard_stats` | 按侵蚀等级拆分的桶（次数、耗时样本、明石） |
| `siren_research_devices` | 塞壬研究装置（吊机）计数，cl1 与 meow 分源 |
| `commission_income_entries` / `running_gem_commissions` | 委托收益明细（上限 5000）与运行中钻石委托（跨月合并） |
| `research_drop_entries` | 科研掉落明细：项目代号、期数、物品（上限 5000，imgid 去重） |

关键机制：`_stats_transaction()` 用 `BEGIN IMMEDIATE` 取写锁，跨线程/进程串行化整个「读-改-写」，避免并发覆盖；`save_stats` 只做整体替换，增量修改必须走事务内方法。数据库优先，旧 JSON 仅补缺失月份。样本与列表的裁剪、旧计数回填及金币清理版本保留原规则；跨月委托收益、钻石结算和运行记录移除在同一个总库事务内提交。

证券历史的旧数据来源由 `cl1_legacy.read_ap_snapshots()` 在只读连接中提供，复用 CL1 的旧密钥派生和 AES-GCM 解码格式，不创建、删除或改写统计库。原实例首次升级时仅导入上海时区当月 `ap_snapshots` 中带 `ap_total` 的实际记录，再与中央认证历史合并进入持久补传队列；上月及更早月份不读取，注册时间不作为截断条件。已开户账户同样补传，数量不设 2000 条上限。同毫秒冲突以中央来源为准。当月旧统计读取失败时保留原件与重试资格，状态消息说明原因，每五分钟重试，不回滚中央历史、不阻断注册、登录及新记录同步；中央来源或补传队列的认证失败仍停止同步。迁移完成状态由实例身份和补传检查点认证，重命名保留原统计来源，复制及重建实例不继承；完成后不再读取旧库修改。没有总量的 `ap` 只表示当前行动力，不能当作证券股价。

### 日报（daily_summary*.py）

| 组件 | 说明 |
| --- | --- |
| `DailySummaryService.check_due()` | 校验触发时间格式与服务器归属，计算最近一个服务器日窗口；错过宽限期（5 分钟）则 `mark_period_skipped` 防补发，到点则 `claim_period` 原子抢占后起后台线程 |
| `build_facts()` | 聚合任务运行、资源首末值、委托收益、侵蚀 1 事件四类事实；任何读取失败降级为 `data_quality.unavailable` 的明确缺失项，模型只拿可信数据 |
| `DailySummaryStore` | SQLite `config/azurpilot.db`；`busy_timeout=50ms`——写不进就放弃，宁可在日报里标「未采集」也不让调度等锁 |
| `daily_summary_periods` | 周期状态：`generating → sending → sent / failed(配置/LLM/推送/中断)`；`skipped` 表示已错过不补发 |
| `DAILY_SUMMARY_SYSTEM_PROMPT` | 猫娘角色设定 + 术语表，要求只使用 facts 中明确的数据 |

## 6. 工作流程

### 掉落记录链路（以一次大世界自动搜索为例）

```mermaid
flowchart LR
    A[战斗/搜索流程] -->|stat.new genre, method| B[DropImage 上下文]
    B -->|结算画面出现| C[drop.handle_add<br/>处理信息栏+截图]
    C --> B
    B -->|with 退出| D[AzurStats.commit]
    D -->|save=True| E[后台线程存图<br/>screenshots/&lt;genre&gt;/]
    D -->|local=True| F[SceneOperationSiren 解析]
    F --> G[opsi_items 明细入 SQLite]
    G --> H[get_meowofficer_farming 重算原生汇总表]
    G --> J[opsi_drop_stats.collect<br/>统计页「大世界掉落」]
    D --> I[cleanup_drop_screenshots_if_due<br/>节流 1 小时]
```

关键分叉在 `new()` 的 `method` 参数：配置值 `do_not` 产生空的 DropImage（零开销）；大世界掉落（`is_opsi_drop_genre()` 认可的任务，侵蚀1练级除外）的 `save` 与 `upload` **都会**解析入库，区别只在要不要把截图落盘——`upload` 这个名字是远程 AzurStats 时代的遗留，现在的「上传」就是「解析入本地库、不落盘」。解析中发现只有数字代号的未识别物品时，把结算截图画上红框另存到 `screenshots/unknown_items/`，供人工补模板。

### 日报流程

```mermaid
flowchart TD
    A[日报线程每秒检查] --> B{Enable?}
    B -->|否| A
    B -->|是| C[解析触发时间/服务器<br/>计算服务器日窗口]
    C --> D{在触发窗口内?}
    D -->|错过| E[mark_period_skipped<br/>本期不补发]
    D -->|到点| F[claim_period 原子抢占]
    F --> G[后台线程 build_facts<br/>聚合 automation/resources/commission/cl1]
    G --> H[OpenAI 兼容接口生成文案<br/>最多 3 次]
    H --> I[OnePush 推送<br/>最多 3 次]
    I --> J[(daily_summary_periods<br/>sent/failed)]
    J --> K[cleanup 清理 35 天前记录<br/>超 1 天的 generating/sending 标为 interrupted]
```

事实聚合的四个来源各自独立降级：任务运行摘要来自日报库自身（调度器在任务前后打点）、资源变化来自 `resource_stats` 的窗口首末快照、委托收益来自 `cl1_db` 的按月条目、侵蚀 1 事件来自 `record_cl1_battle_event` 逐场打点。LLM 配置不完整或 OnePush 无 provider 时直接置 `failed(error_kind='configuration')`，不调用模型。

## 7. 调用关系

### 上游

| 模块 | 关系 |
| --- | --- |
| `module/base/base.py`（ModuleBase） | 持有 `stat`（AzurStats），战斗、委托、科研、喵箱、大世界各流程用 `stat.new()` 包住结算段 |
| `module/combat`、`module/os`、`module/os_combat`、`module/meowfficer`、`module/research` | 掉落记录的主要产生方；大世界战斗还调用 `opsi_runtime` 的计时器 |
| `module/commission` | 委托结算时调 `cl1_db.add_commission_income`（含钻石委托的事务内结算）与收益截图落盘 |
| `module/shop_status` / `os_status` / `campaign_status` 等 | 通过 `LogRes` 属性赋值上报资源变化 |
| `alas.py` | 日报调度线程 + 任务运行打点 |
| `module/api/statistics_service.py` / `runtime_service.py` | WebUI 统计页的聚合查询层 |

### 下游

| 模块 | 用途 |
| --- | --- |
| `module/ocr` | `AlOcr`/`Ocr`/`Digit` 数量与地名识别 |
| `module/os/globe_zone.ZoneManager` | OCR 地图名 → 标准区域（zone_id/hazard_level）映射 |
| `module/base/api_client.py` | CL1 遥测 POST（双端点故障转移，仅含哈希 device_id） |
| `module/base/async_executor` | 所有 `async_*` 统计写入的执行器 |
| `module/notify` | 日报与委托收益推送（`handle_notify`） |
| `openai` SDK | 日报文案生成（复用 Error 任务组的 LLM 配置） |

## 8. 数据流

```
战斗结算画面
  → DropImage.add()（截图缓存）
  → commit()：pack 成长图，文件名 = 13 位毫秒时间戳
      ├─ save → {DropRecord_SaveFolder}/{genre}/{ts}.png（后台线程）
      └─ local → SceneOperationSiren.parse_scene() → DataOpsiItems
              → opsi_items 表（config/azurpilot.db）→ 重算 farming CSV
              └─ 统计页「大世界掉落」= opsi_drop_stats.collect()（指定部件、图纸、材料、计划及突破部件）
              └─ 有未识别物品 → unknown_items/ 红框标注图

任务事件（alas.py 打点）          → daily_summary_task_runs
侵蚀1战斗（ShipExpStats.on_battle_end）
  ├─ source=cl1 → ship_exp_daily 日效率 + daily_summary_cl1_events
  └─ meow 来源只进 cl1_db 耙耋桶
资源 OCR（LogRes 赋值）
  ├─ Dashboard.<Res>.Value/Record → 配置文件（WebUI 仪表盘）
  └─ 全量快照 → resource_snapshots（config/azurpilot.db）

查询侧：
  statistics.report → opsi_month / commission_income_stats / research_stats / ship_exp_stats
                    / azurstats / resource_stats → metrics + series + tables
  日报窗口 → 日报库 + resource_stats + cl1_db → facts JSON → LLM
```

## 9. 状态模型

日报周期是本层唯一显式的状态机（`daily_summary_periods.status`）：

```mermaid
stateDiagram-v2
    [*] --> generating: claim_period（INSERT OR IGNORE 抢占）
    generating --> sending: 文案生成成功
    generating --> failed: 配置缺失 / LLM 三次失败
    sending --> sent
    sending --> failed: 推送三次失败
    generating --> skipped: 错过触发窗口（mark_period_skipped）
    generating --> failed: 进程中断后 cleanup 补记
```

| 状态 | 含义 |
| --- | --- |
| generating / sending | 生成中 / 推送中；进程意外退出后由 `cleanup()` 在次日改判 `failed(error_kind='interrupted')`，不补发 |
| sent / failed | 终态；`error_kind` 区分 configuration / llm / notify / internal / interrupted |
| skipped | 已错过窗口，防止进程恢复后补发旧日报 |

## 10. 配置

| 配置 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `Alas.DailySummary.Enable` | checkbox | false | 日报开关；关闭时调度器不创建任何日报线程与存储 |
| `Alas.DailySummary.TriggerTime` | str | "20:00" | 触发时刻（服务器时区，24 小时制 HH:MM），由 `parse_daily_summary_trigger` 校验 |
| `Alas.DropRecord.SaveFolder` | str | ./screenshots | 掉落截图根目录（按 genre 分子目录） |
| `Alas.DropRecord.RetentionDays` | int | 0 | 截图保留天数，0 = 不清理 |
| `Alas.DropRecord.BackUpMethod` / `ZipMethod` | option | zip / zip | 过期截图的处理方式（delete / zip / copy）与压缩格式（bz2 / gzip / xz / zip）；备份落在各来源目录下的 `bak/` |
| `Alas.DropRecord.CombatRecord` / `ResearchRecord` / `CommissionRecord` | option | do_not | 各场景掉落记录方式（do_not / save / upload / save_and_upload） |
| `Alas.DropRecord.OpsiHazard1Leveling` / `OpsiMeowfficerFarming` / `OpsiDaily` / `OpsiObscure` / `OpsiAbyssal` / `OpsiStronghold` / `OpsiExplore` / `OpsiOther` | option | upload | 大世界掉落记录方式，按任务拆分（前七项依次为侵蚀1练级、耄耋相接、大世界每日、隐秘海域、深渊海域、塞壬要塞、每月开荒）：跨月每日跟大世界每日、档案坐标跟隐秘海域、月度Boss跟深渊海域共用开关，`OpsiOther` 兜底没列出的任务；运行期由 `opsi_drop_record(config)` 按 `config.task.command` 取用。除侵蚀1练级外，`save` / `upload` / `save_and_upload` 都会解析入库（区别只在要不要把截图落盘），侵蚀1练级只落盘截图、不入掉落统计 |
| `Alas.DropRecord.CommissionIncomeScreenshot` | option | save | 委托收益截图开关 |
| `Alas.DropRecord.ResearchRecord` | option | do_not | 科研掉落截图开关；`save` / `upload` / `save_and_upload` 都会统计（区别只在要不要把截图落盘） |
| `Alas.DropRecord.TelemetryReport` | bool | true | CL1 遥测提交开关（hazard_leveling 里检查） |
| `Alas.Error.LlmApiKey/LlmApiBase/LlmModel` | str | "" | 日报 LLM 配置（与错误上报共用） |
| `Alas.Error.OnePushConfig` | str | "" | 推送通道配置 |

关联关系：日报的 LLM 与推送配置刻意复用 `Error` 组，避免两套密钥；掉落记录各场景开关决定 `DropImage.save/local`。除侵蚀1练级外，大世界任务的 `save` / `upload` / `save_and_upload` 均本地解析，`do_not` 不统计。日报线程不持有完整配置对象——`alas.py` 只传 `SimpleNamespace` 快照并按配置文件 mtime 热读，避免与任务线程争用配置对象。

## 11. 异常与错误处理

| 异常/失败 | 原因 | 处理 |
| --- | --- | --- |
| `ImageError` 族（GetItemsInvalid、OpsiZoneInvalid…） | 截图不是预期结算页 / 信息栏遮挡 | `commit`/离线解析捕获后记 warning 跳过该截图，不影响战斗流程 |
| 掉落数量为 0 或仍超上限 | 数字不完整、图标残影或字形不确定 | 科研、委托、大世界按格记 warning 并跳过，保留同页其他掉落及原截图；不截断猜值 |
| SQLite 锁竞争 | WebUI 线程与调度线程并发写 | 日报连接 `busy_timeout=50ms` 快速失败 + 内存暂存降级事件；普通总库写事务用 `BEGIN IMMEDIATE` 串行化 |
| 日报数据库写失败 | 磁盘/锁异常 | 记入 `daily_summary_collection_gaps`，该周期日报标「数据不完整」 |
| LLM 空响应 / 调用失败 | 网络、配额 | 最多 3 次重试，仍失败置 `failed(error_kind='llm')`，本期不发送 |
| OnePush 失败 | 配置错误、服务不可达 | 同一文案重发 3 次，仍失败置 `failed`，不重试整期 |
| 遥测提交失败 | 网络不通 | 仅 debug 日志，下个 10 分钟窗口再试 |

原则：**统计链路的异常一律不向游戏调度传播**。`record_task_start/finish`、资源快照、战斗计时等都有 try/except 包裹；只有 `Cl1Database.save_stats` 这类显式写接口会把异常传给调用方（由调用方决定回滚语义）。

## 12. 并发与线程模型

统计层被至少四类线程同时访问：游戏任务线程（同步写）、`async_executor` 工作线程（异步写）、日报后台线程（生成与推送）、WebUI 工作线程（查询）。

侵蚀1明石遭遇由 `opsi_runtime.record_cl1_akashi_encounter()` 提交到串行异步队列，并返回写入 Future，主游戏流程不做同步回读。`increment_akashi_encounter(instance, month=None)` 在事务提交后返回实际累计次数；传入事件发生月份避免跨月排队计入下个月。完成回调只在提交成功后打印累计次数，失败记录异常并保留事务回滚；进程正常退出沿用异步执行器的队列刷新。

耄耋相接同样通过 `record_meow_akashi_encounter()` 返回写入 Future。`increment_meow_akashi_encounter(instance, hazard_level, month=None)` 保留侵蚀等级分桶，提交后才返回该桶累计次数；月份在事件入队时固定，回调打印实际次数或记录写入异常。任务的 `_meow_record_akashi_if_solved()` 消费已解决的明石标记，避免后续轮次重复计数。该链路原本已异步，本次语义是确认实际落库，不增加游戏主线程等待。

| 对象 | 保护方式 |
| --- | --- |
| `Cl1Database` | 每次读改写都在 `_stats_transaction()`（`BEGIN IMMEDIATE`）内完成，跨线程与跨进程串行化；不依赖调用方持锁。跨月结算在一个事务里同时写来源月与归档月 |
| `AzurStats` | `_record_lock` 串行化本地解析（解析是 CPU 密集的 OCR），`_local_lock` 串行化 SQLite 插入；save 单独开短命线程避免阻塞战斗 |
| `DailySummaryStore` | `RLock` + 每次操作新建短连接（`_ClosingConnection` 立即释放，防 Windows 文件锁残留）；采集失败先缓存内存、下次可写时补记 |
| `DailySummaryService` | `_lock` 保护 `_active/_processed_periods` 集合；周期幂等性主要靠数据库 `claim_period` 的 INSERT OR IGNORE，进程内集合只是去重快路径 |
| `resource_stats` / `_loot_lock` | 模块级锁串行化快照写入与 farming 重算 |
| 日报线程生命周期 | 由 `alas.py` 的调度器 loop 启停；`check_due` 里启动的生成线程是 daemon，异常全部隔离在 `_generate_and_send` 内 |

## 13. 缓存与持久化

| 存储 | 内容 | 写入时机 | 清理 |
| --- | --- | --- | --- |
| `config/azurpilot.db` | `opsi_items` 掉落明细 + `resource_snapshots` 资源快照 | 每次 commit / LogRes 资源变化 | 不自动清理明细 |
| `config/opsi_secure/` | 旧加密环境描述与恢复材料 | 仅历史版本产生 | 迁移不改写或销毁，随备份保留 |
| `config/azurpilot.db` | CL1 月度统计（instance×month） | 各 `async_*` 方法即时写 | 快照列表内部截断（500/5000 条） |
| `config/azurpilot.db` | 按实例保存完整仓库物品快照 | `StorageStatistics` 单遍完整扫描及同页核对后原子提交 | 保留已完成扫描 |
| `config/azurpilot.db` | 日报任务事件、周期状态、采集缺口 | 任务前后、战斗结束、日报流程 | `cleanup()` 保留 35 天 |
| `config/azurpilot.db` 的 `farming_aggregates` | 全局/实例 farming 汇总 | 显式刷新或实例缓存缺失重算 | 事务更新六等级，读取不刷新时间 |
| `config/azurpilot.db` 的六张 `ship_exp_*` 表 | 战斗耗时、每日经验及升级进度 | 显式保存或业务更新 | 样本 100 条 / 日统计 30 天 |
| `screenshots/<genre>/`、`log/commission_rewards/<instance>/<月份>/` | 掉落与委托截图 | commit / 委托结算 | `DropRecord_RetentionDays` 天数清理（节流 1 小时），过期后按 `DropRecord_BackUpMethod` 删除 / 拷贝备份 / 压缩备份到 `bak/` |

首次迁移可读取旧位置 `log/cl1/cl1_data.db`，保留旧库、JSON、CSV 和 `.bak`。后续只访问总库。每日备份使用 SQLite 备份接口保存总库，并按专用保护机制备份安全数据库、注册信息与密钥材料。

## 14. 生命周期

`Cl1Database.db`、日报 `DailySummaryStore`、遥测提交器 `_submitters` 都是进程级单例，随首次 import 惰性创建，无显式销毁。`AzurStats` 不是单例——每个 `ModuleBase` 持有自己的实例（只封装 config），共享的锁在类属性上。日报线程随调度器 `loop()` 启动、更新事件或进程退出时通过 `_stop_daily_summary_scheduler` 停止；日报关闭的实例从初始化起就不创建任何线程与数据库连接。

## 15. 扩展方式

新增一项月度统计（以「塞壬研究装置」为参照）：

1. 在版本化 SQL 和 `module.persistence.snapshots` 增加原生映射及公开字段位序，再在 `cl1_database.py` 的 `_empty_data()` 加默认字段，新增 `add_xxx`/`get_xxx` 方法——读改写必须包在 `_stats_transaction()` 里，并按需提供 `async_` 包装。
2. 在 `opsi_runtime.py` 加运行期入口（或在对应任务里直接调用），任务代码只上报领域事件。
3. 在 `module/api/statistics_service.py` 的对应 category 里把指标加进 `report()` 输出；API 模型变更后运行 `uv run python -m dev_tools.export_api_schema`。
4. 需要进日报时，在 `DailySummaryService.build_facts()` 的 facts 里补字段并在 prompt 术语表加映射。

新增掉落识别模板：把结算截图交给 `DropStatistics.extract_template()` 提取，人工重命名后放回对应场景的模板目录；图纸、实验计划和突破部件的稀有度由 `AutoSearchItemGrid.match_candidates` 按底色限定，新等级需要同时补 `TIER_BY_COLOR` 可识别的底色。新增物品同时检查 `opsi_drop_stats.py`、名称表、静态图标及五种语言的 `stats.lootHint`；回归入口为 `tests.test_opsi_drop_stats`、`tests.test_opsi_item_recognition` 和前端「大世界掉落展示新增」模拟服务测试。

## 16. 修改注意事项

- **不要在任务代码里直接写 `cl1_db`**。大世界事件的落库口径（侵蚀等级折算、轮次闭合、来源判定）集中在 `opsi_runtime.py`，绕过它会产生口径分裂的统计。
- **正常代码升级不得清空统计**：新增保护字段、变更身份或格式必须先实现兼容迁移；未完成迁移或普通故障绝不能删除数据；普通总库迁移不删除旧源、描述文件或旧密钥。
- **`ItemGrid` 是被多处共享的单例状态**（`get_items.ITEM_GROUP` 是模块级实例）：`GetItemsStatistics`、`CampaignBonusStatistics`、`azur_stats.GetItems`、商店与仓库都改它的 `grids/item_class/similarity`。新增使用方时必须在使用前完整设置这些属性，如同 `_stats_get_items_load` 所做的那样，否则会带着上一场景的网格布局去匹配。数量侧同理：`amount_area` / `amount_area_rules` / `amount_ocr` / `amount_max` 都是按场景设置的，`azur_stats.GetItems` 会把前三个一起设好。
- **删除是不可逆的**：`drop_cleanup` 只处理文件名匹配 `^\d{13}(_.+)?\.png$` 的文件，配置异常时按 0 处理（不清理）；`bak/` 内的备份不参与扫描（拷贝备份保留原修改时间，只看时间会被反复处理），压缩或拷贝失败时保留原文件。改清理逻辑时保持这些保守默认。
- **日报的 `period_key` 含服务器与时区信息**，改动 `get_daily_summary_window` 的窗口语义会让已存在库里的 period_key 失配，导致重复推送。
- **数量识别先用真实切片回归**：`amount_digits` 的字形阈值、粘连拆分与 `remove_small_fragments` 的 OCR 兜底均需覆盖原生数字；不要把 OCR 旧输出作为真值，也不要凭删首位或末位修正超限值。回归包含重复数字、五位凭证、纸角和粗体图纸数字。
- **遥测提交只发聚合指标**（battle_count/明石次数 + MD5 前缀 instance_id），不要往 `calculate_metrics` 里加可识别个人的字段。
- `module/statistics/assets.py` 与 `module/azur_stats/assets.py` 是 `dev_tools.button_extract` 的生成物，改按钮资源后重新生成，不要手改。
- **科研的期数只能看队列页卡片的罗马数字角标**（`research_drop._read_series`，复用 `module/research/series.py` 的模板）。项目代号在每一期都存在、判不了期；掉落物也判不了——只有彩装备与舰船图纸绑期数，金装备各期混着出，项目还会「额外赠送」别期的图纸。
- **科研的列剖面只用于图纸的 OCR 兜底**：先匹配完整数量字形，图纸纸角粘连且完整匹配不确定时可核对最右单字；末位为 0 不返回单字数量，保留真实的 10。神经 OCR 兜底仅在上限 ≤10 时取最右数字簇，读空时提高阈值重读，仍超限则跳过本格。物资、心智单元不能按图纸切列，避免三位数丢失首位。
- **心智单元不属于任何一期**：它有自己的「心智/物资」视图，也不计入每期的总收益。两个视图**共用同一套版式**（收益卡片 + 收获明细 + 掉落记录，只是心智/物资不分期）。**金装备已不再统计**（2026-09-24 撤掉原「金装统计」视图：它各期混着出、不绑期数，图标又与彩装备相近，容易被认成彩装）。`research_stats.should_show()` 按 `scope` 分这两套口径。
- 科研模板的新增/重命名走 `dev_tools/research_template_extract.py`（从游戏 Lua 数据推导仓库命名，含底色变体与 `{namecode:XXX}` 占位符处理），不要手裁素材。
- **模板改名只改了模板，改不动库里已写入的记录**：记录里存的是模板文件名，显示时才按名称表翻译，所以旧记录会张冠李戴（实测把「四联装610mm鱼雷」显示成八期彩装、把九期彩装 Ta 152C 显示成四期天雷）。名字级的历史映射救不了——一个旧名可能同时盖住两件不同装备——只能用原截图重放：`dev_tools/research_drop_repair.py`（只覆盖 `items`，不动期数与项目代号，动库前先备份）。

## 17. 已知限制

- `AzurStats` 的远程上传路径已废弃；大世界 `upload` 表示本地解析、不保存截图，侵蚀1练级除外。
- `AzurStats.get_meow_loot_monthly_totals` / `get_meow_loot_available_months` 目前在仓库内没有调用方，属于预留接口。
- 委托收益条目没有「已检查但零结算」的心跳记录，日报侧只能把空列表标为 `available=False` 而非零收益（`commission_income_stats` 有注释说明）。
- 遥测域名 `ApiClient.PRIMARY_DOMAIN` 与 `FALLBACK_DOMAIN` 当前相同，故障转移实际未生效。
- farming 汇总表（`farming_aggregates`）使用 SQL 全量重算而非增量，明细库很大时刷新会变慢。
- `drop_statistics.py` 离线分析依赖手动重命名模板与改脚本常量，没有命令行参数化。
- 科研模板库还缺 1~5 期几艘船的图纸（一期路易九世、三期柴郡、四期奥古斯特·冯·帕塞瓦尔与马可波罗、五期鲁普雷希特）：没有模板的掉落会在解析阶段被跳过，所以按期视图里看不到这几艘。

## 18. 示例

最小掉落记录路径（任务代码侧的全部参与方式）：

```python
# ModuleBase 子类里，用配置开关包住一次自动搜索
# 记录方式按当前任务取（opsi_drop_record），智能调度等代理执行时读到的是子任务的开关
with self.stat.new(
    genre=inflection.underscore(self.config.task.command),
    method=opsi_drop_record(self.config),
) as drop:
    combat = self.os_auto_search_run(drop)   # 结算画面出现时 drop.handle_add(main=self)
    drop.set_combat_count(combat)
```

写入一条月度统计（运行期入口模式）：

```python
# 任务代码只声明事件
record_siren_research_device(self)          # opsi_runtime 内部决定来源与等级并异步落库
```

## 19. 调试方法

- 日志前缀：`[统计-物品]`（识别修正）、`[统计-资源]`、`[统计-经验]`、`[统计-大世界]`（运行期事件）、`[统计-解密]`（显式旧解码工具）、`[日报]`（日报全链路）、`[掉落记录]`（清理）、`[基础-API]`（遥测提交）。`logger.attr('CL1单轮耗时', ...)` 等属性行适合 grep 单轮耗时。
- 本地调试服务：`ALAS_DEBUG_SERVER=1` 启动调度器后，`module/debug/commission_debug.py` 可以不开游戏注入伪造委托收益并触发推送，验证统计口径与推送链路。
- 测试：`tests/test_statistics_amount_digits.py` / `test_item_amount_area.py`（真实数量切片、严格上限、裁剪边界与单格失败保留其余物品）、`tests/test_statistics_transactions.py`（CL1 事务与并发）、`tests/test_daily_summary*.py`（日报窗口与聚合）、`tests/test_drop_cleanup.py`（清理与 `AzurStats.new` 节流）、`tests/test_archive.py`（删除/拷贝/压缩三种过期处理方式）、`tests/test_commission_settlement.py`、`tests/test_research_stats.py` / `test_research_drop.py` / `test_research_drop_repair.py`（科研口径、角标识别与记录订正）。
- 数据核查入口：使用 `uv run python -m dev_tools.business_storage --config-dir ./config check` 检查总库；farming 汇总查询 `farming_aggregates`。科研记录里出现「当前 `assets/stats/research_items/` 与名称表都没有的模板名」基本就是模板改名残留，用 `dev_tools/research_drop_repair.py` 拿原截图重放订正。
- 未识别物品：检查 `screenshots/unknown_items/` 下的红框标注图，补模板后重跑 `DropStatistics.extract_template`。

## 20. 相关模块

- [调度器（alas.py）](../entry/alas.md)——日报调度线程、任务运行打点的宿主
- [API 服务](../webui/api.md)——`statistics_service` 的 6 类报表与 `statistics.refreshLoot`
- [通知、LLM 与日志](notify-llm-logger.md)——`handle_notify` 推送通道与 LLM 配置复用
- [战斗系统](../combat.md)——`combat()` 是掉落截图最主要的产生方
- [大世界核心](../os/index.md)——CL1/耄耋相接任务与 `opsi_runtime` 事件的来源
- [委托系统](../game/commission.md)——委托收益识别、截图落盘与钻石委托结算的调用方
- [异步执行器与工具](../base/decorator-utils.md)——`async_executor` 的行为
