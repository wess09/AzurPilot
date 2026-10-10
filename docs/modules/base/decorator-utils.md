# 装饰器与工具函数

> `module/base` 的横切原语速查：`Config.when()` 按配置分发同名方法、`cached_property` 缓存属性及其主动失效、`retry` 退避重试，以及随机坐标、颜色比较、图像裁剪等 utils 函数速查表。

## 1. 模块概述

`module/base` 的三个无状态支撑文件：`decorator.py` 提供控制方法行为的装饰器（条件分发、缓存属性、单次执行），`retry.py` 提供带退避的通用重试，`utils.py` 提供被几乎所有模块 `from module.base.utils import *` 消费的图像与坐标工具。它们不持有游戏状态，只做「行为修饰」与「纯函数计算」，是业务模块表达「按服务器/选项切换实现」和「缓存 + 主动失效」两个高频模式的底层支撑。

## 2. 模块职责

### 负责

- `Config.when(**配置条件)`：同名方法按运行时配置值分发到不同实现。
- `cached_property` 及配套 `del_cached_property` / `has_cached_property` / `set_cached_property`：实例级缓存属性与主动失效。
- `run_once`（只执行一次）、`function_drop`（随机丢调用，测试用）。
- `retry` / `retry_call`：tries/delay/backoff/jitter 退避重试（改自 retry 库）。
- `utils.py`：随机点击/滑动坐标、区域与点运算、图像裁剪与色彩空间转换、颜色容差比较、OCR 预处理、进度条百分比、地图网格坐标互转。

### 不负责

- `Timer` 计时器与时间解析——在 `module/base/timer.py`，见 [基础层](index.md)。
- 设备层的重试恢复（`module/device/method/retry.py` 的 `retry_backend`）——独立实现，参数语义不同，勿与本文 `retry` 混淆。
- 资源注册与批量释放（`resource.py`）——但它复用本模块的 `del_cached_property`。
- OCR 推理与模型管理——本层只提供 `extract_letters` 等预处理函数。

## 3. 模块位置

```
module/base/
├── decorator.py   # Config.when、cached_property、del/has/set_cached_property、function_drop、run_once
├── retry.py       # retry、retry_call（从 retry 库复制并修改）
└── utils.py       # 图像处理、随机坐标、颜色比较、OCR 预处理、网格坐标互转
```

| 函数/类 | 一句话用途 | 典型使用者 |
| --- | --- | --- |
| `Config.when` | 同名方法按 `self.config` 当前值分发 | 约 77 处，业务模块服务器/选项差异（截至 2026-09） |
| `cached_property` 系列 | 实例缓存属性读写删 | 资源类（Button/Template）、调度器、设备连接 |
| `run_once` | 状态循环内的一次性动作 | 停止条件检查、日志去重、一次性探测 |
| `retry` | 通用重试 | `module/runtime/updater.py` |
| `random_rectangle_point` 等 | 点击/滑动坐标随机化 | `module/device/control.py` |
| `crop` / `get_color` / `color_similar` | 裁剪与颜色检测 | `ModuleBase.appear()` 及几乎所有识别代码 |
| `color_bar_percentage` | 进度条百分比 | 血量平衡、大世界搜索进度 |
| `extract_letters` / `crop_to_text` | OCR 预处理 | `module/ocr` |

## 4. 核心入口

| 入口 | 用途 |
| --- | --- |
| `@Config.when(KEY=value, ...)` | 为同名方法注册按配置分发的实现 |
| `@cached_property` / `del_cached_property(obj, name)` | 缓存属性计算与主动失效 |
| `@retry(exceptions, tries, delay, ...)` / `retry_call(...)` | 失败自动重试 |
| `random_rectangle_point(area)` | 点击坐标的随机化来源（`Device.click` 内部调用） |
| `crop(image, area)` / `get_color(image, area)` / `color_bar_percentage(...)` | 图像裁剪、颜色采样与进度检测 |

## 6. 使用方式

### Config.when：按配置分发同名方法

装饰时把 `{options, func}` 追加进**类级** `func_list[方法名]`（相同条件重复定义则覆盖，不同条件则追加）；调用时遍历该列表，条件为 `每项 value is None or self.config.<key> == value`，全部满足的**首个**分支生效。

