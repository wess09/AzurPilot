"""把岛屿生产规划结果换算成 AzurPilot 已有的岛屿配置。

规划算法来自 AzurLaneAutoScript（见 calculator.py），本文件是 AzurPilot 专属的适配层，
不依赖设备，便于离线测试：

- 店铺后厨 `Island{Restaurant,Teahouse,JuuEatery,Grill,JuuCoffee}.Meal1~8/MealNumber1~8`：
  先列出售菜品（按日销量降序），再列原料/中间品（按日消耗降序）。出售菜品的目标库存为
  一个货架容量 + 一天销量，与 ALAS「餐厅保留 + 日缓冲」一致；中间品目标为一天消耗量。
- 挂机生产 `Island*NextTask.AwayCook`：该后厨闲时累积量最大的产品，没有则为 None。
- 商区 `IslandBusinessShop1~5.Product1~5`：该餐厅计划出售的菜品，按日销量降序。
- 农田 `IslandFarm/IslandOrchard/IslandNursery.CropTargets`：区域内所有作物都写明目标，
  计划消耗的作物为一天消耗量，不需要的作物为 0；只为攒 PT 的闲时作物只在日志中提示。

- 矿山/林场/渔场 `Min*`：一天计划消耗量，不用的为 0；闲时累积只在日志中提示。
- 渔场 `MinFreshwaterFishMeat`/`MinSaltwaterFishMeat`：鱼肉一天需要量，渔场任务按此把鱼兑换成鱼肉。
- 牧场 `MinChicken`（禽肉）/`MinPork`（鲜肉）取计划日产量，`Milk`/`Wool` 看计划是否养牛/羊。
- 制造业 `WoodProcessing/ElectronicProcessing/Industrial/Handmade.Positions`：计划需要的岗位数。
- 空余岗位（目标都达标后）：农田三区 `DefaultCrop` 与默认作物岗位数、`MineSilver`、`CutElegant`、
  `PlantYellowfinTuna` 取闲时累积（为季节 PT）的产品与岗位数。

AzurPilot 不会做或卖的菜品、不会种的作物、不会生产的矿石/木材/鱼/制造品，会在求解前从模型中排除，
避免规划出 AzurPilot 执行不了的方案。
"""
from math import ceil

from module.island.farm_targets import format_crop_targets
from module.island_planner.data import DIC_ISLAND_ITEM, DIC_ISLAND_RECIPE
from module.island_planner.restaurant_config import (
    WAITRESS_ANY,
    WAITRESS_NONE,
    get_restaurant_config,
)

GRADES = ('bronze', 'silver', 'gold', 'diamond')
MEAL_SLOTS = 8
PRODUCT_SLOTS = 5

# 餐厅编号 -> AzurPilot 配置组。slot_group 为 calculator.SLOT_TO_GROUP 中的后厨分组。
KITCHENS = {
    601: {'name': 'Restaurant', 'task': 'IslandRestaurant', 'business': 'IslandBusinessShop1', 'slot_group': 'koi'},
    602: {'name': 'Teahouse', 'task': 'IslandTeahouse', 'business': 'IslandBusinessShop2', 'slot_group': 'bear'},
    603: {'name': 'JuuEatery', 'task': 'IslandJuuEatery', 'business': 'IslandBusinessShop3', 'slot_group': 'eatery'},
    604: {'name': 'Grill', 'task': 'IslandGrill', 'business': 'IslandBusinessShop4', 'slot_group': 'grill'},
    901: {'name': 'JuuCoffee', 'task': 'IslandJuuCoffee', 'business': 'IslandBusinessShop5', 'slot_group': 'cafe'},
}
BUSINESS_TASK = 'IslandBusiness'

