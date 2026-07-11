# OCR 使用统计

本文档统计仓库中业务代码对 `module.ocr` 的使用位置、使用的模型以及用途。统计时间：2026-07-05。

## 统计口径

- 扫描对象：仓库内 Python 源码。
- 纳入范围：直接构造 `Ocr`、`Digit`、`DigitCounter`、`Duration`、`AlOcr`，以及继承这些类的业务 OCR 子类；同时统计已有 OCR 对象的 `.ocr()` 和 `.det()` 调用。
- 排除范围：`module/ocr/` OCR 框架自身、`module/base/resource.py` 模型释放逻辑、`module/webui/` OCR 服务启停、`module/device/` 设备重连后重置 OCR、`module/config/` 后端能力探测。
- 注意：`assets/**/OCR_*.png` 是识别区域资源，不是 OCR 调用点。

业务侧静态扫描结果：

- 相关业务/工具/测试文件：86 个。
- OCR 构造或 OCR 子类构造调用：230 处。
- `.ocr()` 或 `atomic_ocr*()` 识别调用：184 处。
- `.det()` 文本检测调用：2 处。

## 模型映射

业务代码里的 `lang` 参数并不总是等于底层文件名，实际映射如下：

| 业务写法 | 实际 `AlOcr` 模型 | ONNX 识别模型 | 字典 | 主要用途 |
|---|---|---|---|---|
| 默认不写 `lang` / `lang='azur_lane'` | `azur_lane`；日服运行时自动改成 `azur_lane_jp` | `bin/ocr_models/azur_lane/ap_azurlane-v6.5_small_rec_nvidia.onnx`；日服为 `bin/ocr_models/azur_lane_jp/ap_azurlane_jp-v6_small_rec_nvidia.onnx` | `ppocrv6_azurlane_dict.txt`；日服为 `ppocrv6_azurlane_jp_dict.txt` | 数字、计数器、时长、关卡名、少量英文/符号 |
| `lang='cnocr'` | `cn` | `bin/ocr_models/zh-CN/ap_zh-cn-v6.1_small_rec_dcu.onnx` | `ppocrv6_cn_dict.txt` | 中文文本、中文 UI 中非标准字体数字 |
| `lang='ppocr_v6'` | `ppocr_v6` | `bin/ocr_models/ppocr-v6/PP-OCRv6_small_rec.onnx` | `ppocrv6_dict.txt` | 国际服/通用文本 |
| `lang='jp'` | `jp` | `bin/ocr_models/ppocr-v6/PP-OCRv6_small_rec.onnx` | `ppocrv6_dict.txt` | 日服文本 |
| `lang='tw'` | `tw` | `bin/ocr_models/ppocr-v6/PP-OCRv6_small_rec.onnx` | `ppocrv6_dict.txt` | 台服文本 |
| `AlOcr(name='cn' if server.server == 'cn' else 'ppocr_v6')` | 国服 `cn`，其他服 `ppocr_v6` | 同上 | 同上 | 岛屿系统文本检测和整图候选定位 |

后端说明：

- 默认后端是 RapidOCR + ONNX Runtime。
- 当配置 `ocr_backend == 'ncnn'` 时，识别模型改用 `bin/ocr_models/ncnn/*.param/*.bin`；`cnocr` 是 `cn` 的别名，`en` 是 `azur_lane` 的别名。
- `.det()` 文本检测使用 `bin/ocr_models/det/PP-OCRv6_tiny_det.onnx`，ONNX 后端会检测 + 识别；ncnn 后端用 RapidOCR 做检测，再用 ncnn 识别模型。
- `Ocr` 默认会先裁剪区域、按字色二值化，再走 `atomic_ocr_for_single_lines()`；`Digit`、`DigitCounter`、`Duration` 在此基础上做数字、`x/y`、`hh:mm:ss` 后处理。

## OCR 子类

仓库中有一批业务子类负责特殊预处理或后处理：

