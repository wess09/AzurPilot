---
description:
alwaysApply: true
---

# 编码规范文档

**生成日期**: 2026-05-27
**项目版本**: dev 分支

---

## 一、语言与交流规范

### 1.1 语言使用

- **交流语言**：简体中文（回复、注释、文档、提交信息）
- **代码语言**：英文（变量名、函数名、类名）
- **注释语言**：简体中文

### 1.2 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 变量名 | snake_case | `skip_first_screenshot` |
| 函数名 | snake_case | `appear_then_click()` |
| 类名 | PascalCase | `ModuleBase`, `AzurLaneConfig` |
| 常量 | UPPER_SNAKE_CASE | `BUTTON_A`, `END_CONDITION` |
| 模块文件 | snake_case | `campaign_base.py` |

### 1.3 特殊命名约定

- `point` = (x,y) 屏幕坐标
- `area` = (x1,y1,x2,y2) 边界框
- `location` = (x,y) 网格坐标
- `node` = "E3" 字符串网格引用

---

## 二、文件组织规范

### 2.1 目录结构

```
module/
├── base/           # 基础工具类
├── config/         # 配置系统
├── device/         # 设备连接
├── ui/             # UI 导航
├── ocr/            # OCR 系统
├── handler/        # 游戏处理器
├── combat/         # 战斗逻辑
├── map/            # 地图处理
├── campaign/       # 战役执行
├── research/       # 科研系统
├── commission/     # 委托系统
├── ...             # 其他游戏功能模块
└── webui/          # WebUI 应用
```

### 2.2 模块文件结构

每个游戏功能模块通常包含：
- `__init__.py` — 模块初始化
- `assets.py` — Button/Template 对象定义
- `<module>.py` — 主逻辑类（包含 `run()` 方法）
- 其他辅助文件

### 2.3 文件长度限制

- **单文件 ≤500 行**
- 一个函数一个画面（游戏界面状态）
- 过长的文件应拆分为多个子模块

---

## 三、注释规范

### 3.1 Docstring 格式

使用 Google 格式 docstring：

```python
def some_function(self, param1: str, param2: int = 0) -> bool:
    """
    函数功能描述。

    Args:
        param1: 参数1说明
        param2: 参数2说明，默认值为 0

    Returns:
        bool: 返回值说明

    Raises:
        SomeException: 异常说明
    """
```

### 3.2 页面状态注解

使用 `Pages:` 标注函数进出时的游戏界面状态：

```python
def navigate_to_shop(self):
    """
    导航到商店页面。

    Pages: in: page_main, out: page_shop
    """
```

### 3.3 注释比例

- 注释占函数的 1/3–1/2
- 重点解释 **为什么** 而不是 **做什么**
- 复杂逻辑配合流程图或时序图说明

---

## 四、日志规范

### 4.1 日志级别

使用 `logger.hr(title, level)` 做节标题：

| Level | 用途 | 示例 |
|-------|------|------|
| 0 | 脚本开始 | `logger.hr('AzurPilot', level=0)` |
| 1 | 功能开始 | `logger.hr('Research', level=1)` |
| 2 | 阶段开始 | `logger.hr('Select project', level=2)` |
| 3 | 子阶段 | `logger.hr('Check rewards', level=3)` |

### 4.2 属性记录

使用 `logger.attr(name, value)` 记录属性：

```python
logger.attr('Server', self.config.SERVER)
logger.attr('Campaign', self.config.Campaign_Name)
```

### 4.3 避免过度强调

如果什么都强调，就等于没强调。只在真正重要的地方使用强调。

---

## 五、状态循环模式（强制）

### 5.1 标准模式

所有游戏交互必须使用持续的截图-检查循环：

```python
def some_function(self, skip_first_screenshot=True):
    while 1:
        if skip_first_screenshot:
            skip_first_screenshot = False
        else:
            self.device.screenshot()

        # 退出条件——使用 appear()，不设 interval
        if self.appear(END_CONDITION):
            break

        # 点击——使用 interval 防止快速重复点击（2-5 秒）
        if self.appear_then_click(BUTTON_A, interval=2):
            continue
        if self.appear_then_click(BUTTON_B, interval=3):
            continue
```