# AzurPilot 菜品名 -> 游戏物品 ID（按中文名与 data.py 对照得到）
DISH_ITEM_IDS = {
    # 有鱼餐馆
    'tofu': 3011, 'tofu_meat': 3012, 'omurice': 3013, 'cabbage_tofu': 3014, 'salad': 3015,
    'tofu_combo': 3101, 'hearty_meal': 3102, 'fish_chip': 3114, 'onion_fish': 3116, 'fo_tiao': 3120,
    'persimmon_cake': 4009, 'matsutake_chicken_soup': 4010, 'double_bamboo_shoots': 4025,
    'asparagus_shrimp': 4026, 'amaranth_rice_ball': 4039,
    # 白熊饮品
    'apple_juice': 3017, 'banana_mango': 3018, 'honey_lemon': 3019, 'strawberry_lemon': 3020,
    'lavender_tea': 3021, 'strawberry_honey': 3022, 'floral_fruity': 3103, 'fruit_paradise': 3104,
    'sunny_honey': 3105, 'carrot_pear_juice': 4013, 'chrysanthemum_tea': 4014,
    'spring_flower_tea': 4024, 'watermelon_juice': 4038,
    # 啾啾简餐
    'apple_pie': 3009, 'corn_cup': 3023, 'orange_pie': 3024, 'rice_mango': 3025, 'banana_crepe': 3026,
    'strawberry_charlotte': 3028, 'succulently_sweet': 3106, 'orchard_duo': 3107, 'berry_orange': 3108,
    'seafood_rice': 3118,
    # 烧烤店
    'roasted_skewer': 3029, 'chicken_potato': 3030, 'stir_fried_chicken': 3032, 'carrot_omelette': 3033,
    'steak_bowl': 3034, 'carnival': 3109, 'double_energy': 3110, 'crayfish_stir_fry': 3119,
    # 啾咖啡
    'iced_coffee': 3005, 'cheese': 3006, 'latte': 3007, 'citrus_coffee': 3008,
    'strawberry_milkshake': 3010, 'omelette': 3059, 'morning_light': 3111, 'wake_up_call': 3112,
    'fruity_fruitier': 3113,
}

# AzurPilot 作物名 -> 游戏物品 ID，按 IslandFarm 的三个区域分组
CROP_ITEM_IDS = {
    'farm': {
        'wheat': 2000, 'corn': 2001, 'rice': 2002, 'chinese_cabbage': 2003, 'potato': 2005,
        'soybean': 2006, 'pasture': 2008, 'coffee_bean': 2009,
    },
    'orchard': {
        'apple': 2016, 'citrus': 2017, 'banana': 2018, 'mango': 2019, 'lemon': 2020,
        'avocado': 2021, 'rubber': 2022, 'pear': 4005, 'persimmon': 4007,
    },
    'nursery': {
        'carrot': 2004, 'onion': 2007, 'flax': 2010, 'strawberry': 2011, 'cotton': 2012,
        'tea': 2014, 'lavender': 2015, 'pineapple': 4021, 'asparagus': 4019,
    },
}
CROP_AREAS = {
    'farm': {'task': 'IslandFarm', 'group': 'IslandFarm', 'slot_group': 'field'},
    'orchard': {'task': 'IslandFarm', 'group': 'IslandOrchard', 'slot_group': 'orchard'},
    'nursery': {'task': 'IslandFarm', 'group': 'IslandNursery', 'slot_group': 'nursery'},
}

# 矿山/林场/渔场：按物品设最低库存的生产区，{物品ID: 配置路径}。
# 岗位共享，目标只含一天计划消耗，闲时累积只作提示（同作物）。
THRESHOLD_GROUPS = {
    'mine': {
        2701: 'IslandMineForest.IslandMine.MinCopper',
        2702: 'IslandMineForest.IslandMine.MinAluminium',
        2703: 'IslandMineForest.IslandMine.MinIron',
        2704: 'IslandMineForest.IslandMine.MinSulphur',
        2705: 'IslandMineForest.IslandMine.MinSilver',
    },
    'wood': {
        2801: 'IslandMineForest.IslandForest.MinPractical',
        2802: 'IslandMineForest.IslandForest.MinSelected',
        2803: 'IslandMineForest.IslandForest.MinElegant',
    },
    'fishery': {
        5001: 'IslandRancher.IslandFishery.MinShell',
        5005: 'IslandRancher.IslandFishery.MinShrimp',
        5006: 'IslandRancher.IslandFishery.MinCrayfish',
        5007: 'IslandRancher.IslandFishery.MinBass',
        5008: 'IslandRancher.IslandFishery.MinCrab',
        5101: 'IslandRancher.IslandFishery.MinSquid',
        5107: 'IslandRancher.IslandFishery.MinYellowfinTuna',
        5108: 'IslandRancher.IslandFishery.MinSeaCucumber',
    },
}

