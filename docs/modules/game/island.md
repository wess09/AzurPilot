# 岛屿系统（module/island）

> 碧蓝航线「离岛」生活玩法的自动化：四大生产区派遣、六类店铺生产、商区经营与每日/每周任务（采集、订单、空投、互动、货运、珍珠交易）。

## 1. 模块概述

离岛是游戏内的常驻生活玩法：玩家在岛上经营农田、果园、苗圃、牧场、渔场、矿山、林场，把产出加工成菜品饮品，再通过岗位派遣、商区经营、货运委托与珍珠交易换取资源。玩法画面是自由视角的 3D 岛屿（长按移动视角），内部大量同构 UI（岗位详情、产品选择、角色选择、购买弹窗）在十几个子玩法间重复出现。

本模块把这些玩法拆成一个厚基类 `Island` 加约 20 个任务类：基类负责所有子玩法共享的「岛屿导航、岗位管理、产品/角色选择、仓库筛选与 OCR、商店补货」原语；每个任务类只描述自己玩法的岗位布局、产品配置和调度规则。店铺类玩法（餐馆、饮品、烧烤、简餐、咖啡、制造业）再共享一层 `IslandShopBase`，统一「库存 → 需求 → 套餐分解 → 排产」的算法。另一个贯穿全局的维度是**季节**：全局配置 `IslandPlan.Season` 决定四季限定物品是否参与补种与生产，由 `island_season.py` 统一管理。

调度上，`alas.py` 尾部的 `island_*` 任务方法惰性导入对应模块；任务之间有一条显式联动链：牧场任务执行完后内联执行渔场任务并合并两者计时器，商区经营开始后会触发对应餐馆类生产任务。

## 2. 模块职责

### 负责

- 岛屿页面导航与地图移动：进入管理/岗位管理/仓库/好友岛页面，岛屿地图目的地跳转（矿山林场、农场、苗圃、集会、港口），长按视角移动（`island_up/down/left/right`）。
- 岗位管理原语：遍历岗位、打开/关闭岗位详情、收取产物、追加派遣、页签切换（生产/经营/采集）。
- 派遣两要素：角色选择（网格识别 + 体力 OCR + 优先级回退）与产品选择（模板匹配 + 滑动搜索 + 材料数量 OCR + 商店即时补货）。
- 仓库能力：种类/来源双维度筛选，网格模板匹配 + 数字 OCR 读库存。
- 各生产玩法（农田/果园/苗圃、牧场+磨坊、渔场、矿山林场）与六类店铺（烧烤、白熊饮品、有鱼餐馆、啾啾简餐、啾咖啡、制造工坊）的自动运营。
- 商区经营（5 家商店的按钮状态机、季节/加成商品替换、分批经营）。
- 每日每周任务：采集派遣、每日订单与紧急委托、空投与好友岛补给、摸猫/速运/外送/每周照相、货物筹备运输、珍珠每周采购售卖。

### 不负责

- 季节数据的提取（`dev_tools/island_extractor.py` 是独立开发工具，运行时不参与）。
- 岛屿商店金币/货币的 Dashboard 上报、常规游戏商店（`module/shop`）。
- 页面跳转图谱本身的维护（`module/ui`，本模块只新增岛屿页面节点）。
- 调度恢复与异常重试策略（`module/runtime`，本模块只通过 `task_delay` 与异常语义对接）。

## 3. 模块位置

```
module/island/                  # 全部逻辑所在的主包
├── island.py                   # Island 基类：导航、岗位、选品、仓库筛选、商店购买
├── island_select_character.py  # SelectCharacter：角色网格识别、体力、滚动查找
├── warehouse.py                # WarehouseOCR：仓库网格模板定位 + 数量 OCR
├── island_shop_base.py         # IslandShopBase：店铺通用排产框架
├── island_season.py            # SeasonConfig：季节常量与全局单例
├── ui.py                       # IslandUI：运输/管理页导航，岛屿弹窗处理
├── assets.py                   # button_extract 生成的公共岛屿按钮
├── island_farm.py / island_rancher.py / island_fishery.py / island_mine_forest.py
├── island_grill.py / island_teahouse.py / island_restaurant.py
├── island_juu_coffee.py / island_juu_eatery.py / island_manufacture.py
├── island_business.py          # 商区经营（最大的单文件，含按钮状态机与批次逻辑）
├── island_daily_gather.py / island_daily_interact.py / island_daily_order.py
├── island_air_drop.py / island_pearl_sell.py / island_cargo_preparation.py
└── island_shop_base.py 所在的生产链各店无独立 run 以外的入口

module/island_farm/ 等 16 个目录  # 薄壳：仅 button_extract 生成的 assets.py

module/island_planner/          # 岛屿生产规划器（工具页任务，移植自 ALAS），只写配置不做生产
├── data.py / utils.py / restaurant_config.py / calculator.py   # ALAS 原样移植的数据表与线性规划
├── settings_map.py             # 规划结果 → AzurPilot 配置（菜品/作物名与物品 ID 对照）
├── scanner.py                  # 岛屿科技树扫描
└── planner.py                  # IslandProductionPlanner 任务入口
```