为什么必须为其他情况写 `@Config.when(SERVER=None)` 回退：`None` 在条件求值中恒为真，充当「任意服务器」分支。若某方法只写了 `@Config.when(SERVER='en')` 一个分支，EN 之外的服务器没有任何匹配记录，wrapper 会打 warning（`[装饰器] 没有选项适合 ...`）并**回落执行最后定义的那个函数**——也就是 EN 版实现被错误地跑在 CN/JP/TW 上。因此项目惯例是：专服实现写在前，`SERVER=None` 通用回退写在最后；`commission_parse`、`get_zone_name`、`research_detect` 等四服务器分发均遵循此结构。

要点：

- `self.config` 是唯一数据来源，分发发生在**每次调用的运行时**，配置热重载后下一次调用即切换分支；装饰（注册）只发生在导入期。
- 条件可写多个键（如 `POOR_MAP_DATA=True, MAP_CLEAR_ALL_THIS_TIME=False`），且不限于 `SERVER`，任何 `AzurLaneConfig` 属性都行。
- 常与 `cached_property` 叠用缓存按服务器变化的网格/裁剪区（约 20 处，如 `sos._sos_chapter_crop`），`cached_property` 必须放在外层。

```python
@Config.when(SERVER='en')
def _fleet_sidebar(self): ...   # 仅 EN

@Config.when(SERVER=None)
def _fleet_sidebar(self): ...   # 其余服务器；必须写在最后
```

### cached_property 与主动失效

`cached_property.__get__` 把计算结果写入 `obj.__dict__[原函数名]`，之后同名实例属性直接命中 `__dict__`、描述符不再执行。配套函数操作同一个 `__dict__` 键：`del_cached_property`（删键即重置，KeyError 静默）、`has_cached_property`（判断是否已缓存）、`set_cached_property`（直接预置值）。

缓存一旦写入就固定，因此任何「底层状态已变」的场景都必须主动删键，下次访问才会重建：

| 场景 | 失效调用 | 原因 |
| --- | --- | --- |
| 调度器服务器维护恢复（`alas.loop`） | `del_cached_property(self, 'config')` | 阻塞期间 WebUI 可能已改配置文件，重新构造 `AzurLaneConfig` 才能读到新值 |
| `config.task_call()` 注入任务后 | 同上 | 让调度与内存对象和磁盘配置重新同步 |
| 模拟器重启后 | `del_cached_property(self, 'device')` | 下次访问 `self.device` 重建连接 |
| 长等待被热重载打断（`wait_until` 返回 False） | `del_cached_property(self, 'config')` 后 `continue` | 重入循环前刷新配置 |
| 设备连接断开（minitouch/maatouch/nemu_ipc 恢复逻辑） | `del_cached_property(self, '_minitouch_builder')` 等 | 下次访问缓存属性时重建连接 |
| 任务切换资源释放（`resource_release()`） | 批量删 `cached` 列表 | 下次按当前服务器重新解析/加载图像 |

### retry：退避重试

`@retry(exceptions=Exception, tries=-1, delay=0, max_delay=None, backoff=1, jitter=0, logger=...)`。失败后的等待序列为：先 `sleep(初始 delay)`，此后每轮 `_delay = min(_delay * backoff + jitter, max_delay)`；`backoff` 是固定乘数，`jitter` 可传数值或 `(min, max)` 元组（取随机值），`tries=-1` 表示无限重试。与原版 retry 库的两处差异：重试耗尽时抛**原始异常**（原版抛 `RetryError`），且失败时用 `logger.exception` 输出完整堆栈。`retry_call` 是同一逻辑的函数式调用。当前唯一使用点是 `module/runtime/updater.py` 的 `git_install`（`tries=3, delay=5, logger=None`）。

### utils 场景速查表