# 鱼肉由鱼兑换得到（渔场任务养鱼后在商店「鱼肉加工」兑换），按一天需要量写入目标持有数量
FISH_MEAT_TARGETS = {
    2521: 'IslandRancher.IslandFishery.MinFreshwaterFishMeat',
    2522: 'IslandRancher.IslandFishery.MinSaltwaterFishMeat',
}

# 牧场：每种动物一个岗位，不与其他产品争岗位，目标取计划日产量。
# 鸡舍/猪圈按 AzurPilot 识别的禽肉/鲜肉库存触发；牛/羊只有开关。
RANCH_THRESHOLDS = {
    'ranch_chicken': (2602, 'IslandRancher.IslandRancher.MinChicken'),
    'ranch_pig': (2600, 'IslandRancher.IslandRancher.MinPork'),
}
RANCH_SWITCHES = {
    'ranch_cow': 'IslandRancher.IslandRancher.Milk',
    'ranch_sheep': 'IslandRancher.IslandRancher.Wool',
}

# 制造业：AzurPilot 每条产线固定生产这些产品（见 island_manufacture.py），
# 只能配置启用的岗位数。手工含各季节限定品。
MANUFACTURE_LINES = {
    'manufacturing_lumber': ('IslandManufacture.WoodProcessing.Positions', {3052}),
    'manufacturing_electronic': ('IslandManufacture.ElectronicProcessing.Positions', {3056}),
    'manufacturing_machinery': ('IslandManufacture.Industrial.Positions', {3044, 3047}),
    'manufacturing_crafts': ('IslandManufacture.Handmade.Positions',
                             {3036, 3040, 4011, 4012, 4027, 4028, 4041, 4042}),
}
# 一个岗位一天的工作量，与 calculator._build_production_problem 一致
DAILY_WORKLOAD = 24 * 60 * 60 * 10


# AzurPilot 商区角色名 -> ALAS 服务员名（只有这些角色有容量或售价加成）
WAITRESS_ALIASES = {
    'ChaoHo': 'Chao_Ho',
    'Cheshire': 'Cheshire',
    'Helena': 'Helena',
    'Eugen': 'Prinz_Eugen',
    'August': 'August_von_Parseval',
    'Belfast': 'Belfast',
    'ChangFeng': 'Chang_Feng',
}


def recipe_product(recipe_id):
    return next(iter(DIC_ISLAND_RECIPE[recipe_id]['commission_product']))


def waitress_slots(restaurant_id, chars):
    """把商区 Char1/Char2 换算成 ALAS 的服务员槽位。

    AzurPilot 中 None 表示由工作啾代班，店照常营业，因此与其他无加成角色一样视为 any；
    对本店有加成的角色保留名字。同一加成角色重复填写时第二个视为 any，避免 ALAS 判为非法配置。
    """
    options = get_restaurant_config(restaurant_id)['waitress_options']
    slots = []
    for char in chars:
        name = WAITRESS_ALIASES.get(char)
        if name in options and name not in slots:
            slots.append(name)
        else:
            slots.append(WAITRESS_ANY)
    return tuple(slots)


def open_restaurants(batch_enabled, batch1, batch2):
    """商区会营业的餐厅编号。分批经营开启时只有列在某一批里的店营业。"""
    if not batch_enabled:
        return set(KITCHENS)
    indexes = {int(index) for index in list(batch1 or []) + list(batch2 or [])}
    return {rid for rid, kitchen in KITCHENS.items() if int(kitchen['business'][-1]) in indexes}


def restaurant_settings(grades, chars, open_ids=None):
    """
    Args:
        grades (dict): {餐厅编号: 'bronze'|'silver'|'gold'|'diamond'}。
        chars (dict): {餐厅编号: (Char1, Char2)}，来自 IslandBusinessShopN。
        open_ids (set): 营业的餐厅编号，None 为全部营业。不营业的店不参与出售。

    Returns:
        dict: calculator 的 restaurant_settings 参数。
    """
    settings = {}
    for restaurant_id in KITCHENS:
        grade = grades.get(restaurant_id) or 'bronze'
        if grade not in GRADES:
            raise ValueError(f'Invalid restaurant grade: {grade}')
        if open_ids is not None and restaurant_id not in open_ids:
            slots = (WAITRESS_NONE, WAITRESS_NONE)
        else:
            slots = waitress_slots(restaurant_id, chars.get(restaurant_id, (None, None)))
        settings[restaurant_id] = {'grade': grade, 'waitress_slots': slots}
    return settings