**薄壳目录设计**（本模块最容易误解的结构）：`dev_tools/button_extract.py` 扫描 `assets/{cn,en,jp,tw}/` 下所有子目录，为每个目录机械生成同名 `module/<目录>/assets.py`。岛屿团队把按钮截图按子玩法拆到了 `assets/cn/island_farm/`、`assets/cn/island_restaurant/` 等 16 个目录（每个玩法几十到上百个 `POST_XXX`/`SELECT_XXX`/`TEMPLATE_XXX` 资源），生成器便机械地产出了 16 个只含 `assets.py` 的「薄壳」目录。这些薄壳**不承载任何逻辑，也没有被 alas.py 导入**——`alas.py` 的 17 个 `island_*` 任务方法全部 `from module.island.island_xxx import Xxx`（主包），薄壳只作为资源文件被主包逻辑 `from module.island_farm.assets import *` 反向引用。其真实价值是**资源隔离**：单一 `island/` 资产目录已超百个文件，按玩法拆分让模板/按钮按玩法成组维护，跨玩法复用（如牧场复用农田的作物模板、渔场复用牧场的按钮）直接 import 对方薄壳即可。`island_fishery.py` 中「重新导入鱼苗商店专用按钮（覆盖 island.assets 中的同名旧定义）」的注释佐证了资源在逐步从 `island/` 迁出到玩法目录，旧同名定义靠后置 import 覆盖。

## 4. 核心入口

| 入口 | 用途 |
| --- | --- |
| `alas.py` 的 `island_farm`/`island_rancher`/`island_fishery`/`island_mine_forest` 等方法 | 调度器按任务名进入各玩法，惰性导入并 `run()` |
| `IslandShopBase.run()` | 六类店铺（含制造业覆盖版）的统一生产主流程 |
| `IslandBusiness.run()` | 商区经营状态机（分批/传统两种模式） |
| `IslandDailyGather/Interact/Order/AirDrop/PearlSell.run()` | 每日每周任务的独立入口 |
| `IslandCargoPreparation.run()` | 货运委托入口（唯一基于 `IslandUI` 而非 `Island` 的主流程） |
| `Island`（基类本身） | 无 `run()`，不作为任务运行；alas 的 `island()` 方法仅为导入基类存在 |
| `tests/test_island_shop_production.py` | 离线验证店铺排产逻辑（假 UI，不连游戏） |

## 5. 核心组件

| 组件 | 基类 | 职责 |
| --- | --- | --- |
| `Island` | `SelectCharacter` | 岛屿全局基类：`goto_management`/`goto_postmanage`/`island_map_goto`、岗位详情状态机（`post_open`/`post_get_and_add`/`confirm_post_add_order`）、`select_product`（滑动选品）、材料 OCR 与商店补货（`ensure_select_product_material`）、`warehouse_filter`、`buy_shop_item` |
| `SelectCharacter` | `UI` | 角色网格（前两行）身份/工作/选中状态识别，`WorkerJuu` 体力无限兜底；角色选择器自行等待筛选界面稳定并完成体力排序，再查找默认位于列表末尾的 `WorkerJuu` |
| `WarehouseOCR` | — | 6x2 仓库网格上按模板定位物品并 OCR 数量（`ocr_item_quantity`） |
| `IslandShopBase` | `Island, WarehouseOCR` | 店铺框架：`Meal1~8` 槽位需求、套餐分解、保留线排产、循环填岗 |
| `IslandUI` | `UI` | 岛屿手机页的运输/管理入口，覆盖 `ui_additional` 处理维护公告与信息弹窗 |
| `SeasonConfig` | — | 读取 `IslandPlan.Season`，提供按模块键查询当季限定物品；进程级单例 |
| `CargoPreparationTransport` | — | 单个货运栏位的解析模型（状态/货物/时长） |

各任务类一览（玩法见第 6 节）：

| 任务类 | 组合的父类 | 玩法 |
| --- | --- | --- |
| `IslandFarm` | Island + WarehouseOCR + LoginHandler | 农田/果园/苗圃补种 |
| `IslandRancher` | 同上 | 磨坊加工 + 牧场养殖，完成后串联渔场 |
| `IslandFishery` | 同上 | 鱼苗购买与养殖，合并牧场计时器 |
| `IslandMineForest` | Island + LoginHandler | 矿山/林场派遣 |
| `IslandGrill/Teahouse/Restaurant/JuuCoffee/JuuEatery` | IslandShopBase | 餐饮店铺生产 |
| `IslandManufacture` | IslandShopBase（重度覆盖） | 工坊四产线 |
| `IslandBusiness` | Island | 商区经营 |
| `IslandDailyGather/Interact/Order/AirDrop/PearlSell` | Island | 每日每周玩法 |
| `IslandCargoPreparation` | IslandUI | 货运委托 |

## 6. 工作流程

### 生产派遣的公共骨架

农田、渔场、矿山林场等生产类任务的流程同构：

1. `ui_ensure(page_island)` 进入岛屿，必要时 `goto_management()` 经手机页/季节页纠偏；
2. 进入仓库，`warehouse_filter` 筛选品类，模板 + OCR 统计各产品库存；
3. 库存与阈值比较生成补种/补产列表（季节限定产品按当季过滤），扣除在产岗位需求；
4. `goto_postmanage()` 进入岗位管理，`post_manage_mode` 切到生产页签（必要时按 `post_manage_swipe_count` 上下滑动定位岗位列表）；
5. 逐岗位 `post_open` 打开详情：完成→收取，工作中→记录产品与 `Duration` OCR 的剩余时间，空闲→进入派遣流程；
6. 派遣走固定顺序：点空岗 → `ISLAND_SELECT_CHARACTER_CHECK` 时按角色筛选器 `select_character`（切换体力排序后查找 `WorkerJuu`；筛选按钮、弹窗和列表刷新由共享选择器超时重试）→ `ISLAND_SELECT_PRODUCT_CHECK` 时 `select_product` 选中产品，`ensure_select_product_material` 发现种子/鱼苗/饲料不足则跳转对应商店页签补买后重来 → `POST_MAX` + `POST_ADD_ORDER` 确认。商店只列出账号已解锁的商品，未解锁的商品不占格子，后续格子整体前移（如国际服未解锁洋葱时，苗圃商店草莓格子上是棉花；未解锁虾、小龙虾、蟹时，鱼苗商店「其他」页签的鱿鱼从第 5 格移到第 2 格），因此 `buy_shop_item` 以商品图标在整页范围内模板搜索（`ISLAND_SHOP_ITEM_SEARCH_OFFSET`，相似度 `ISLAND_SHOP_ITEM_SIMILARITY`=0.93，种子包外观相同只有图案不同，阈值低了会认错），找不到时超时放弃购买而不会点到别的商品；`tests/test_island_seed_shop_search.py` 用国际服苗圃、农田、果园与鱼苗商店截图校验定位。补货目标（如农田 `seed_number`）只是尽力而为：点击购买后购买弹窗 3 秒内不关闭（岛币不足时游戏提示资源不足、把数量重置为 1 并保持弹窗）即视为购买失败，`buy_shop_item` 点弹窗右上角 ✕（固定坐标 `ISLAND_SHOPPING_CLOSE`，无模板）关闭后返回产品选择页；本轮任务内同一材料不再尝试同样多的数量，库存已够页面「当前/需求」中的单次需求就直接派遣，不够时只补差到单次需求，仍失败则跳过该岗位（`plan_select_product_material` 决定）；
7. 全部安排完成后，把所有岗位完成时间与 6 小时兜底值取最小，`config.task_delay(target=...)` 预约下次运行。