| 子类 | 位置 | 基类 | 用途 |
|---|---|---|---|
| `OcrDataKey` | `module/war_archives/war_archives.py` | `DigitCounter` | 作战档案数据密钥，修正 `1560` 到 `15/60` |
| `ExpOnBookSelect` | `module/tactical/tactical_class.py` | `DigitCounter` | 战术学院技能经验，针对绿色经验条裁剪 |
| `ExpOnSkillSelect` | `module/tactical/tactical_class.py` | `Ocr` | 战术学院技能等级文本 |
| `ShipLevel` | `module/awaken/awaken.py`、`module/os/ship_exp.py` | `Digit` | 舰船等级 |
| `ShipExp` | `module/os/ship_exp.py` | `Ocr` | 舰船经验百分比 |
| `OcrDormFood` | `module/dorm/dorm.py` | `DigitCounter` | 宿舍食物填充量，支持百分比/分数后处理 |
| `PtOcr` | `module/campaign/campaign_status.py` | `Ocr` | 活动 PT，处理 `pt` 后缀、逗号等 |
| `AcademyPtOcr` | `module/coalition/coalition.py` | `Digit` | 学园联动 PT，从 `累计: 840` 中提取数字 |
| `DALPtOcr` | `module/coalition/coalition.py` | `Digit` | DAL 联动 PT，从 `X9100` 中提取数字 |
| `LevelOcr` | `module/combat/level.py` | `Digit` | 战斗/船坞卡片等级 |
| `Level` | `module/exercise/opponent.py` | `Digit` | 演习对手等级 |
| `DatedDuration`、`DatedDurationYuv` | `module/exercise/exercise.py` | `Ocr` | 演习周期剩余时间，支持带日期文本 |
| `ExchangeLimitOcr` | `module/guild/logistics.py` | `Digit` | 大舰队兑换次数上限 |
| `MeowfficerLevelOcr` | `module/meowfficer/enhance.py` | `Digit` | 指挥喵强化等级 |
| `PercentageOcr` | `module/os/fleet.py` | `Ocr` | 大世界据点百分比 |
| `SeaMilesOCR` | `module/os/sea_miles_ocr.py` | `Digit` | 大世界海域坐标/海里数字 |
| `DailyDigitCounter` | `module/os_ash/ash.py` | `DigitCounter` | META 每日收集状态 |
| `MetaDigitCounter` | `module/os_ash/meta.py` | `DigitCounter` | META 点数/计数器 |
| `ActionPointBuyCounter` | `module/os_handler/action_point.py` | `DigitCounter` | 大世界行动力购买次数，修正 `05` 到 `0/5` |
| `PriceOcr` | `module/os_shop/item.py`、`module/shop_event/item.py` | `DigitYuv` / `Digit` | 商店商品价格 |
| `CounterOcr` | `module/os_shop/item.py`、`module/shop_event/item.py` | `Ocr` | 商品库存计数器 |
| `StockCounter` | `module/shop/clerk.py` | `DigitCounter` | 购买弹窗库存数量 |
| `ShopPriceOcr` | `module/shop/shop_medal.py` | `DigitYuv` | 勋章商店价格 |
| `AmountOcr` | `module/statistics/item.py` | `Digit` | 掉落物数量，带最大值校验 |
| `AutoSearchAmount` | `module/azur_stats/image/auto_search_reward.py` | `AmountOcr` | 自动搜索奖励数量 |
| `EmotionDigit` | `module/retire/scanner.py` | `Digit` | 船坞心情数字 |
| `RaidCounter`、`RaidCounterPostMixin`、`HuanChangCounter`、`HuanChangPtOcr` | `module/raid/raid.py` | `DigitCounter` / `Digit` | 突袭活动剩余次数和 PT，针对活动 UI 修正 |

## 按模块用途清单

### 战役、活动、突袭