def restrict_calculator(calculator, meal_options, product_options):
    """求解前排除 AzurPilot 执行不了的配方与菜品。

    Args:
        calculator (ProductionPlanCalculator): 已按科技初始化，尚未求解。
        meal_options (dict): {餐厅编号: AzurPilot 后厨可选菜品名}。
        product_options (dict): {餐厅编号: AzurPilot 商区可选菜品名}。

    Returns:
        list[str]: 被排除的配方说明，供日志查看。
    """
    allowed_products = {}
    for restaurant_id, kitchen in KITCHENS.items():
        allowed_products[kitchen['slot_group']] = {
            DISH_ITEM_IDS[name] for name in meal_options.get(restaurant_id, ()) if name in DISH_ITEM_IDS}
    for area, data in CROP_AREAS.items():
        allowed_products[data['slot_group']] = set(CROP_ITEM_IDS[area].values())
    for group, items in THRESHOLD_GROUPS.items():
        allowed_products[group] = set(items)
    for group, (_, items) in MANUFACTURE_LINES.items():
        allowed_products[group] = set(items)

    excluded = []
    for recipe_id, group in calculator.recipe_group.items():
        if group not in allowed_products or not calculator.recipe_available.get(recipe_id, False):
            continue
        if recipe_product(recipe_id) not in allowed_products[group]:
            calculator.recipe_available[recipe_id] = False
            excluded.append(DIC_ISLAND_RECIPE[recipe_id]['name']['en'])

    calculator.sellable_items = {
        restaurant_id: {DISH_ITEM_IDS[name] for name in product_options.get(restaurant_id, ())
                        if name in DISH_ITEM_IDS}
        for restaurant_id in KITCHENS
    }
    return excluded


def daily_need(calculator):
    """每日需要的库存宽度：计划消耗量（日缓冲）+ 季节任务/额外目标的每日速率。

    目标物品在计划中是「累积」而不是被消耗，不出现在日缓冲里；不加上它，
    AzurPilot 的阈值/后厨目标不会为目标物品开工。
    """
    need = dict(calculator.product_daily_buffer_items)
    for item_id, data in (getattr(calculator, 'demand_items', None) or {}).items():
        rate = data.get('rate_per_day', 0)
        if rate > 0:
            need[item_id] = need.get(item_id, 0) + rate
    return need


def _item_name_map(names):
    return {DISH_ITEM_IDS[name]: name for name in names if name in DISH_ITEM_IDS}


def _produced_items(calculator, slot_group):
    """该分组计划生产的产品 -> 每日产量。"""
    produced = {}
    for recipe_id, batches in calculator.production_plan.items():
        if calculator.recipe_group.get(recipe_id) != slot_group or batches <= 1e-6:
            continue
        for item_id, amount in DIC_ISLAND_RECIPE[recipe_id]['commission_product'].items():
            produced[item_id] = produced.get(item_id, 0) + amount * batches
    return produced