### 店铺排产（IslandShopBase）

```mermaid
flowchart TD
    A[run: goto_postmanage] --> B[post_check 逐岗位收取/记录状态]
    B --> C{有空闲岗位?}
    C -- 否 --> Z[task_delay 最早完成时间 + 6h]
    C -- 是 --> D[仓库 OCR + 在制品重建 current_totals]
    D --> E[季节优先排产 get_priority_production]
    E --> F[_compute_base_demands 找首个缺口槽位<br>记录保留线 _reserved_targets]
    F --> G[process_meal_requirements 套餐分解]
    G --> H[schedule_production 填充空闲岗位]
    H --> I{仍有空闲岗位?}
    I -- 是 --> J[特殊餐品 → 回退常驻餐品 away_cook]
    I -- 否 --> Z
    K[排产零产出时:<br>严格模式 check_materials → force_skip] -.-> F
```

排产的核心约束：每个岗位单次最多生产 `POST_PRODUCE_LIMIT`（约 7）个；填岗循环最多 `_MAX_FILL_LOOP`（10）轮；套餐（`meal_compositions`）下单时实时 `deduct_materials` 扣减原料账目；「保留线」记录已处理槽位的最高目标，原料库存低于目标时禁止作为套餐原料，达到目标后允许先消耗并由套餐分解补回。排产多次失败时先切严格模式（真零库存才跳过），仍失败则把缺口产品加入 `force_skip` 本轮不再停留。

### 子玩法速览

| 子模块 | 玩法 | 入口类 | 特殊机制 |
| --- | --- | --- | --- |
| `island_farm.py` | 农田、果园、苗圃播种 | `IslandFarm` | 三区域独立阈值/默认作物，可按作物单独设目标（`farm_targets.py`，按库存/目标比例排序）；未达标作物每类最多占一岗；果园秋季限定（秋月梨/柿子）按 4x1 计种子；牛油果/菠萝可忽略；小天城（Amagi_chan）橡胶优先开关 |
| `island_rancher.py` | 磨坊 + 牧场 | `IslandRancher` | 按岗位固定饲料种类补磨坊加工（小麦→鸡饲料等）；`run()` 末尾内联 `IslandFishery(...).run(ranch_finish_times=...)` 合并计时器 |
| `island_fishery.py` | 渔场养殖 | `IslandFishery` | 鱼苗商店分淡水/海水/其他页签；按每苗产量反推购买数；体力门槛 98；养殖后鱼肉少于 `MinFreshwaterFishMeat`/`MinSaltwaterFishMeat` 时调用 `island_fish_meat.py` 兑换 |
| `island_fish_meat.py` | 鱼肉加工（移植自 ALAS） | `IslandFishMeatExchange`（混入渔场） | 岛屿主页「商店」→ 侧栏第 7 项「鱼肉加工」→ 淡水/海水子页签；鱼卡 OCR 鱼名与库存，按产量从高到低只换到目标数量；侧栏、确认弹窗、获得物品弹窗按颜色识别（EN 通用弹窗资源不匹配），点过「商店」后才点侧栏 |
| `island_mine_forest.py` | 矿山/林场 | `IslandMineForest` | 仓库顺序不固定，自实现「OCR 品名 → 读数字」库存扫描（`ITEM_CN_NAMES` 同时收录中文名与国际服英文名首词）；每岗产 4 个、各产物有最大连续次数；体力门槛 80 |
| `island_grill.py` | 乌鱼烤肉店 | `IslandGrill` | 最薄的店铺：仅声明 8 菜品、2 套餐、2 岗位，全部逻辑走基类 |
| `island_teahouse.py` | 白熊饮品 | `IslandTeahouse` | 季节高优先级饮品走固定坐标（不滑动不比色）；「迎春花茶优先生产」开关；为手动配置的季节饮品补注册防止 KeyError |
| `island_restaurant.py` | 有鱼餐馆 | `IslandRestaurant` | 季节菜品自动切换槽位；覆盖 `select_product` 支持固定坐标季节菜 |
| `island_juu_coffee.py` | 啾咖啡 | `IslandJuuCoffee` | 牛奶为特殊材料，扩展仓库读取与 `deduct_materials`；Friedrich 特殊角色开关 |
| `island_juu_eatery.py` | 啾啾简餐 | `IslandJuuEatery` | 芝士/牛奶特殊材料约束；海鲜饭等无套餐产品 |
| `island_manufacture.py` | 制造工坊 | `IslandManufacture` | 四产线（木工/电子/工业/手工）各按配置启用岗位；完全覆盖 `run()` 与排产规则（数量由材料检查决定）；滑动 2 次；产品连续 3 次找不到（多为科技未解锁）记入本批 `unavailable_products`，工业线铁钉足够时先试刀叉餐具、不可用则继续生产铁钉 |
| `island_business.py` | 商区经营 | `IslandBusiness` | 5 商店 × 蓝/黄/深蓝/灰按钮状态机；分批经营（默认批 1=简餐/餐馆/咖啡，批 2=饮品/烤肉）；季节商品库存 <7 时替换 fallback；加成（30/20/10%）档位替换；开始经营后 `task_delay` 触发对应餐馆生产任务补货 |
| `island_daily_gather.py` | 每日采集 | `IslandDailyGather` | 每日 03:10 / 18:00 两次；三槽位派角色，体力阈值 100，忽略 WorkerJuu；未能点击出发（体力或资金不足时为灰色）时不等待采集完成页面 |
| `island_daily_interact.py` | 摸猫、JUU 速运、商区外送、每周照相 | `IslandDailyInteract` | 以「开发计划」任务图标模板判断任务是否可做；地点交互共用 `delivery_location_flow`；每周照相经任务详情的地图按钮（`WEEKLY_PHOTO_TASK_CHECK` 的 button）前往拍照点，以照相按钮被预览遮住确认拍照生效，再点空白关闭预览；失败 60 分钟重试 |
| `island_daily_order.py` | 每日订单 | `IslandDailyOrder` | 紧急委托周配额 15（OCR 检测 + 周一刷新）；订单驳回按 `RejectFilter`；冷却 OCR 失败回退 8 小时 |
| `island_air_drop.py` | 每日空投 + 好友岛偷补给 | `IslandAirDrop` | 以服务器 0 点为每日边界；5 小时偷取冷却（`LastSteal` 落配置）；拜访次数 OCR 复检；`island_air_drop()` 按画面点补给气泡（最多 2 次）、关闭奖励弹窗，气泡变为「分享剩余补给」即停止，国际服误开的邀请好友窗口点 ✕ 关闭、不邀请 |
| `island_pearl_sell.py` | 珍珠每周采购售卖 | `IslandPearlSell` | 周一 01:00 交易窗口；本岛价不达标时按排行榜拜访好友岛比价（买 1.1 折算）；每日 03:00 可选价格刷新 |
| `island_cargo_preparation.py` | 货运委托 | `IslandCargoPreparation` | 3 栏位状态机（locked/pending/running/finished/refreshing/empty）；牛奶黑名单触发换货；尚未提交任何货物且仍缺货的委托也会更换（更换扣除一次运输次数、已提交货物不退还，因此已提交过的委托保留等待）；更换列表按每行左侧序号定位，只选「库存/需求」全部为蓝色的委托，没有则刷新一次，仍没有就保留原委托；默认 2 小时重跑 |