| 位置 | 模型 | 用途 |
|---|---|---|
| `module/campaign/campaign_status.py` | 默认 `azur_lane`；日服自动 `azur_lane_jp` | 识别战役界面的活动 PT、燃油、金币、魔方、宝石等资源数字；`campaign/run.py` 复用困难次数 OCR |
| `module/campaign/campaign_ocr.py` | 默认 `azur_lane` | 识别关卡名/章节名，字符集限制为数字、大写字母和 `-` |
| `module/war_archives/war_archives.py` | 默认 `azur_lane` | 识别作战档案数据密钥 `当前/总数`，判断是否延迟任务 |
| `module/hard/hard.py` | 默认 `azur_lane` | 识别困难模式剩余次数 |
| `module/daily/daily.py` | 默认 `azur_lane` | 识别每日挑战剩余次数和舰队编号 |
| `module/raid/raid.py`、`module/raid/run.py` | 默认 `azur_lane`，部分活动用 `cnocr` | 识别突袭活动各难度剩余次数、活动 PT、特殊活动计数器 |
| `module/coalition/coalition.py` | 默认 `azur_lane`；`coalition_20250626` 用 `cnocr` | 识别联动活动 PT，不同活动有不同专用后处理 |
| `module/event/maritime_escort.py` | 默认 `azur_lane` | 识别海上护航活动剩余次数 |
| `module/sos/sos.py` | 默认 `azur_lane` | 识别 SOS 信号数量和 SOS 章节号 |
| `module/minigame/minigame.py`、`module/minigame/new_year_challenge.py` | 默认 `azur_lane` | 识别小游戏代币、挑战消耗、战斗分数 |

### 委托、科研、战术学院

| 位置 | 模型 | 用途 |
|---|---|---|
| `module/commission/project.py` | `ppocr_v6`、`jp`、`tw`、`cnocr`；时长用默认 `azur_lane` | 按服务器识别委托名称、委托持续时间、过期时间 |
| `module/research/project.py` | 默认 `azur_lane` | 识别科研项目简称/编号和日服详情页研究时长 |
| `module/research/research.py` | 默认 `azur_lane` | 识别科研实验室项目剩余时间 |
| `module/research/rqueue.py` | 默认 `azur_lane` | 识别科研队列剩余时间，计算结束时间 |
| `module/tactical/tactical_class.py` | 默认 `azur_lane`；技能等级列表用 `cnocr` | 识别技能书经验、训练剩余时间、船坞等级、技能等级 |

### 宿舍、指挥喵、大舰队、船坞

| 位置 | 模型 | 用途 |
|---|---|---|
| `module/dorm/dorm.py`、`module/dorm/buy_furniture.py` | 默认 `azur_lane` | 识别宿舍槽位、食物数量、食物填充量、家具币和家具价格 |
| `module/meowfficer/buy.py` | 默认 `azur_lane` | 识别指挥喵购买剩余次数、选择数量、喵箱金币 |
| `module/meowfficer/train.py` | 默认 `azur_lane` | 识别指挥喵训练队列、容量、箱子数量 |
| `module/meowfficer/enhance.py` | 默认 `azur_lane` | 识别指挥喵喂养材料数量、强化等级、金币 |
| `module/guild/operations.py` | 默认 `azur_lane` | 识别大舰队作战进度 |
| `module/guild/logistics.py` | 默认 `azur_lane` | 识别大舰队后勤商店兑换限制 |
| `module/retire/dock.py`、`module/retire/enhancement.py`、`module/retire/scanner.py` | 默认 `azur_lane` | 识别船坞选中数量、船坞容量、舰船等级、心情数字，用于退役和强化筛选 |
| `module/awaken/awaken.py` | 默认 `azur_lane` | 识别舰船等级，判断觉醒条件 |

### 商店、仓库、免费福利