def kitchen_settings(calculator, restaurant_id, meal_options, product_options):
    """单个店铺的后厨、挂机与商区配置。

    Returns:
        tuple[dict, list[str]]: ({配置路径: 值}, 提示信息)。
    """
    kitchen = KITCHENS[restaurant_id]
    task = kitchen['task']
    notes = []
    meal_names = _item_name_map(meal_options)
    product_names = _item_name_map(product_options)
    capacity = calculator.restaurant_capacity[restaurant_id]
    buffer = daily_need(calculator)
    idle = calculator.idle_accumulating_items_per_day

    sales = {
        item_id: amount for (slot, item_id), amount in calculator.sell_plan.items()
        if slot == restaurant_id and amount > 1e-6
    }
    produced = _produced_items(calculator, kitchen['slot_group'])

    meals = []
    for item_id in sorted(sales, key=lambda i: (-sales[i], i)):
        if item_id in meal_names:
            meals.append((meal_names[item_id], capacity + ceil(buffer.get(item_id, sales[item_id]) - 1e-9)))
    sold = {item_id for item_id in sales}
    others = [item_id for item_id in produced if item_id not in sold and buffer.get(item_id, 0) > 0]
    for item_id in sorted(others, key=lambda i: (-buffer[i], i)):
        if item_id in meal_names:
            meals.append((meal_names[item_id], ceil(buffer[item_id] - 1e-9)))
    if len(meals) > MEAL_SLOTS:
        dropped = [name for name, _ in meals[MEAL_SLOTS:]]
        notes.append(f'{task}: only {MEAL_SLOTS} meal slots, dropped {dropped}')
        meals = meals[:MEAL_SLOTS]

    values = {}
    for index in range(MEAL_SLOTS):
        name, number = meals[index] if index < len(meals) else ('None', 0)
        values[f'{task}.{task}.Meal{index + 1}'] = name
        values[f'{task}.{task}.MealNumber{index + 1}'] = number

    idle_items = [item_id for item_id in produced if idle.get(item_id, 0) > 0 and item_id in meal_names]
    away = max(idle_items, key=lambda i: (idle[i], -i)) if idle_items else None
    values[f'{task}.{task}NextTask.AwayCook'] = meal_names[away] if away else 'None'

    products = [product_names[item_id] for item_id in sorted(sales, key=lambda i: (-sales[i], i))
                if item_id in product_names]
    if len(products) > PRODUCT_SLOTS:
        notes.append(f'{kitchen["business"]}: only {PRODUCT_SLOTS} product slots, dropped {products[PRODUCT_SLOTS:]}')
        products = products[:PRODUCT_SLOTS]
    business = kitchen['business']
    for index in range(PRODUCT_SLOTS):
        values[f'{BUSINESS_TASK}.{business}.Product{index + 1}'] = \
            products[index] if index < len(products) else 'None'
    return values, notes


def crop_settings(calculator):
    """三个种植区域的 CropTargets。

    目标只含一天的计划消耗量（ALAS 的日缓冲），不含闲时累积量：AzurPilot 按
    「库存/目标」比例排序补种，若把闲时累积量计入目标，只为攒 PT 的作物会挤占
    真正需要的作物。闲时累积的作物作为提示返回，由用户在区域的默认作物岗位数中安排。

    Returns:
        tuple[dict, list[str]]: ({配置路径: 值}, 提示信息)。
    """
    buffer = daily_need(calculator)
    idle = calculator.idle_accumulating_items_per_day
    values = {}
    notes = []
    for area, data in CROP_AREAS.items():
        targets = {}
        idle_crops = []
        for crop, item_id in CROP_ITEM_IDS[area].items():
            amount = buffer.get(item_id, 0)
            targets[crop] = ceil(amount - 1e-9) if amount > 0 else 0
            if idle.get(item_id, 0) > 0:
                idle_crops.append((idle[item_id], crop))
        values[f'{data["task"]}.{data["group"]}.CropTargets'] = format_crop_targets(targets)
        if idle_crops:
            text = ', '.join(f'{crop} {amount:.0f}/day' for amount, crop in sorted(idle_crops, reverse=True))
            notes.append(f'{data["group"]}: spare posts can grow {text} for season PT (default crop settings)')
    return values, notes


def _idle_note(name, items, idle):
    idle_items = sorted(((idle[i], i) for i in items if idle.get(i, 0) > 0), reverse=True)
    if not idle_items:
        return None
    text = ', '.join(f'{DIC_ISLAND_ITEM[i]["name"]["en"]} {amount:.0f}/day' for amount, i in idle_items)
    return f'{name}: spare posts can produce {text} for season PT (default product settings)'


def threshold_settings(calculator):
    """矿山、林场、渔场的最低库存：一天计划消耗量，不用的为 0。"""
    buffer = daily_need(calculator)
    idle = calculator.idle_accumulating_items_per_day
    values = {}
    notes = []
    for group, items in THRESHOLD_GROUPS.items():
        for item_id, path in items.items():
            amount = buffer.get(item_id, 0)
            values[path] = ceil(amount - 1e-9) if amount > 0 else 0
        note = _idle_note(next(iter(items.values())).split('.')[1], items, idle)
        if note:
            notes.append(note)
    for item_id, path in FISH_MEAT_TARGETS.items():
        amount = buffer.get(item_id, 0)
        values[path] = ceil(amount - 1e-9) if amount > 0 else 0
    return values, notes


RANCH_SLOTS = {'ranch_chicken': 9031, 'ranch_pig': 9032, 'ranch_cow': 9033, 'ranch_sheep': 9034}