### 岛屿生产规划器（IslandProductionPlanner）

工具页任务，思路、数据表与线性规划移植自 ALAS（LmeSzinc/AzurLaneAutoScript，GPL-3.0）的 Island Production Planner，仅作为「计算器」把方案写入 AzurPilot 已有配置，生产仍由上表各任务执行。

1. **科技状态**：读取 `IslandProductionPlanner.Storage.Storage.IslandTechnologyStatus`；没有保存或勾选 `RescanTechnology` 时进入 `page_island_technology`（岛屿主页右上 `ISLAND_GOTO_ISLAND_TECHNOLOGY`，`BACK_ARROW_WHITE` 返回）扫描，扫描后自动取消勾选。扫描与语言无关：用 `assets/island/technology/technology_chart_{2..6}.png` 连线轮廓模板匹配当前视野，按 `data.py` 节点坐标读亮度（>160 即解锁）；左侧 2~6 号标签按颜色识别，1 号标签无生产科技不扫描。点击带 2 秒间隔，每个标签最多滑动 15 次。
2. **季节任务与额外目标**：`ScanSeasonTasks` 开启时进入 `page_island_season`（岛屿主页右上 `ISLAND_GOTO_ISLAND_SEASON`）底部第 3 个「任务」标签，先 `ISLAND_SEASON_TASK_RECEIVE_ALL` 一键领取已完成任务的奖励（否则已完成任务会被当成目标），再按 `TEMPLATE_ISLAND_SEASON_REWARD` 定位任务卡、OCR 任务名（EN 用 cnocr 并按任务表还原空格，编辑距离纠正到当前季节任务），遇到 `TEMPLATE_ISLAND_SEASON_TASK_OBTAINED` 或滚到底停止（最多翻 20 页），把以物品为目标的未完成任务汇总写入 `SeasonTaskTargets`（预览模式也写）。第一页就识别不到任务卡片（页面未就绪等）时不更新目标、沿用上次保存的值；翻页后内容不变即停止；编辑距离超过 max(3, 任务名长度/2) 的 OCR 结果不予识别（避免把读错的「F」纠正成某个任务）。`ExtraTargets` 为手动追加目标（YAML，值为数量或 `{count, period}`）。两者合并为需求：期限默认本季剩余天数，按 ALAS 方式换算成每日速率并作为约束；当前科技无法生产的物品记录警告后忽略。同名物品（两个 Corn）优先取可生产的。ALAS 的「卡住的季节订单」由其订单任务记录，AzurPilot 不处理季节订单，改由 `ExtraTargets` 手动表达。
3. **求解**：`ProductionPlanCalculator` 以「每日净增物品的季节 PT」为目标，约束包括物品平衡、各生产分组工时（解锁岗位数 × 24 小时 × 效率）、餐厅货架（等级决定货架数 2/2/3/4、容量 5/6 + 服务员加成）、每日岛币净收入 ≥ `DailyProfitLowerLimit`。SciPy 自带 `scipy.optimize.milp`，不需要 ALAS 的兼容层。效率加成来自岛屿角色收集奖励，配置以整数百分比保存（0/4/12，由 `efficiency_rate` 换算）：WebUI 用「.」分隔翻译键，ALAS 的 0.04/0.12 小数选项在 AzurPilot 中无法选择。求解前 `restrict_calculator` 排除 AzurPilot 后厨选项里没有的配方、商区选项里没有的出售菜品，以及农田配置里没有的作物；季节活动按服务器时间从 `data.py` 读取。
4. **餐厅营业与服务员**：分批经营开启时只有 `Batch1Shops`/`Batch2Shops` 中的店参与出售；`IslandBusinessShopN.Char1/2` 中对本店有加成的角色（肇和、柴郡、海伦娜、欧根亲王、奥古斯特、贝尔法斯特、长风）计入加成，其余角色及 None（工作啾代班）只占位。店铺等级由本任务的 `*Grade` 手动填写。
5. **写回**（`settings_map.py`，`ApplySettings` 关闭时只在日志预览，标 `*` 的为会改变的项）：
   - 下列「一天用量/消耗」均含目标物品的每日速率（`daily_need`），目标物品在计划中是累积而非消耗，不计入会导致不为其开工。
   - 后厨 `Meal1~8/MealNumber1~8`：先列出售菜品（按日销量降序，目标 = 货架容量 + 一天用量），再列原料/中间品（按日消耗降序，目标 = 一天用量）；超过 8 个时丢弃末尾并告警。
   - `*NextTask.AwayCook`：该后厨闲时累积量最大的产品，没有则 None。
   - 商区 `Product1~5`：计划出售的菜品，按日销量降序。
   - `CropTargets`：三个区域所有作物都写明目标（一天计划消耗，未使用为 0），因此规划后 `MinFarm` 等区域阈值不再生效。只为攒 PT 的闲时作物不计入目标（补种按库存/目标比例排序，计入会挤占真正需要的作物），只在日志中提示，由默认作物岗位数（`PlantPotatoes` 等）安排。
   - 矿山/林场/渔场 `IslandMine/IslandForest/IslandFishery.Min*`：一天计划消耗量，不用的为 0；求解前排除 AzurPilot 不生产的煤炭、自然之木和未配置的鱼种。闲时累积同作物只作提示（由 `MineSilver`/`CutElegant`/`PlantYellowfinTuna` 安排）。
   - 牧场 `IslandRancher.MinChicken`（禽肉）/`MinPork`（鲜肉）取计划日产量（按牧场科技等级放大，禽肉为副产物，每 3 批摊一次；用到时至少为 1），`Milk`/`Wool` 按计划是否养牛/羊开关。
   - 制造业 `WoodProcessing/ElectronicProcessing/Industrial/Handmade.Positions`：计划工作量需要的岗位数（不超过已解锁岗位与 2）。AzurPilot 各产线产品写死（文件柜、净水滤芯、铁钉/刀叉餐具、皮革/鞋靴/季节手工品），求解前排除其余制造配方。
