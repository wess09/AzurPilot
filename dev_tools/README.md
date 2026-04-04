# dev_tools (开发者工具集)

该目录包含了一系列用于 AzurLaneAutoScript (ALAS) 的开发者工具和脚本，主要用于提取游戏数据、调试核心算法以及处理图像资源。普通用户一般不需要直接运行这些脚本，但它们在开发修改功能、适配新活动或分析收益时非常重要。

## 目录用途说明

### 游戏数据提取与解析 (Lua Extractor)
这些工具通常依赖于碧蓝航线的解包 Lua 文件（如 `AzurLaneLuaScripts` 仓库）。
- **`map_extractor.py`**: 提取活动海域/主线海域的地图网格形貌、敌人刷新规则，并自动生成 ALAS 的海域作战代码 (`campaign_x_x.py`)。
- **`os_extract.py`**: 提取大型作战（大世界、Operation Siren）的海域数据、坐标、多语言名称。
- **`island_extractor.py`**: 提取海岛主题活动（如夏日活动）的物品、配方、产出任务等逻辑数据。
- **`research_extractor.py`**: 提取科研项目的消耗、产出数据，并自动建立简中到英文的翻译映射。
- **`ship_exp_extract.py`**: 提取舰船各等级所需的累计经验值表格数据。
- **`word_template_extractor.py`**: 提取游戏内的聊天屏蔽词库库文件（`word_template.lua`）。

### 自动化执行与收益统计
- **`coin_statistics.py`**: 通过分析打捞记录截图，计算特定海域打捞的总物资收益和“油金比”（考量了舰船退役及装备拆解隐藏收益）。
- **`item_statistics.py`**: 提取战斗掉落页面的战利品数据，自动裁剪并保存新物品的模板图片，协助完善统计功能。
- **`research_optimizer.py`**: 计算并优化不同科研完成度下各项目的刷新概率，用于自动科研系统的收益过滤算法。

### 图像资源与模板工具
- **`button_extract.py`**: 读取 `assets` 目录下的原始图片素材，提取按钮区域和颜色特征，自动生成 `module/xx/assets.py` 中的 UI 元素代码。
- **`relative_record.py` (包含 gif 系列)**: 自动化连续截图辅助工具，通常用来给在海面上浮动的人型塞壬录制动态图，筛选出无背景遮挡的纯净图片作为识别模板。
- **`relative_crop.py`**: 基于已识别出的海域网格进行等比裁剪测试，主要用于截取分析网格内部的特定区域（如敌人类型图标）。

### 底层框架分析与测试
- **`campaign_swipe.py`**: 校准工具。控制模拟器在地图中进行滑动测试，透视网格计算实际滑动距离差，拟合输出不同底层（adb、minitouch、maatouch）的最佳地图滑动乘数。
- **`grids_debug.py`**: 调试工具。能够独立调用 ALAS 的图像透视变换和地图网格提取模块，方便开发者排查“识别不到地图网格格子”或者“格子歪了”等视觉识别报错。
- **`emulator_test.py`**: 压力测试脚本。对比测试 ADB 和 Uiautomator2 各自的截图速度和点击延迟性能。

### 维护工具
- **`war_archives_update.py`**: 每当官方将以往活动加入常驻“作战档案（War Archives）”时，该脚本可一键将 ALAS 旧的活动代码挪并批量修正命名路径。
- **`requirements_updater.py`**: 一键规范化修复 Python 依赖文件 (`requirements.txt`) 的格式，避免环境快速安装时出错。
- **`Flatten_generator.py`**: 快速将直观的网格字符串转换为坐标拼接代码的小工具。