| 位置 | 模型 | 用途 |
|---|---|---|
| `module/shop/shop_status.py` | 默认 `azur_lane` | 识别商店货币余额：宝石、金币、勋章、功勋、舰队币、核心、兑换券 |
| `module/shop/clerk.py`、`module/os_shop/shop.py` | 默认 `azur_lane` | 识别购买数量、库存上限、购买弹窗数量 |
| `module/shop/shop_medal.py` | 默认 `azur_lane`；新版勋章商店国服用 `cnocr` | 识别勋章商店商品价格 |
| `module/shop/shop_voucher.py` | 默认 `azur_lane`，YUV 预处理 | 识别兑换券商店价格 |
| `module/shop_event/ui.py`、`module/shop_event/item.py` | 截止时间用 `cnocr`；PT/油/价格/库存默认 `azur_lane` | 识别活动商店截止日期、活动货币、UR PT、燃油、商品价格和库存 |
| `module/os_shop/item.py` | 默认 `azur_lane`，YUV 预处理 | 识别大世界商店商品价格和库存 |
| `module/storage/storage.py`、`module/storage/box_disassemble.py` | 默认 `azur_lane` | 识别仓库拆解数量、箱子使用数量、剩余箱子数量 |
| `module/freebies/data_key.py` | 默认 `azur_lane` | 识别免费数据密钥数量 |
| `module/freebies/supply_pack.py` | 默认 `azur_lane` | 识别补给包燃油数量 |
| `module/private_quarters/status.py` | 默认 `azur_lane` | 识别私人休息室每日互动次数、金币、宝石、商品价格 |

### 大世界、META、统计

| 位置 | 模型 | 用途 |
|---|---|---|
| `module/os/map_operation.py` | CN 用 `cnocr`，EN 用 `ppocr_v6`，JP 用 `jp`，TW 用 `tw` | 识别大世界海域名称 |
| `module/azur_stats/image/opsi_zone.py` | `cnocr` | 统计图片中的大世界地图名识别 |
| `module/os_handler/target.py` | 默认 `azur_lane` | 识别大世界目标海域 ID |
| `module/os_handler/action_point.py` | 行动力数字默认 `azur_lane`；适应性和购买次数用 `cnocr` | 识别行动力余额、补给商店行动力、适应性三项数值、行动力购买次数 |
| `module/os_handler/os_status.py` | 默认 `azur_lane` | 识别大世界商店黄币、紫币 |
| `module/os/tasks/month_boss.py` | 复用 `OCR_OS_ADAPTABILITY` 的 `cnocr` | 读取适应性，判断月度 Boss 条件 |
| `module/os/fleet.py` | 默认 `azur_lane` | 识别据点压制百分比 |
| `module/os/sea_miles_ocr.py`、`module/os/tasks/hazard_leveling.py` | 默认 `azur_lane` | 识别大世界海里/坐标数字 |
| `module/os/ship_exp.py` | 默认 `azur_lane` | 识别舰船等级和经验百分比 |
| `module/os_ash/meta.py` | 默认 `azur_lane` | 识别 META 信标等级、伤害、点数计数器 |
| `module/os_ash/ash.py` | 默认 `azur_lane` | 识别 META 收集状态和每日状态 |
| `module/statistics/item.py` | 掉落数量默认 `azur_lane`；商店价格 CN 用 `cnocr`，其他服默认/YUV | 识别掉落物数量、商品价格，用于掉落/奖励统计 |
| `module/statistics/battle_status.py` | `cnocr` | 识别战斗统计中的敌人名称 |
| `module/statistics/drop_statistics.py` | 不直接 OCR；设置 `AlOcr.CNOCR_CONTEXT` | 给掉落统计 OCR 调试/上下文使用 |
| `module/azur_stats/image/auto_search_reward.py` | 默认 `azur_lane` | 识别自动搜索奖励数量 |

### 岛屿系统