6. 无可行方案时不改配置，日志给出瓶颈（通常是岛币下限过高）。

## 7. 调用关系

### 上游

| 模块 | 关系 |
| --- | --- |
| `alas.py` | 17 个 `island_*` 任务方法的唯一调度入口，惰性导入各任务类 |
| `IslandRancher.run()` | 运行结束后直接实例化 `IslandFishery` 并传入牧场计时器 |
| `IslandBusiness` | 通过 `config.task_delay(task=...)` 调度 `IslandRestaurant` 等生产任务（SHOP_REFILL_TASK_MAP） |

### 下游

| 模块 | 用途 |
| --- | --- |
| `module/ui` | `page_island*` 页面图谱、`Navbar`/`Scroll`/`ui_goto`/`ui_ensure` |
| `module/handler` | `InfoHandler.loop()` 状态循环、`LoginHandler` 掉线重连 |
| `module/ocr` | `Digit`/`DigitCounter`（体力、库存、次数）与 `Duration`（剩余时间） |
| `module/base` | `Button`/`Template`/`ButtonGrid`、`Timer`、`match_template_color` |
| `module/device` | `island_swipe_hold`（长按视角移动）、`swipe_vector`、点击记录 |
| `module/config` | 参数读写、`task_delay`、`cross_get('IslandPlan.IslandPlan.Season')` |
| `module/exception` | `GameStuckError` 上抛、`GameBugError` 请求重启客户端 |

## 8. 数据流

```
游戏截图
  → 模板/颜色匹配（岗位、菜品图标、季节图标、按钮颜色态）
  → OCR（材料数量 150/2、体力 26/110、剩余时长、订单冷却）
  → 决策（库存阈值比对、需求缺口计算、角色优先级）
  → 操作（点击/滑动/长按视角移动）
  → 产出落配置：任务计时（task_delay）、状态字段（LastSteal、RejectCount、BuyNextRun）
```

排产相关的核心内存结构是 `IslandShopBase` 的三本账：`warehouse_counts`（仓库实际库存）、`post_check_meal`（在制品，来自岗位 OCR）、`current_totals`（两者加本轮已下单未收获量）。套餐下单即扣原料，`produced_pass` 跨排产轮次累计，保证同一轮内被套餐消耗的原料不会在下一轮被重复计入。

## 9. 状态模型

岗位是本系统最核心的状态载体，两个层级的循环都围绕它展开：

```mermaid
stateDiagram-v2
    [*] --> idle: ISLAND_POST_SELECT / WORK_COMPLETE
    [*] --> working: ISLAND_WORKING（记录产品+数量+完成时间）
    idle --> working: post_produce / post_plant 派遣成功
    working --> idle: 收取产物
```

