# 岛屿功能扩展设计文档

> 本文档记录岛屿模块新增功能的详细设计方案。

---

## 实现进度 TODO

- [ ] **功能1**: 岛屿计划 TODO 列表 — 创建统一的任务计划管理器
- [ ] **功能2**: 矿山/森林按库存阈值执行 — 检测仓库数量，低于阈值才安排生产
- [ ] **功能3**: 每日订单功能 — 自动接取和完成每日订单
- [ ] **功能4**: 货运委托功能 — 集成已有运输系统到 TODO 列表
- [ ] **功能5**: 每周珍珠售卖 — 按配置日自动全量卖出珍珠
- [ ] **功能6**: 经营模块智能分波 — 季节限定数量检测替换 + 加成商品检测替换
- [ ] **功能7**: 自动采集角色体力检测 — 体力 < 100 自动换人
- [ ] **功能8**: 摸猫/JUU速运任务 — 每日互动任务
- [ ] **功能9**: 给三个小人打招呼 — NPC 互动
- [ ] 配置系统：更新 [`argument.yaml`](module/config/argument/argument.yaml) 和 [`task.yaml`](module/config/argument/task.yaml)
- [ ] i18n：更新翻译文件
- [ ] 运行配置生成器

---

## 目录

1. [功能1: 岛屿计划 TODO 列表](#功能1-岛屿计划-todo-列表)
2. [功能2: 矿山/森林按库存阈值执行](#功能2-矿山森林按库存阈值执行)
3. [功能3: 每日订单功能](#功能3-每日订单功能)
4. [功能4: 货运委托功能](#功能4-货运委托功能)
5. [功能5: 每周珍珠售卖](#功能5-每周珍珠售卖)
6. [功能6: 经营模块智能分波](#功能6-经营模块智能分波)
7. [功能7: 自动采集角色体力检测换人](#功能7-自动采集角色体力检测换人)
8. [功能8: 摸猫/JUU速运任务](#功能8-摸猫juu速运任务)
9. [功能9: 给三个小人打招呼](#功能9-给三个小人打招呼)
10. [配置变更总览](#配置变更总览)
11. [任务调度集成](#任务调度集成)

---

## 功能1: 岛屿计划 TODO 列表

### 目标

创建一个统一的任务计划管理系统，让所有岛屿任务模块共享一个 `TODO` 列表。每次岛屿任务运行时，先生成 TODO 列表，按优先级排序执行。

### 设计方案

**新文件**: [`module/island/island_todo.py`](module/island/island_todo.py)

#### 核心类: `IslandTodo`

```python
class IslandTodo(Island):
    """岛屿任务 TODO 列表管理器"""

    # 任务优先级
    PRIORITY_MAP = {
        'receive_transport':    10,  # 收取货运委托
        'daily_order':          20,  # 每日订单
        'pearl_selling':        30,  # 每周珍珠（仅周一）
        'pet_cat':              35,  # 摸猫
        'juu_express':          36,  # 啾啾速运
        'greet':                37,  # 打招呼
        'farm':                 40,  # 农场
        'mine_forest':          50,  # 矿山/森林
        'ranch':                60,  # 牧场
        'fishery':              61,  # 渔场
        'business_wave1':       70,  # 经营第一波
        'business_wave2':       71,  # 经营第二波
        'manufacture':          80,  # 制造
        'restaurant':           90,  # 餐馆
        'teahouse':             91,  # 茶馆
        'grill':                92,  # 烤肉
        'juu_eatery':           93,  # 啾啾简餐
        'juu_coffee':           94,  # 啾咖啡
        'daily_gather':         100, # 每日采集
        'air_drop':             110, # 空投
        'season_task':          120, # 季节任务
        'transport_start':      130, # 开始货运委托
    }
```

#### TODO 条目结构

```python
class TodoItem:
    task_id: str        # 如 'farm', 'mine_forest'
    priority: int       # 优先级数字（越小越先执行）
    enabled: bool       # 用户配置是否启用
    description: str    # 描述
    run_func: callable  # 执行函数引用
```

#### 执行流程

```
IslandTodo.run()
  ├── generate_todo_list()     # 根据配置生成 TODO 列表
  │     ├── check_transport_receive()  # 检查货运委托领取
  │     ├── check_daily_order()         # 检查每日订单
  │     ├── check_pearl_selling()       # 检查是否周一可卖珍珠
  │     ├── check_pet_cat()             # 检查摸猫
  │     ├── check_juu_express()         # 检查啾啾速运
  │     ├── check_greet()              # 检查打招呼
  │     ├── check_farm_needs()          # 检查农场需求
  │     ├── check_mine_forest_needs()   # 检查矿山/森林需求
  │     ├── check_ranch_needs()         # 检查牧场需求
  │     ├── check_business()            # 检查经营（分两波）
  │     └── ...                         # 其他模块
  │
  ├── sort_todo_list()         # 按优先级排序
  │
  └── execute_todo_list()      # 依次执行
        ├── run_single_task(item)
        │     ├── if task_id == 'farm': IslandFarm(config, device).run()
        │     ├── if task_id == 'mine_forest': IslandMineForest(config, device).run()
        │     └── ...
        └── handle_error()     # 错误处理
```

### 配置项

- [`IslandPlan.EnabledModules`](module/config/argument/argument.yaml:1112): 启用模块列表，多选
- [`IslandPlan.TodoListOrder`](module/config/argument/argument.yaml:1112): TODO 顺序（按优先级默认）

### 与现有任务调度的关系

当前的 [`task.yaml`](module/config/argument/task.yaml:362) 中 `Island` 组有多个独立任务（IslandFarm、IslandRancher 等）。
新增 `IslandPlan` 任务后，用户可以选择使用统一的 `IslandPlan` 任务替代多个独立任务。

---

## 功能2: 矿山/森林按库存阈值执行

### 目标

当前 [`IslandMineForest.run()`](module/island/island_mine_forest.py:46) 根据固定槽位配置（Mining1~4、Felling1~4）决定哪些岗位运行，不考虑库存数量。
改为先检查仓库库存，低于阈值才安排生产。

### 设计方案

修改文件: [`module/island/island_mine_forest.py`](module/island/island_mine_forest.py)

#### 新增配置项

```yaml
IslandMine:
  MinCopper: 0        # 铜矿最低库存
  MinAluminium: 0     # 铝矿最低库存
  MinIron: 0          # 铁矿最低库存
  MinSulphur: 0       # 硫磺最低库存
  MinSilver: 0        # 银矿最低库存
  # 当对应矿物库存 < MinXxx 时，才安排该岗位
IslandForest:
  MinElegant: 0       # 优雅木材最低库存
  MinPractical: 0     # 实用木材最低库存
  MinSelected: 0      # 精选木材最低库存
```

#### 核心逻辑变更

```python
def check_inventory_and_prepare(self):
    """检查仓库中矿山/森林产品数量，生成需要生产的列表"""
    self.warehouse_filter('mine')
    image = self.device.screenshot()
    
    needs = []
    # 矿山产品
    for product_name, (_, _, _) in self.PRODUCT_CONFIGS.items():
        if product_name in ['Elegant', 'Practical', 'Selected', 'Natural']:
            continue  # 跳过森林产品
        min_key = f'Min{product_name}'
        threshold = getattr(self.config, f'IslandMine_{min_key}', 0)
        count = self.ocr_item_quantity(image, TEMPLATE_MINE_PRODUCTS[product_name])
        if count < threshold:
            needs.append(product_name)
    
    # 森林产品
    self.warehouse_filter('forest')
    image = self.device.screenshot()
    for product_name in ['Elegant', 'Practical', 'Selected', 'Natural']:
        # ... 同理
```

#### run() 方法修改

```python
def run(self):
    # 1. 检查库存，生成需要生产的列表
    needs = self.check_inventory_and_prepare()
    
    # 2. 根据 needs 决定哪些岗位要运行
    #    优先匹配 Mining1~4 和 Felling1~4 中配置了对应产品的岗位
    #    如果产品已经足够，对应岗位直接跳过
    
    # 3. 现有逻辑执行
    for post_id, product_config, time_var_name in all_configs:
        if product_config is not None and product_config in needs:
            self.run_single_post(post_id, product_config, time_var_name)
```

---

## 功能3: 每日订单功能

### 目标

岛屿系统中存在"每日订单"功能（在管理页面 → 采集页签旁的"订单"页签），玩家可以接取每日订单，完成后获得奖励。

### 设计方案

**新文件**: [`module/island/island_daily_order.py`](module/island/island_daily_order.py)

#### 核心类: `IslandDailyOrder`

```python
class IslandDailyOrder(Island):
    """每日订单处理"""
    
    def run(self):
        """
        执行每日订单流程：
        1. 进入管理页面 → 订单页签
        2. 领取已完成订单的奖励
        3. 检查是否有可用订单可接
        4. 自动接取符合条件（物品充足）的订单
        """
```

#### 流程详解

```
run()
  ├── goto_management()
  ├── switch_to_order_tab()       # 切换到订单页签
  ├── claim_completed_orders()    # 领取已完成的订单奖励
  ├── detect_available_orders()   # 检测可用订单列表
  │     ├── OCR 订单名称和需求物品
  │     └── 匹配仓库库存
  ├── accept_best_orders()        # 自动接取可完成的订单
  │     └── 确认接取
  └── set_next_run_time()         # 设置下次运行时间
```

#### 订单检测

- 订单区域有一个列表，可滑动查看
- 每个订单显示：需求物品图标 + 数量、奖励预览
- 有"接取"按钮（物品足够时亮起）或"已接取"状态

#### 配置项

```yaml
IslandDailyOrder:
  Enabled: true                          # 启用每日订单
  AutoAccept: true                       # 自动接取可用订单
  MaxOrders: 3                            # 最大同时接取订单数
  PriorityItems: [wheat, corn, ...]      # 优先消耗的物品种类
```

---

## 功能4: 货运委托功能

### 目标

货运委托（运输系统）已在 [`transport.py`](module/island/transport.py) 中有完整实现。
需要将其集成到 IslandPlan TODO 列表中，并支持配置启用的委托槽位和黑名单物品。

### 现有功能分析

[`transport.py`](module/island/transport.py) 已实现：

| 方法 | 功能 |
|------|------|
| [`IslandTransportRun.island_transport_run()`](module/island/transport.py:400) | 完整执行运输流程 |
| [`transport_receive()`](module/island/transport.py:280) | 领取已完成委托 |
| [`transport_detect()`](module/island/transport.py:249) | 检测委托状态 |
| [`transport_refresh()`](module/island/transport.py:334) | 刷新委托 |
| [`transport_start()`](module/island/transport.py:364) | 开始委托 |

### 需要新增的功能

1. **集成到 IslandPlan TODO**: 在 [`island_todo.py`](module/island/island_todo.py) 中检查 transport 状态
2. **配置支持**:
   - 是否启用运输委托
   - 委托黑名单物品（已实现 via [`blacklist`](module/island/transport.py:222)）
   - 自动刷新未满委托的开关

#### 配置项

```yaml
IslandTransport:
  Enabled: true
  AutoRefresh: true
  SubmitCopper: true
  SubmitAluminium: true
  # ... 其他物品（已存在）
```

---

## 功能5: 每周珍珠售卖

### 目标

每周一（或配置的某天）自动进入珍珠商店，将库存中的珍珠全部卖出。

### 设计方案

**新文件**: [`module/island/island_pearl_sell.py`](module/island/island_pearl_sell.py)

#### 核心类: `IslandPearlSell`

```python
class IslandPearlSell(Island):
    """每周珍珠售卖"""
    
    WEEKDAY_MAP = {
        'monday': 0,
        'tuesday': 1,
        # ...
    }
    
    def run(self):
        """
        流程：
        1. 检查今天是否是设定的售卖日
        2. 导航到岛屿商店
        3. 进入珍珠商店页签
        4. 检测当前珍珠数量
        5. 如果有珍珠，执行全量卖出
        6. 设置下周同一时间运行
        """
```

#### 流程详解

```
run()
  ├── if today != config.sell_day: skip
  ├── navigate_to_island_shop()
  ├── switch_to_pearl_tab()
  ├── detect_pearl_count()        # OCR 检测珍珠数量
  ├── if count > 0:
  │     ├── click_sell_all()       # 点击全部卖出
  │     └── confirm_sell()         # 确认
  └── schedule_next_week()        # 设置下周运行
```

#### 珍珠售卖UI

- 珍珠商店有专门页签
- 显示当前珍珠数量
- 有"全部卖出"按钮
- 确认弹窗

#### 配置项

```yaml
IslandPearlSell:
  Enabled: false                     # 默认关闭
  SellDay: monday                    # 售卖日（周一~周日）
  SellTime: "09:00"                  # 售卖时间
```

---

## 功能6: 经营模块智能分波

### 目标

对现有 [`IslandBusiness`](module/island/island_business.py:39) 经营模块进行三项增强：

1. **分两波经营**：将 5 个商店分成两波执行，避免单次运行时间过长
2. **季节限定检测替换**：检测季节限定餐品库存数量，如果 < 7 则替换为另一个可配置菜品
3. **加成商品检测替换**：检测当天具有加成的商品，如果条件满足则替换，优先从下往上替换

### 设计方案

修改文件: [`module/island/island_business.py`](module/island/island_business.py)

#### 6.1 分两波经营

将 5 个商店分成两个 Wave：

```python
WAVE_CONFIG = {
    'wave1': {
        'shops': ['有鱼餐馆', '白熊饮品', '啾啾简餐'],  # 前3个
        'priority': 70,  # TODO 优先级
    },
    'wave2': {
        'shops': ['乌鱼烤肉', '啾咖啡'],                # 后2个
        'priority': 71,  # TODO 优先级（稍低）
    }
}
```

**配置项**：

```yaml
IslandBusiness:
  WaveEnabled: true              # 启用分波
  Wave1Shops: [1, 2, 3]         # 第一波商店索引
  Wave2Shops: [4, 5]            # 第二波商店索引
  Wave1Time: "08:00"            # 第一波执行时间
  Wave2Time: "14:00"            # 第二波执行时间
```

**执行流程**：

```python
def should_run_wave1(self):
    """判断第一波是否需要执行"""
    now = datetime.now()
    wave1_time = now.replace(hour=8, minute=0, second=0)
    return now >= wave1_time

def should_run_wave2(self):
    """判断第二波是否需要执行"""
    now = datetime.now()
    wave2_time = now.replace(hour=14, minute=0, second=0)
    return now >= wave2_time

def run_wave(self, shop_list):
    """执行指定商店列表的经营"""
    for shop in shop_list:
        self._process_single_shop(shop)
```

#### 6.2 季节限定餐品数量检测替换

核心逻辑：在经营前检查仓库中季节限定餐品的数量，如果 < 7 则替换为备用菜品。

```python
def check_seasonal_dish_quantity(self, shop_name):
    """
    检查指定商店的季节限定餐品库存数量。
    
    Returns:
        list: 需要替换的餐品列表 [(原餐品, 替换餐品), ...]
    """
    replacement_plan = []
    
    # 获取当前商店的季节限定餐品
    seasonal_items = self._get_seasonal_items_for_shop(shop_name)
    if not seasonal_items:
        return replacement_plan
    
    # 遍历当前激活的餐品配置，检查季节限定品
    for product in self.active_products.get(shop_name, []):
        if product['name'] in seasonal_items:
            # 通过仓库 OCR 检测该餐品数量
            count = self._check_product_quantity(product['name'])
            if count < 7:
                logger.info(
                    f"{shop_name}: 季节限定 {product['name']} 库存 {count} < 7，"
                    f"需要替换"
                )
                # 查找备用菜品配置
                fallback = self._get_fallback_product(shop_name, product['name'])
                if fallback:
                    replacement_plan.append((product, fallback))
    
    return replacement_plan
```

**备用菜品配置**：

```yaml
IslandBusinessShop1:        # 有鱼餐馆
  # ... 现有 Product1~5 配置
  SeasonalFallback1: hearty_meal   # 季节限定餐品1的备用替换
  SeasonalFallback2: fo_tiao       # 季节限定餐品2的备用替换
```

#### 6.3 加成商品检测替换

核心逻辑：进入商店后，检测当天具有加成的商品（UI 上带有"推荐""流行"等标记），如果加成条件满足则替换当前商品，**优先从下往上替换**（即先替换最后一个槽位的商品）。

```python
def check_boosted_products(self, shop_name):
    """
    检测当天具有加成的商品，从下往上替换。
    
    加成判定：
    - 游戏 UI 中商品可能有特殊标记（如"推荐"标签、高亮边框等）
    - 通过模板匹配或颜色检测识别加成标记
    
    替换策略（从下往上）：
    - 假设有 5 个商品槽位：P1, P2, P3, P4, P5
    - 优先替换 P5 → P4 → P3 → P2 → P1
    """
    # 1. 截图商品区域
    self.device.screenshot()
    
    # 2. 检测所有商品的加成状态
    boosted_products = self._detect_boosted(shop_name)
    if not boosted_products:
        logger.info(f"{shop_name}: 没有检测到加成商品")
        return
    
    # 3. 获取当前已选择的商品列表（从下往上遍历）
    current_products = self.active_products.get(shop_name, [])
    # 倒序，从最后一个槽位开始检查
    for product in reversed(current_products):
        # 检查是否有加成商品可以替换这个槽位
        for boosted in boosted_products:
            if boosted['name'] != product['name']:
                # 检查加成条件是否满足
                if self._check_boost_condition(boosted):
                    logger.info(
                        f"{shop_name}: 加成商品 {boosted['name']} "
                        f"替换槽位商品 {product['name']}（从下往上）"
                    )
                    # 执行替换
                    self._replace_product(shop_name, product, boosted)
                    break
```

**加成商品检测方法**：

```python
def _detect_boosted(self, shop_name):
    """
    检测加成商品。
    
    方法1: 模板匹配 — 检测商品图标上的"推荐"标签
    方法2: 颜色检测 — 检测商品边框的特殊颜色
    方法3: OCR — 读取商品名称旁边的特殊文本
    """
    products = self.shop_products.get(shop_name, [])
    boosted = []
    
    for p in products:
        b = p.get('button')
        if not b:
            continue
        
        # 检测商品区域是否有"推荐"模板
        if hasattr(self, f'TEMPLATE_BOOSTED_{p["name"].upper()}'):
            template = getattr(self, f'TEMPLATE_BOOSTED_{p["name"].upper()}')
            if self.appear(template, offset=30):
                boosted.append(p)
                continue
        
        # 或者检测商品图标上叠加的加成标记
        TEMPLATE_BOOSTED_TAG = getattr(self, 'TEMPLATE_BOOSTED_TAG', None)
        if TEMPLATE_BOOSTED_TAG:
            area_img = crop(self.device.image, b.area)
            if TEMPLATE_BOOSTED_TAG.match(area_img, similarity=0.8):
                boosted.append(p)
    
    return boosted
```

**配置项**：

```yaml
IslandBusiness:
  BoostedReplace: true            # 启用加成商品替换
  BoostThreshold: 1.2             # 加成倍率阈值（如 1.2 倍以上才替换）
  BoostReplaceDirection: bottom_up  # 替换方向：bottom_up（从下往上）
```

---

## 功能7: 自动采集角色体力检测换人

### 目标

在 [`IslandDailyGather`](module/island/island_daily_gather.py:14) 每日自动采集流程中，选择角色时检测其剩余体力（疲劳值），如果低于 100 则换人。

### 设计方案

修改文件: [`module/island/island_daily_gather.py`](module/island/island_daily_gather.py)

#### 核心逻辑

```python
def select_collector_with_stamina(self):
    """
    选择采集角色时检测体力，低于 100 则换人。
    
    流程：
    1. 进入角色选择界面
    2. 对角色列表按"生活等级"升序排序
    3. 遍历角色列表，OCR 检测每个角色的体力值
    4. 如果体力 >= 100，选择该角色
    5. 如果所有角色体力都 < 100，选择体力最高的
    
    OCR 区域说明：
    - 体力值通常显示在角色头像旁边的数字
    - 格式如 "100/100" 或纯数字 "100"
    - 使用 Digit 或 Duration 进行 OCR
    """
```

#### 体力检测区域

```python
# 每个角色卡片上体力值显示区域（相对角色卡片区域的偏移）
STAMINA_AREA_RELATIVE = (80, 5, 120, 25)  # (x1, y1, x2, y2) 相对角色按钮
```

#### 修改后的角色选择流程

```python
def _select_characters_with_stamina_check(self):
    """
    修改后的角色选择流程（替换原来的简单选择）。
    
    步骤：
    1. 打开角色选择界面 → 按生活等级排序
    2. 对每个 "+" 按钮：
       a. 遍历角色列表（从上到下）
       b. 对每个角色截图体力区域 → OCR 读取数值
       c. 如果体力 >= 100 → 选中该角色
       d. 如果体力 < 100 → 跳过，继续找下一个
       e. 如果遍历完所有角色都 < 100 → 选体力最高的
    3. 确认选择
    """
    for slot_idx in range(3):  # 3 个采集槽位
        # 点击 "+" 按钮
        # 等待角色选择界面出现
        
        best_char = None       # (button, stamina)
        for attempt in range(max_swipes):
            self.device.screenshot()
            
            # 遍历当前页面的角色
            for char_button in self._get_visible_characters():
                stamina = self._ocr_stamina(char_button)
                logger.info(f"角色体力: {stamina}")
                
                if stamina >= 100:
                    # 找到体力充足的，直接选中
                    self.device.click(char_button)
                    self.device.sleep(0.5)
                    self.device.click(SELECT_UI_CONFIRM)
                    return
                
                # 记录体力最高的
                if best_char is None or stamina > best_char[1]:
                    best_char = (char_button, stamina)
            
            # 向下滑动查看更多角色
            self._swipe_down()
        
        # 没有体力 >= 100 的角色，选体力最高的
        if best_char:
            logger.warning(f"没有体力>=100的角色，选择体力最高的: {best_char[1]}")
            self.device.click(best_char[0])
            self.device.sleep(0.5)
            self.device.click(SELECT_UI_CONFIRM)
```

#### OCR 体力值

```python
def _ocr_stamina(self, char_button):
    """
    对角色按钮区域的体力值进行 OCR。
    
    Args:
        char_button: 角色按钮
        
    Returns:
        int: 体力值，OCR 失败返回 0
    """
    # 体力区域：角色按钮右上方的小数字
    stamina_area = (
        char_button.area[0] + self.STAMINA_AREA_RELATIVE[0],
        char_button.area[1] + self.STAMINA_AREA_RELATIVE[1],
        char_button.area[0] + self.STAMINA_AREA_RELATIVE[2],
        char_button.area[1] + self.STAMINA_AREA_RELATIVE[3],
    )
    
    ocr_btn = Button(
        area=stamina_area, color=(),
        button=stamina_area,
        file={'cn': '', 'en': '', 'jp': '', 'tw': ''}
    )
    
    ocr = Digit(ocr_btn, letter=(255, 255, 255), threshold=200)
    try:
        value = ocr.ocr(self.device.image)
        return int(value) if value else 0
    except:
        return 0
```

#### 配置项

```yaml
IslandDailyGather:
  StaminaThreshold: 100         # 体力阈值，低于此值换人
  StaminaCheckEnabled: true     # 启用体力检测
```

---

## 功能8: 摸猫/JUU速运任务

### 目标

每日在岛屿上执行两个小互动：

1. **摸猫**: 点击岛上出现的猫，获得好感度和随机奖励
2. **JUU速运**: 在岛屿场景中找到并点击啾啾速运的NPC/建筑物，领取或提交速运任务

### 设计方案

**新文件**: [`module/island/island_daily_interact.py`](module/island/island_daily_interact.py)

#### 核心类: `IslandDailyInteract`

```python
class IslandDailyInteract(Island):
    """每日互动任务：摸猫、JUU速运"""
    
    def run(self):
        """执行每日互动"""
        self.goto_island()
        self.pet_cat()
        self.juu_express()
    
    def pet_cat(self):
        """
        摸猫流程：
        1. 在岛屿主场景中寻找猫
        2. 猫会随机出现在岛屿各个位置
        3. 通过模板匹配检测猫
        4. 点击猫 → 出现互动弹窗
        5. 点击"抚摸"按钮
        6. 关闭奖励弹窗
        """
    
    def juu_express(self):
        """
        JUU速运流程：
        1. 在岛屿场景中寻找JUU速运点
        2. 通常在地图固定位置
        3. 点击进入速运界面
        4. 领取已完成速运的奖励
        5. 如果有可用速运，接受
        """
```

#### 摸猫检测

- 猫的图像模板存储在 [`assets/`](assets/) 中
- 猫可能出现在多个位置，使用模板匹配扫描全屏
- 如果没有检测到猫，说明已经被摸过了或不在场景中

#### JUU速运检测

- JUU速运在岛屿地图上有固定位置的建筑物/NPC
- 需要先进入岛屿场景，然后寻找速运入口
- 速运界面有：领取奖励、查看速运列表

#### 配置项

```yaml
IslandDailyInteract:
  PetCat: true               # 启用摸猫
  JuuExpress: true           # 启用JUU速运
```

---

## 功能9: 给三个小人打招呼

### 目标

岛屿场景中会出现三个可互动的小人（NPC/游客），点击给他们打招呼可以获得友好度或小奖励。

### 设计方案

在 [`module/island/island_daily_interact.py`](module/island/island_daily_interact.py) 中扩展。

#### 核心逻辑

```python
def greet_npcs(self):
    """
    给三个小人打招呼流程：
    1. 进入岛屿主场景
    2. 扫描场景中出现的 NPC 小人
    3. 小人有三种类型/位置
    4. 依次点击每个小人
    5. 点击"打招呼"按钮
    6. 关闭弹窗
    """
    
    NPC_TEMPLATES = [
        TEMPLATE_NPC_1,   # 小人1的模板
        TEMPLATE_NPC_2,   # 小人2的模板
        TEMPLATE_NPC_3,   # 小人3的模板
    ]
```

#### NPC 检测

- 三个小人在岛屿场景中的固定或半固定位置
- 使用模板匹配检测
- 可能出现在不同区域，需要扫描
- 如果已被打过招呼，小人可能消失或变为不同状态

#### 挑战与注意事项

1. 小人可能不在当前屏幕视口中，需要滑动地图寻找
2. 小人出现有随机性，不是每天都会出现
3. 点击后的弹窗需要处理

#### 配置项

```yaml
IslandDailyInteract:
  GreetNpcs: true            # 启用打招呼
  GreetNpcCount: 3           # 打招呼数量
```

---

## 配置变更总览

### [`argument.yaml`](module/config/argument/argument.yaml) 新增配置

```yaml
# ==================== Island 新增配置 ====================

IslandPlan:
  Season:
    value: spring
    option: [spring, summer, autumn, winter]
  # --- 新增 ---
  EnabledModules:
    value: []
    option: [Farm, Rancher, MineForest, Business, Restaurant, Teahouse, Grill, JuuEatery, JuuCoffee, DailyGather, AirDrop, Transport, DailyOrder, PearlSell, DailyInteract, SeasonTask, Manufacture]

IslandMine:
  # 现有 Mining1~4
  # --- 新增阈值 ---
  MinCopper: 0
  MinAluminium: 0
  MinIron: 0
  MinSulphur: 0
  MinSilver: 0

IslandForest:
  # 现有 Felling1~4
  # --- 新增阈值 ---
  MinElegant: 0
  MinPractical: 0
  MinSelected: 0
  MinNatural: 0

IslandBusiness:
  # --- 分波经营 ---
  WaveEnabled: true
  Wave1Shops: [1, 2, 3]
  Wave2Shops: [4, 5]
  Wave1Time: "08:00"
  Wave2Time: "14:00"
  # --- 季节限定替换 ---
  SeasonalReplaceEnabled: true
  SeasonalThreshold: 7
  # --- 加成商品替换 ---
  BoostedReplace: true
  BoostThreshold: 1.2
  BoostReplaceDirection: bottom_up

IslandBusinessShop1:
  SeasonalFallback1: hearty_meal
  SeasonalFallback2: fo_tiao

IslandDailyGather:
  StaminaThreshold: 100
  StaminaCheckEnabled: true

IslandDailyOrder:
  Enabled: true
  AutoAccept: true
  MaxOrders: 3

IslandPearlSell:
  Enabled: false
  SellDay:
    value: monday
    option: [monday, tuesday, wednesday, thursday, friday, saturday, sunday]
  SellTime: "09:00"

IslandDailyInteract:
  PetCat: true
  JuuExpress: true
  GreetNpcs: true
  GreetNpcCount: 3
```

### [`task.yaml`](module/config/argument/task.yaml) 修改

```yaml
Island:
  tasks:
    IslandPlan:
      - Scheduler
      - IslandPlan
      - IslandDailyOrder       # 新增
      - IslandPearlSell        # 新增
      - IslandDailyInteract    # 新增
    # ... 保留现有任务
```

---

## 任务调度集成

### IslandPlan 作为统一入口

用户可通过 `IslandPlan` 任务一键执行所有岛屿任务。调度方式：

1. **统一运行模式**: 启用 `IslandPlan` 后，自动生成 TODO 列表按优先级执行
2. **独立运行模式**: 保留现有独立任务（IslandFarm、IslandRancher 等），用户可单独调度

### 优先级调度

```
高优先级（立即执行）：
  收取货运委托 → 10
  每日订单 → 20
  每周珍珠 → 30（仅周一）
  摸猫/速运/打招呼 → 35-37

中优先级（定期执行）：
  农场/矿山/牧场 → 40-61
  经营第一波 → 70
  经营第二波 → 71
  制造 → 80
  餐饮类店铺 → 90-94

低优先级（确保每日执行）：
  每日采集 → 100
  空投 → 110
  季节任务 → 120
  货运开始 → 130
```

### 与 alas.py 集成

在 [`alas.py`](alas.py) 中 `AzurLaneAutoScript` 类的任务循环中，`IslandPlan` 作为 `Island` 组下的一个任务，按照标准调度流程运行。

---

## 文件结构变化

```
module/island/
├── island.py                    # 已有 - 核心类
├── island_todo.py               # 新增 - TODO 列表管理器
├── island_daily_order.py        # 新增 - 每日订单
├── island_pearl_sell.py         # 新增 - 珍珠售卖
├── island_daily_interact.py     # 新增 - 摸猫/速运/打招呼
├── island_mine_forest.py        # 修改 - 增加库存检测
├── island_business.py           # 修改 - 分波 + 季节检测 + 加成检测
├── island_daily_gather.py       # 修改 - 体力检测换人
├── transport.py                 # 已有 - 货运委托
├── assets.py                    # 已有 - 通用按钮资源
├── ...
```

---

## i18n 新增 Key

在 [`zh-CN.json`](module/config/i18n/zh-CN.json) 等翻译文件中新增：

```json
{
  "Island.IslandPlan.EnabledModules": "启用模块",
  "Island.IslandPlan.EnabledModules.description": "选择需要在岛屿计划中自动管理的模块",
  "Island.IslandMine.MinCopper": "铜矿最低库存",
  "Island.IslandMine.MinAluminium": "铝矿最低库存",
  "Island.IslandMine.MinIron": "铁矿最低库存",
  "Island.IslandMine.MinSulphur": "硫磺最低库存",
  "Island.IslandMine.MinSilver": "银矿最低库存",
  "Island.IslandForest.MinElegant": "优雅木材最低库存",
  "Island.IslandForest.MinPractical": "实用木材最低库存",
  "Island.IslandForest.MinSelected": "精选木材最低库存",
  "Island.IslandForest.MinNatural": "自然木材最低库存",

  "Island.IslandBusiness.WaveEnabled": "启用分波经营",
  "Island.IslandBusiness.WaveEnabled.description": "将5个商店分成两波执行",
  "Island.IslandBusiness.SeasonalReplaceEnabled": "季节限定替换",
  "Island.IslandBusiness.SeasonalReplaceEnabled.description": "季节限定菜品库存不足时自动替换",
  "Island.IslandBusiness.SeasonalThreshold": "季节限定替换阈值",
  "Island.IslandBusiness.BoostedReplace": "加成商品替换",
  "Island.IslandBusiness.BoostedReplace.description": "检测当天加成商品自动替换（从下往上）",
  "Island.IslandBusiness.BoostThreshold": "加成倍率阈值",
  "Island.IslandBusinessShop1.SeasonalFallback1": "季节限定备用菜品1",

  "Island.IslandDailyGather.StaminaThreshold": "体力阈值",
  "Island.IslandDailyGather.StaminaThreshold.description": "角色体力低于此值则换人",
  "Island.IslandDailyGather.StaminaCheckEnabled": "启用体力检测",

  "Island.IslandDailyOrder.Enabled": "启用每日订单",
  "Island.IslandPearlSell.Enabled": "启用珍珠售卖",
  "Island.IslandPearlSell.SellDay": "售卖日",
  "Island.IslandDailyInteract.PetCat": "摸猫",
  "Island.IslandDailyInteract.JuuExpress": "JUU速运",
  "Island.IslandDailyInteract.GreetNpcs": "打招呼"
}
```

---

## 实现优先级

| 优先级 | 功能 | 预计工作量 |
|--------|------|-----------|
| P0 | 矿山/森林库存阈值 | 小（改现有代码） |
| P0 | TODO 列表框架 | 中（新文件） |
| P0 | 经营模块智能分波 | 中（改现有代码） |
| P0 | 经营模块季节限定替换 | 中（新增逻辑） |
| P1 | 经营模块加成商品替换 | 中（需截图资源） |
| P1 | 货运委托集成 | 小（集成已有代码） |
| P1 | 每日订单 | 中（新功能） |
| P1 | 自动采集体力检测换人 | 小（改现有代码） |
| P2 | 珍珠售卖 | 小（新功能） |
| P2 | 摸猫/JUU速运 | 中（需截图资源） |
| P3 | 打招呼 | 中（需截图资源） |

> **注意**: 摸猫、JUU速运、给小人打招呼、加成商品检测等功能需要游戏内截图资源（Button/Template），需先通过 `dev_tools/button_extract.py` 从截图中提取按钮定义才能实现。