| 位置 | 模型 | 用途 |
|---|---|---|
| `module/island/island.py` | 默认 `azur_lane` | 识别选择产品材料数量文本 |
| `module/island/warehouse.py` | 默认 `azur_lane` | 识别岛屿仓库物品数量 |
| `module/island/island_air_drop.py` | 默认 `azur_lane` | 识别空投奖励计数器 |
| `module/island/island_business.py` | 默认 `azur_lane` | 识别商业区剩余时间 |
| `module/island/island_cargo_preparation.py` | 部分运输时长用 `cnocr`，其他默认 `azur_lane` | 识别运输任务时间和刷新倒计时 |
| `module/island/island_daily_order.py` | 默认 `azur_lane` | 识别每日订单紧急剩余次数和冷却时间 |
| `module/island/island_farm.py`、`module/island/island_fishery.py`、`module/island/island_mine_forest.py`、`module/island/island_manufacture.py`、`module/island/island_rancher.py`、`module/island/island_shop_base.py`、`module/island/island_teahouse.py` | 默认 `azur_lane`；矿林仓库物品名用 `ppocr_v6` | 识别工作岗位数量、生产/采集剩余时间、仓库物品名和数量 |
| `module/island/island_select_character.py` | 默认 `azur_lane` | 识别岛屿角色体力计数器 |
| `module/island/island_pearl_sell.py` | `cnocr` | 识别珍珠售卖计数器、价格和当前数量 |

### 造船、装备、演习、UI 辅助

| 位置 | 模型 | 用途 |
|---|---|---|
| `module/gacha/gacha_reward.py` | 默认 `azur_lane` | 识别建造魔方、快速建造票、提交数量、活动提交数量 |
| `module/equipment/fleet_equipment.py` | 默认 `azur_lane` | 识别舰队装备界面的舰队编号 |
| `module/shipyard/ui.py`、`module/shipyard/ui_globals.py` | 默认 `azur_lane` | 识别船坞金币、蓝图数量、开发/命运总进度 |
| `module/exercise/exercise.py` | 默认 `azur_lane`；周期时间可用 YUV 变体 | 识别演习次数和周期剩余时间 |
| `module/exercise/opponent.py` | 默认 `azur_lane` | 识别演习对手等级和战力 |
| `module/combat/level.py` | 默认 `azur_lane` | 识别战斗/敌人等级 |
| `module/ui/ui.py` | 调用方传入 OCR 对象，通常默认 `azur_lane` | `ui_ensure_index()` 中读取当前页签/数量索引 |

### 开发和基准工具

| 位置 | 模型 | 用途 |
|---|---|---|
| `dev_tools/snapshot_resources.py` | 默认 `azur_lane` | 从截图批量识别燃油、金币、宝石、魔方、活动 PT，辅助生成资源快照 |
| `module/daemon/ocr_benchmark.py` | 动态 `model_name` | 对不同 OCR 模型跑性能/准确性基准 |
| `test/ncnn_ocr_benchmark.py` | ncnn 测试封装 | ncnn OCR 性能测试 |

## 框架内部支撑

| 位置 | 作用 |
|---|---|
| `module/ocr/ocr.py` | 定义 `Ocr`、`OcrYuv`、`Digit`、`DigitCounter`、`Duration` 等统一接口和后处理 |
| `module/ocr/models.py` | 定义 `OCR_MODEL` 懒加载入口，映射 `azur_lane`、`azur_lane_jp`、`ppocr_v6`、`cnocr`、`jp`、`tw` |
| `module/ocr/al_ocr.py` | RapidOCR / ONNX / ncnn 后端、单线程 OCR 队列、文本检测 `.det()` |
| `module/ocr/ncnn_ocr.py` | ncnn 识别模型规格和推理实现 |
| `module/ocr/rpc.py` | OCR RPC 客户端/服务器代理；启用 OCR server 时业务对象仍通过同一 `OCR_MODEL` 属性访问 |
| `module/base/resource.py` | 释放 OCR 模型缓存 |
| `module/webui/app.py` | 启停 OCR server 进程 |
| `module/device/device.py` | 设备重连后重置 OCR 模型缓存 |
| `module/config/config.py` | 探测 ncnn Vulkan GPU 可用性 |