| 状态 | 识别依据 | 处理 |
| --- | --- | --- |
| idle | `ISLAND_POST_SELECT` 或 `ISLAND_WORK_COMPLETE` | 进入补种/补产队列 |
| working | `ISLAND_WORKING` + `ISLAND_WORKING_TIME` | OCR 记产品与完成时间，从需求列表剔除 |
| locked | `TEMPLATE_POST_LOCK`（岗位未解锁） | 跳过 |

货运栏位（`IslandCargoPreparation`）另有六态：`locked/pending/running/finished/refreshing/empty`，由模板颜色逐栏判定，驱动领取、换货、装载三种动作。

## 10. 配置

配置路径 `<Task>.<Group>.<Argument>`，代码经 `self.config.Group_Argument` 访问；以下为关键项（完整定义见 `module/config/argument/`）：

| 配置 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `IslandPlan.Season` | select | spring | 全局季节，驱动所有限定物品过滤（选项仅四季，冬季限定为空表） |
| `IslandFarm.Positions` / `MinFarm` / `PlantPotatoes` / `WorkerFilter` | 数值/文本 | 3 / 660 / 4 / WorkerJuu | 农田岗位数、补种阈值、默认作物岗位数、工人优先级 |
| `IslandFarm.CropTargets` / `IslandOrchard.CropTargets` / `IslandNursery.CropTargets` | 多行文本 | 空 | 按作物的补种目标，每行 `作物: 目标库存`（作物名为 `INVENTORY_CONFIG` 英文名）；未列出的作物用区域阈值，0 表示不补种；岛屿生产规划器会改写 |
| `IslandProductionPlanner.ApplySettings` / `RescanTechnology` / `DailyProfitLowerLimit` / `DailyBufferSafetyMargin` / `*Efficiency` / `*Grade` | checkbox/数值/select | false / true / 50000 / 0 / 0 / bronze | 规划器写入开关、重新扫描科技、每日岛币下限、日缓冲余量、农田/果园/苗圃效率加成、五家店铺等级 |
| `IslandOrchard.AmagiChanRubber` | checkbox | false | 小天城优先种橡胶 |
| `IslandRancher.MinChicken` / `MinPork` | 数值 | — | 畜牧产品阈值 |
| `IslandFishery.PlantYellowfinTuna` / `Min*` | 数值 | — | 默认金枪鱼岗位数与各鱼种阈值 |
| `IslandTeahouse.Seasonal` | checkbox | false | 迎春花茶/季节饮品优先生产开关（与全局季节叠加） |
| `IslandJuuCoffee.Friedrich` | checkbox | false | 特殊角色（腓特烈）派遣开关 |
| `IslandBusiness.BatchEnabled` / `Batch1Shops` / `Batch2Shops` | checkbox/multiselect | true / [3,1,5] / [2,4] | 分批经营与批次划分 |
| `IslandBusinessShop1~5.Product1~5` / `Char1~2` / `SeasonalFallback` / `BoostReplaceFilter` | select/文本 | — | 每商店餐品、角色、季节备选与加成档位 |
| `IslandAirDrop.VisitOtherIsland` / `LastSteal` | checkbox/datetime | true / 2020-01-01 | 好友岛偷补给开关与冷却锚点（运行时写回） |
| `IslandDailyOrder.RejectFilter` / `RejectCount` | 文本/数值 | "Cheese > Tofu" / 0 | 订单驳回条件与运行时计数 |
| `IslandPearlSell.BuyPrice` / `SellPrice` / `DailyPriceRefresh` | 数值/checkbox | 200 / 1000 / false | 珍珠交易价格阈值与每日刷新开关 |
| `IslandCargoPreparation.Blacklist` | 文件串 | "Milk" | 货物黑名单（当前仅支持 Milk） |
| `IslandPlan.IslandWalk.*` | 多行文本（走位规则） | 见 `module/island/island_walk.py` | 每条路线的走位规则，如 `up 3000, right 800, jump`（对所有控制方式生效）；`<路线>Enable` 勾选后由「全局配置」任务走一遍做校验 |

关联关系：季节是唯一贯穿所有模块的横切配置，由 `SeasonConfig` 在各任务 `__init__` 时读取并缓存；店铺类任务的 `Meal{i}`+`MealNumber{i}` 成对声明 8 个排产槽位；`WorkerFilter`/`ChefFilter` 均为 `>` 分隔的角色优先级串，`WorkerJuu`（工作啾）作为通用回退。

走位规则的入口是岛屿计划的全局配置页（任务名「全局配置」，配置段 `IslandPlan.IslandWalk`）：
`IslandWalk.<路线>` 是规则字符串（`up 3000` 整数按毫秒，`3.0` / `1.5s` 按秒；`jump` 只点一次跳跃；
`switch` 是切换到啾咖啡餐厅，即布莱梅路线中间那一步），`IslandWalk.<路线>Enable` 是该校验开关。
`module/island/island_walk.py` 集中维护 17 条路线的默认规则（磨坊路线与地图跳转强绑定、长度也短，保持写死在 `goto_mill()`），`island_walk_steps()` 对所有控制方式
都读配置，规则为空或非法时回退默认值，时长越界夹到 0.1~20 秒（桥接 swipe 的位移随负载漂移，
按机器各配一套规则最稳）。

两条例外路线因为中间夹着别的操作，不能整条用规则表达：`AirDropRetry`（补滑）在每步之后都要检测
补给是否到手，方向固定为上 → 右 → 下，配置只按位置取 3 个时长，个数不符时回退默认值；
`DailyBulaimei` 的中间动作已抽成规则里的 `switch` 一步，所以它和其它路线一样可整条配置。