### 5.2 绝对禁止的模式

- ❌ `click(X); sleep(2)` — 禁止"点击-等待"模式
- ❌ `sleep()` 出现在状态循环内
- ❌ 使用负面条件做循环控制（`if not self.appear(...)`）
- ❌ 用 `appear_then_click()` 做循环退出条件——用 `appear()` 退出
- ❌ 嵌套状态循环——展平到父循环
- ❌ 给退出条件设置 `interval`
- ❌ `handle_*()` 返回非 bool 值

### 5.3 handle_*() 方法规范

返回 `bool`：
- `True` — 已采取行动，需要新截图
- `False` — 未采取行动

---

## 六、异常处理规范

### 6.1 异常层次

```python
# 正常战役结束
CampaignEnd, OilExhausted, OilMaxed

# 地图导航错误
MapDetectionError, MapWalkError, MapEnemyMoved, CampaignNameError

# 游戏状态错误（触发重启）
GameStuckError, GameBugError, GameTooManyClickError

# 连接/页面错误
GameNotRunningError, GamePageUnknownError, EmulatorNotRunningError

# 开发者错误
ScriptError, ScriptEnd

# 不可恢复
RequestHumanTakeover, AutoSearchSetError
```

### 6.2 异常捕获原则

- 异常只在顶层捕获
- 捕获时，日志和最近截图保存到单独的文件夹
- 用户身份信息被擦除
- 任务返回值：`True`（成功）、`False`（不可恢复）、`'recoverable'`（可自动恢复）

---

## 七、配置访问规范

### 7.1 配置路径格式

```
<Task>.<Group>.<Argument>
```

例如：`Main.Campaign.Name`

### 7.2 配置访问方式

```python
# 通过下划线分隔访问
self.config.Group_Argument

# 示例
self.config.Campaign_Name
self.config.Optimization_WhenTaskQueueEmpty
```

---

## 八、Button/Template 定义规范

### 8.1 Button 定义

```python
# 在 assets.py 中定义
BUTTON_A = Button(
    area=(100, 200, 300, 400),  # 边界框 (x1, y1, x2, y2)
    color=(255, 255, 255),      # 平均颜色
    file='assets/cn/module/BUTTON_A.png'  # 模板图像
)
```

### 8.2 Template 命名

必须以 `TEMPLATE_` 前缀命名：

```python
TEMPLATE_SHIP = Template(file='assets/cn/module/TEMPLATE_SHIP.png')
```

### 8.3 添加新 Button 流程

1. 在 1280×720 分辨率下截图
2. 复制到 `assets/` 目录
3. 在 Photoshop 中裁剪
4. 运行 `uv run -m dev_tools.button_extract`

---

## 九、模块独立性原则

- 所有模块可独立运行，不依赖 GUI 或用户配置
- 每个模块通常只有一个方法读取用户配置
- 模块间通过清晰的接口调用，避免循环依赖

---

## 十、性能考虑

- **~99% 运行时间**在等待模拟器截图（~350ms）
- **图像处理** ~2.5ms
- **地图检测/OCR** ~100-180ms
- **不需要过度优化 Python 代码**
- 避免不必要的重复计算
- 合理使用 `@cached_property` 缓存计算结果

---

## 十一、测试规范

- **没有正式的 Python 测试套件**
- 测试通过运行任务对接真实模拟器进行
- Webapp 有基本的 Playwright 测试（`webapp/tests/app.spec.js`）

---

## 十二、提交规范

### 12.1 提交信息格式

```
<type>(<scope>): <subject>

<body>

<footer>
```

### 12.2 Type 类型

- `feat`: 新功能
- `fix`: 修复 bug
- `docs`: 文档更新
- `style`: 代码格式调整
- `refactor`: 重构
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建/工具相关