def _ranch_output(calculator, group):
    """牧场岗位每日产出，与 calculator 的建模一致：按牧场科技等级放大，
    解锁副产物科技后副产物（禽肉、皮料）按每 3 批一次摊入。"""
    multiplier = 1 + calculator.ranch_level[RANCH_SLOTS[group]]
    output = {}
    for recipe_id, batches in calculator.production_plan.items():
        if calculator.recipe_group.get(recipe_id) != group or batches <= 1e-6:
            continue
        recipe = DIC_ISLAND_RECIPE[recipe_id]
        for item_id, amount in recipe['commission_product'].items():
            output[item_id] = output.get(item_id, 0) + amount * multiplier * batches
        if calculator.ranch_additional:
            for item_id, amount in recipe['second_product_display'].items():
                output[item_id] = output.get(item_id, 0) + (
                    amount * multiplier / calculator.RANCH_SECOND_PRODUCT_INTERVAL * batches)
    return output


def ranch_settings(calculator):
    """牧场：鸡舍/猪圈阈值取计划日产量，牛/羊开关看计划是否使用。"""
    values = {}
    for group, (item_id, path) in RANCH_THRESHOLDS.items():
        used = any(amount > 1e-6 for amount in _ranch_output(calculator, group).values())
        produced = _ranch_output(calculator, group).get(item_id, 0)
        # 用到该岗位时至少为 1，保证库存为 0 时会开工；未解锁副产物时禽肉不会增加，鸡舍会一直开工
        values[path] = max(ceil(produced - 1e-9), 1) if used else 0
    for group, path in RANCH_SWITCHES.items():
        values[path] = any(amount > 1e-6 for amount in _ranch_output(calculator, group).values())
    return values


def manufacture_settings(calculator):
    """制造业各产线启用的岗位数：计划工作量需要的岗位，不超过已解锁岗位。"""
    values = {}
    for group, (path, _) in MANUFACTURE_LINES.items():
        workload = 0
        for recipe_id, batches in calculator.production_plan.items():
            if calculator.recipe_group.get(recipe_id) == group:
                workload += DIC_ISLAND_RECIPE[recipe_id]['workload'] * batches
        unlocked = sum(
            1 for slot in calculator.GROUP_TO_SLOTS.get(group, [])
            if calculator.slot_available.get(slot, False))
        values[path] = min(ceil(workload / DAILY_WORKLOAD - 1e-6), unlocked, 2) if workload > 0 else 0
    return values


# 各区域任务实际运行的岗位数配置；规划器按它限制可用岗位，超出部分的产能不会实际产出。
POSITION_LIMITS = {
    'field': 'IslandFarm.IslandFarm.Positions',
    'orchard': 'IslandFarm.IslandOrchard.Positions',
    'nursery': 'IslandFarm.IslandNursery.Positions',
    'mine': 'IslandMineForest.IslandMine.Positions',
    'wood': 'IslandMineForest.IslandForest.Positions',
    'fishery': 'IslandRancher.IslandFishery.Positions',
}


def position_limits(get):
    """读取各区域的岗位数配置，get(path) 取不到或不是整数时不限制该区域。"""
    limits = {}
    for group, path in POSITION_LIMITS.items():
        value = get(path)
        if isinstance(value, int) and not isinstance(value, bool):
            limits[group] = value
    return limits


# 闲时产能（目标都达标后的空余岗位）写入各区域的「默认产品」设置。
# crops 为可选默认作物（名称 -> 物品ID），fixed 为写死的默认产品；count 为默认产品岗位数配置及其上限。
DEFAULT_PRODUCTS = {
    'field': {'crops': CROP_ITEM_IDS['farm'], 'crop_path': 'IslandFarm.IslandFarm.DefaultCrop',
              'count': ('IslandFarm.IslandFarm.PlantPotatoes', 4), 'place': 101},
    'orchard': {'crops': CROP_ITEM_IDS['orchard'], 'crop_path': 'IslandFarm.IslandOrchard.DefaultCrop',
                'count': ('IslandFarm.IslandOrchard.PlantRubber', 4), 'place': 501},
    'nursery': {'crops': CROP_ITEM_IDS['nursery'], 'crop_path': 'IslandFarm.IslandNursery.DefaultCrop',
                'count': ('IslandFarm.IslandNursery.PlantLavender', 2), 'place': 502},
    'mine': {'fixed': 2705, 'count': ('IslandMineForest.IslandMine.MineSilver', 4), 'place': 401},
    'wood': {'fixed': 2803, 'count': ('IslandMineForest.IslandForest.CutElegant', 4), 'place': 402},
    'fishery': {'fixed': 5107, 'count': ('IslandRancher.IslandFishery.PlantYellowfinTuna', 3), 'place': None},
}