「全局配置」任务本身是可运行的：勾选若干 `<路线>Enable` 后运行它，会在岛屿场景里把每条勾选的路线
各走一遍（供人工核对落点），跑完把任务推迟到第二天；一条都没勾选时同样直接推迟到第二天，
避免同一天反复执行。

## 11. 异常与错误处理

| 异常 | 原因 | 处理 |
| --- | --- | --- |
| `GameStuckError` | 导航（进入管理/地图/页签）、`post_open` 反复重试、仓库筛选超时 | 直接上抛，交给调度器按卡死流程恢复 |
| `GameBugError` | 每轮结束检测到 `ERROR1` 弹窗（置 `island_error` 标志）、拜访卡死 | 各任务 `run()` 尾部统一抛出，调度器重启游戏客户端后重试 |
| `GameTooManyClickError`（预防） | 同一按钮高频点击触发保护 | 代码主动规避：`select_product` 前清理 `click_record`、滑动后点安全区域且 `control_check=False`、地图确认按钮只在前 10 秒内补点 |
| 阶段级失败（返回 False/0） | 拜访超时、角色无可用、材料不足（含岛币不足导致补货失败）、按钮状态未知 | 记录警告后跳过该岗位/地点，不打断整轮任务；`IslandDailyInteract` 失败时延时 60 分钟重试 |

店铺选品连续 `PRODUCT_SELECT_RETRY_LIMIT`（3）次在产品列表中找不到商品时（多为岛屿科技尚未解锁），不再抛 `GameStuckError` 重启游戏，而是返回岗位管理页、`post_produce` 返回 0，调用方把该商品记入 `chef_unavailable_products` 本轮跳过；只有无法返回岗位管理页时才按卡死处理。

`post_open` 识别到的岗位按钮下沿超出列表可见区域（`POST_LIST_VISIBLE_BOTTOM`=640，滑动框下沿约 656）时，点击会落在列表外或画面外（y>720）而打不开岗位，最终 `GameTooManyClickError`（啾咖啡岗位 1 滑动后常停在 y≈680~720）。现在先 `post_manage_up_swipe` 上推列表（最多 `POST_EDGE_NUDGE_LIMIT` 次）再点击。

错误处理的设计取向是「局部失败不拖垮全局」：单个岗位无角色、单个菜品原料不足、单个好友不可访问都只影响自身，循环继续处理其余岗位；只有 UI 导航层面无法回到已知状态才升级为异常。`GameBugError` 与 `GameStuckError` 的分工来自 `module/exception.py`：前者明确表示客户端 bug（重启可恢复），后者表示操作卡死。

## 13. 缓存与持久化

- 持久化全部经由配置系统：`IslandAirDrop_LastSteal`（空投冷却）、`IslandDailyOrder_RejectCount`/`UrgentDetectRefreshTime`、`IslandPearlSell_BuyNextRun`/`NextPearlTradeTime` 等字段在任务运行中写入并随 `config.save()` 持久化，作为下次调度的锚点。
- `island_season.py` 维护进程级单例 `_global_season_config`：首个任务创建后，后续任务传入新 config 时仅刷新季节值。同一调度进程内多次任务共享一个实例。
- 内存账目（`warehouse_counts`、`post_check_meal`、`_reserved_targets`、`unavailable_characters`）每轮 `run()` 开头清空重建，不跨轮累计，避免上一轮的识别残留污染本轮决策。

## 14. 生命周期

每个调度周期实例化一个任务类 → `__init__` 读取配置并构建产品/岗位表（`initialize_shop`、`name_to_config`）→ `run()` 执行完整玩法循环 → `task_delay` 预约下次运行后实例销毁。没有跨任务复用的重对象；模板图像按需从磁盘读取。唯一常驻的是季节配置单例，随进程存活。

## 15. 扩展方式

新增一个岛屿店铺类玩法的固定步骤：

1. 在 `assets/{cn,...}/island_<name>/` 放置按钮/模板 PNG（岗位按钮、`SELECT_*`/`SELECT_*_CHECK` 选品对、`POST_<产品>` 图标、`TEMPLATE_<产品>` 仓库模板），运行 `uv run -m dev_tools.button_extract` 生成薄壳 `module/island_<name>/assets.py`；
2. 在 `module/island/island_<name>.py` 声明 `IslandShopBase` 子类：`shop_type`（需与 `SEASONAL_ITEMS` 的模块键一致以接入季节）、`shop_items`（模板/选品/仓库模板四件套）、`meal_compositions`（套餐）、`post_buttons`、`filter_asset`（仓库来源筛选）、`setup_config(前缀...)`；
3. 在 `task.yaml` 的 Island 段注册任务与参数组，在 `argument.yaml` 增加对应配置组（`PostNumber`/`ChefFilter`/`Meal*`），运行 `uv run -m module.config.config_updater`；
4. 在 `alas.py` 增加 `def island_<name>()` 方法（惰性导入 + `run()`）；
5. 若有季节限定或特殊材料，参考 `IslandTeahouse`（固定坐标季节菜）或 `IslandJuuCoffee`（`special_materials` + `deduct_materials` 覆盖）补写钩子，并在 `tests/test_island_shop_production.py` 用假 UI 验证排产。

新增非店铺玩法（如新的采集点）则直接继承 `Island`，复用 `island_map_goto` 与 `island_up/down/left/right` 的移动原语编写 `run()`。

## 16. 修改注意事项