| 场景 | 函数 |
| --- | --- |
| 点击点随机化（正态分布取区域内的点） | `random_rectangle_point(area)`（`Device.click` 的坐标来源） |
| 滑动路径随机化（防滑动被游戏当点击） | `random_rectangle_vector_opted(vector, box, whitelist_area, blacklist_area)`、`random_rectangle_vector` |
| 拖拽分段路径 | `random_line_segments(p1, p2, n)` |
| 时间/整数随机化（秒、间隔、持续时间的元组写法） | `ensure_time`、`random_normal_distribution_int`、`ensure_int` |
| 进度条百分比（HP 条、搜索进度等，支持渐变与反向） | `color_bar_percentage(image, area, prev_color, reverse=...)` |
| 区域平均颜色 / 颜色相似判断 | `get_color`、`color_similar`（容差 = 最大正差 − 最大负差，与 Photoshop 一致，threshold 越大越宽松） |
| 逐像素颜色掩码 / 颜色计数 | `color_mask`、`color_similarity_2d`、`color_similar_1d`、`image_color_count` |
| 图像裁剪（越界用黑边填充，模拟 pillow） | `crop(image, area, copy=True)`；坐标超出边界返回对应尺寸全黑图 |
| 粘贴/缩放/通道与尺寸 | `image_paste`、`resize`、`image_channel`、`image_size`、`copy_image`、`rgb2gray`、`rgb2hsv`、`rgb2yuv`、`rgb2luma`、`color_mapping` |
| 加载/保存图像（去 alpha、可先裁剪） | `load_image(file, area=None)`（始终关闭 PIL 对象；4 通道转 3 通道）、`save_image` |
| OCR 预处理（字母黑、背景白） | `extract_letters`、`extract_white_letters`、`crop_to_text`、`image_left_strip`（去除 `DAILY:` 前缀类文本） |
| 内容外接框 | `get_bbox` / `get_bbox_reversed`（全黑图抛 `ImageNotSupported`） |
| 红色叠加透明度（伏击/空袭提示强度） | `red_overlay_transparency(color1, color2)` |
| 地图网格坐标（A1 风格 ↔ 元组，支持负值） | `node2location`、`location2node`、`col2name`、`name2col` |
| 非原生 720p 截图的模板匹配阈值放宽 | `lower_template_match_similarity`（上限钳到 0.75），开关由截图层经 `set_template_match_non_native_720p` 设置 |
| 区域与点的关系运算 | `area_offset`、`area_pad`、`area_limit`、`area_size`、`point_limit`、`point_in_area`、`area_in_area`、`area_cross_area`、`xywh2xyxy`、`xyxy2xywh` |
| 日志格式化 | `float2str`、`point2str`；彩色像素抑制的白色文字提取为 `extract_white_letters` |

## 11. 异常与错误处理

| 异常 | 原因 | 处理 |
| --- | --- | --- |
| `ImageNotSupported` | `get_bbox` / `get_bbox_reversed` 遇到全黑图或不支持的通道数 | 上抛调用方（多发生在资源提取工具中） |
| retry 耗尽 | `tries` 次尝试均失败 | 抛最后一次的原始异常，由上层恢复机制接管 |

## 16. 修改注意事项

- **`Config.when` 的分发记录按方法名全局合并**：`func_list` 是 `Config` 的类属性，与类无关。若两个不同类对同名方法使用不同条件集，调用时会命中「先导入类的满足分支」而非本类的实现；新增同名方法前先确认条件集合一致。
- **`SERVER=None` 回退分支必须写在最后**：匹配按定义顺序，且 fallback 执行的是「最后定义的函数」，顺序错了会静默走错实现（仅 warning）。
- **装饰顺序**：叠用时 `@cached_property` 在上、`@Config.when` 在下；给 `retry` 再叠 `Config.when` 时注意两层都会重试/分发。
- **`run_once` 不缓存返回值**：只有首次调用执行并返回结果，后续调用静默返回 `None`。需要结果必须在首次调用处取（如停止条件检查直接 `raise`）。
- **颜色容差是「容差」语义**：`color_similar` / `color_mask` / `image_color_count` 的 threshold 表示允许的色差（0 为完全相同，越大越宽松），与旧代码里的「相似度 221 等价容差 34」换算注意区分。
- **`color_similarity_2d`、`color_mask`、`extract_letters` 存在小图/大图两条实现路径**（按 `h*w < 30000` 分流），修改颜色计算时必须保持两条路径结果一致。
- **`module/base/retry.py` 与设备层 `retry_backend` 是两套实现**：`module/device/method/*.py` 里的 `@retry(on_exhausted=...)` 经 `partial(retry_backend, ...)` 绑定，参数与语义不同（如 `on_exhausted` 只存在于后者），不要互相套用。
- **`load_image` 无服务器回退**：按服务器回退图像路径发生在资源生成期（`dev_tools/button_extract` 回退用 cn 资源）与 `Resource.parse_property` 的运行期选择，不在本函数内。
- 调试时可用 `@function_drop(rate)` 装饰 `Device.click` 模拟丢点击；`function_drop` 与 `@timer`（在 `timer.py`，print 耗时）都仅供测试。

## 20. 相关模块

- [基础层](index.md) — 本篇所属的 module/base 总览（`ModuleBase`、资源释放如何消费 `del_cached_property`）
- [编码规范](../overview/conventions.md) — `Config.when` 与状态循环等项目惯例的汇总