def idle_posts(calculator, group, item_id):
    """闲时累积 item_id 每天需要的岗位数（按配方工作量与区域效率加成换算，向上取整）。"""
    rate = calculator.idle_accumulating_items_per_day.get(item_id, 0)
    if rate <= 0:
        return 0
    place = DEFAULT_PRODUCTS[group]['place']
    efficiency = 1 + (calculator.place_efficiency_bonus.get(place, 0) if place else 0)
    for recipe_id, recipe_group in calculator.recipe_group.items():
        recipe = DIC_ISLAND_RECIPE[recipe_id]
        if recipe_group != group or not calculator.recipe_available.get(recipe_id, False):
            continue
        amount = recipe['commission_product'].get(item_id, 0)
        if amount > 0:
            workload = rate / amount * recipe['workload'] / efficiency
            return ceil(workload / DAILY_WORKLOAD - 1e-6)
    return 0


def default_product_settings(calculator):
    """目标都达标后，空余岗位生产什么：取闲时累积量（为季节 PT）对应的产品与岗位数。

    农田三区的默认作物可选，取需要岗位最多的闲时作物；矿山（银矿）、林场（典雅之木）、
    渔场（黄鳍金枪鱼）的默认产品写死，只写岗位数，闲时产品不同时记录提示并置 0。

    Returns:
        tuple[dict, list[str]]: ({配置路径: 值}, 提示信息)。
    """
    values = {}
    notes = []
    for group, data in DEFAULT_PRODUCTS.items():
        count_path, limit = data['count']
        unlocked = sum(1 for slot in calculator.GROUP_TO_SLOTS.get(group, [])
                       if calculator.slot_available.get(slot, False))
        limit = min(limit, unlocked)
        group_name = count_path.split('.')[1]
        if 'crops' in data:
            posts = {crop: idle_posts(calculator, group, item_id) for crop, item_id in data['crops'].items()}
            crop = max(posts, key=lambda name: (posts[name], name)) if posts else None
            if crop and posts[crop] > 0:
                values[data['crop_path']] = crop
                values[count_path] = min(posts[crop], limit)
            else:
                values[count_path] = 0
            continue
        posts = idle_posts(calculator, group, data['fixed'])
        values[count_path] = min(posts, limit)
        if posts <= 0:
            others = [DIC_ISLAND_ITEM[item_id]['name']['en']
                      for item_id in calculator.idle_accumulating_items_per_day
                      if any(calculator.recipe_group.get(r) == group
                             and item_id in DIC_ISLAND_RECIPE[r]['commission_product']
                             for r in calculator.recipe_group)]
            if others:
                notes.append(f'{group_name}: spare posts would produce {", ".join(others)}, '
                             f'but the default product is fixed to {DIC_ISLAND_ITEM[data["fixed"]]["name"]["en"]}')
    return values, notes


def build_settings(calculator, meal_options, product_options):
    """求解成功后，生成要写入的全部配置。

    Returns:
        tuple[dict, list[str]]: ({配置路径: 值}, 提示信息)。
    """
    values = {}
    notes = []
    for restaurant_id in KITCHENS:
        kitchen_values, kitchen_notes = kitchen_settings(
            calculator, restaurant_id,
            meal_options.get(restaurant_id, ()), product_options.get(restaurant_id, ()))
        values.update(kitchen_values)
        notes.extend(kitchen_notes)
    crop_values, crop_notes = crop_settings(calculator)
    values.update(crop_values)
    notes.extend(crop_notes)
    threshold_values, threshold_notes = threshold_settings(calculator)
    values.update(threshold_values)
    notes.extend(threshold_notes)
    values.update(ranch_settings(calculator))
    values.update(manufacture_settings(calculator))
    default_values, default_notes = default_product_settings(calculator)
    values.update(default_values)
    notes.extend(default_notes)
    return values, notes


def item_label(item_id):
    return DIC_ISLAND_ITEM[item_id]['name']['en']