- **季节表是手写常量**：`SEASONAL_ITEMS`、`SEASONAL_FOOD_MAP`、`SEASONAL_DRINK_CONFIG` 等随游戏季节更新需要改代码，不在配置生成体系内。新季节上线时需同步季节表、对应模块的固定坐标按钮与 `ISLAND_ITEM_CN_NAMES` 日志映射。
- **按钮资源 area/button 可能交叉**：生产/经营页签按钮（`POST_MANAGE_PRODUCTION/BUSINESS`）的 area 是选中态颜色检测区、button 记录的是对侧页签点击坐标，`post_manage_mode` 靠「点击对侧资源的 button」实现切换。调整这类资源前先核对此约定。
- **选品滑动的点击预算**：`select_product` 的滑动与惯性消除点击共用 `click_record`，改动滑动次数或名称可能触发单按钮 12 次阈值保护；两次调用间靠 `click_record_remove` 防累积。
- **OCR 兜底链是有意设计**：材料 `150/(2+6)`、体力 `26/110` 都存在斜杠被误识别的已知问题，`island.py`/`island_select_character.py` 中多组候选区域、前缀读取、颜色条估算是踩坑后的补偿，勿简化为单区域 OCR。
- **季节单例**：`get_global_season_config` 在进程内缓存，单测中需像 `tests/test_island_shop_production.py` 那样 patch 掉它，否则配置泄漏到其他测试。
- **渔场与牧场共享资产**：`island_fishery.py` 同时导入 `island_fishery` 与 `island_rancher` 的 assets，且后置导入覆盖 `island.assets` 的旧同名定义——调整资源目录时保持导入顺序。
- **补充其他服务器资源时连同覆盖文件一起提供**：不少岛屿资源靠 `.BUTTON.png` 把点击位置指向别处（岗位卡片标题 → 岗位格、页签 → 对侧页签、每周照相任务标题 → 地图按钮）。某服务器只放基础图而缺少对应 `.BUTTON.png` 时，`button_extract` 会把点击位置退化为识别区本身，表现为能识别但点错位置。国际服文案通常更长，裁剪时还需注意代码里写死的搜索区域：`DEVELOPMENT_PLAN_TASK_LIST_AREA` 宽 101 像素，任务名模板不能超过该宽度。
- **岛屿内禁用舰船获取弹窗**：`IslandUI.ui_additional` 固定 `get_ship=False`，岛屿流程的状态循环必须带 `get_ship=False` 的导航调用，否则可能误点宿舍相关弹窗。

## 17. 已知限制

- 所有坐标、路线默认值（`module/island/island_walk.py` 的方向+时长序列）与固定坐标选品均按 1280×720 实测写死，游戏改版需重新校准；`IslandPlan.IslandWalk.<路线>` 可以整条覆盖规则（含方向顺序与时长），对所有控制方式生效。
- `SEASONAL_ITEMS` 中冬季为空、代码保留的 `'none'` 季节分支在当前配置选项下不可达；赛季迭代（新季节物品上线）完全依赖手动维护代码。
- 制造业部分季节物品（夏季茉莉精油、秋季花束）在季节表中保留但有意不配置制作；`filter_element` 复用了 `TEMPLATE_FILE_CABINET` 模板（资源未单独提取），为已知的临时妥协。
- 货物黑名单目前只实现了 Milk 一种识别模板；缺货委托不依赖黑名单，由更换列表的库存颜色判断。更换列表的行定位与颜色阈值基于国际服截图（`tests/fixtures/island_cargo/`），国服若布局不同需另行校准。
- 岛屿生产规划器不能指定制造业产线内的产品比例（铁钉与餐具、皮革与鞋靴由 `island_manufacture.py` 按库存规则切换），只控制岗位数；季节订单需在 `ExtraTargets` 手动填写；每日订单不参与规划。`data.py` 需在游戏更新后从 ALAS 重新复制。
- 各生产玩法每轮固定追加 6 小时兜底延时，依赖 `Duration` OCR 读取剩余时间，极端字体渲染下可能识别失败退化为兜底值。

## 19. 调试方法

- 日志：阶段用 `logger.hr`（如「岛屿-农田」「珍珠购买阶段」），状态用 `[岛屿-xxx]` 前缀行；库存与生产计划均经 `_inv_cn`/`_products_cn` 翻译为中文输出，直接对照配置选项。
- 离线测试：`uv run python -m unittest tests.test_island_shop_production` 用假 UI 驱动六类店铺的真实排产/配方逻辑，改 `island_shop_base.py` 后应先跑它。
- 单玩法冒烟：多数模块文件底部保留 `if __name__ == '__main__'` 块（如 `IslandFarm.test()` 只跑仓库 OCR），可在模拟器在线时定点复现。
- 卡死排查顺序：先看最后一行 `[岛屿-xxx]` 警告（提示哪个超时分支），再查对应按钮资源在当前服务器 `assets/<server>/island*/` 是否存在、坐标是否漂移。
- 走位调参：在「全局配置」页改对应路线的规则（如 `right 4600, up 5100, right 1100`），勾上同名「校验」项，启用并运行一次该任务即可把这条路线走一遍核对落点；日志会打印 `[岛屿走位] <路线>: <规则>` 与每条路线的执行小节。真机/云手机上注意每次 App 重启后虚拟屏 id 会变化，走位依赖的桥接会短暂不可用。

## 20. 相关模块

- [其他游戏功能模块](misc.md) —— 岛屿之外的常驻玩法合集（月历、签到、比绍滑稽剧场等）。
- [UI 导航](../ui.md) —— 岛屿页面在全局图谱中的位置与 `Navbar`/`Scroll` 组件。
- [配置系统](../config.md) —— `<Task>.<Group>.<Argument>` 路径、`task_delay` 与配置热重载。
- [处理器层](../handler.md) —— `InfoHandler.loop()` 状态循环与 `LoginHandler` 掉线恢复。
- [OCR 系统](../ocr.md) —— `Digit`/`DigitCounter`/`Duration` 与字母表白名单机制。
