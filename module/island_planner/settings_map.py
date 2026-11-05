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
- 空余岗位（目标都达标后）：各区域默认产品（`DefaultCrop`/`DefaultOre`/`DefaultWood`/`DefaultFish`）与岗位数，
  取闲时累积（为季节 PT）的产品；开启「填满空余岗位」时写满已解锁岗位，没有闲时产品则取价值最高的可生产产品。

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
    'shiitake_chicken_soup': 4051, 'green_jujube_porridge': 4052,
    # 白熊饮品
    'apple_juice': 3017, 'banana_mango': 3018, 'honey_lemon': 3019, 'strawberry_lemon': 3020,
    'lavender_tea': 3021, 'strawberry_honey': 3022, 'floral_fruity': 3103, 'fruit_paradise': 3104,
    'sunny_honey': 3105, 'carrot_pear_juice': 4013, 'chrysanthemum_tea': 4014,
    'spring_flower_tea': 4024, 'watermelon_juice': 4038,
    # 啾啾简餐
    'apple_pie': 3009, 'corn_cup': 3023, 'orange_pie': 3024, 'rice_mango': 3025, 'banana_crepe': 3026,
    'strawberry_charlotte': 3028, 'succulently_sweet': 3106, 'orchard_duo': 3107, 'berry_orange': 3108,
    'seafood_rice': 3118, 'water_chestnut_cake': 4053, 'sugar_tangerine_daifuku': 4054,
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
        'avocado': 2021, 'rubber': 2022, 'sugar_tangerine': 4047, 'green_jujube': 4049,
        'pear': 4005, 'persimmon': 4007,
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
        5002: 'IslandRancher.IslandFishery.MinCatfish',
        5003: 'IslandRancher.IslandFishery.MinKoiCarp',
        5004: 'IslandRancher.IslandFishery.MinCommonCarp',
        5005: 'IslandRancher.IslandFishery.MinShrimp',
        5006: 'IslandRancher.IslandFishery.MinCrayfish',
        5007: 'IslandRancher.IslandFishery.MinBass',
        5008: 'IslandRancher.IslandFishery.MinCrab',
        5101: 'IslandRancher.IslandFishery.MinSquid',
        5102: 'IslandRancher.IslandFishery.MinMackerel',
        5103: 'IslandRancher.IslandFishery.MinTuna',
        5104: 'IslandRancher.IslandFishery.MinSalmon',
        5105: 'IslandRancher.IslandFishery.MinRedSeaBream',
        5107: 'IslandRancher.IslandFishery.MinYellowfinTuna',
        5108: 'IslandRancher.IslandFishery.MinSeaCucumber',
    },
}

# 矿山/林场/渔场的 AzurPilot 产品名 -> 物品 ID，与 DefaultOre/DefaultWood/DefaultFish、UnlockedFish 的选项一致
PRODUCT_ITEM_IDS = {
    'mine': {'Copper': 2701, 'Aluminium': 2702, 'Iron': 2703, 'Sulphur': 2704, 'Silver': 2705},
    'wood': {'Practical': 2801, 'Selected': 2802, 'Elegant': 2803},
    'fishery': {
        'shell': 5001, 'catfish': 5002, 'koi_carp': 5003, 'common_carp': 5004, 'shrimp': 5005,
        'crayfish': 5006, 'bass': 5007, 'crab': 5008, 'squid': 5101, 'mackerel': 5102, 'tuna': 5103,
        'salmon': 5104, 'red_sea_bream': 5105, 'yellowfin_tuna': 5107, 'sea_cucumber': 5108,
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

# 制造业：各产线 AzurPilot 能生产的产品（名称见 island_manufacture.py）-> 物品 ID。
# 规划器写入启用的岗位数与 <产线>.Products（按计划产量排序的生产顺序）。
# 手工的季节限定品只列出 AzurPilot 有识别图的（荠菜干、夏季花束、梅花香包、冬季花束）。
MANUFACTURE_PRODUCTS = {
    'manufacturing_lumber': {
        'line': 'IslandManufacture.WoodProcessing',
        'products': {'file_cabinet': 3052, 'paper': 3048, 'notebook': 3049, 'chair_desk': 3050},
    },
    'manufacturing_electronic': {
        'line': 'IslandManufacture.ElectronicProcessing',
        'products': {'filter_element': 3056, 'ink_cartridge': 3053},
    },
    'manufacturing_machinery': {
        'line': 'IslandManufacture.Industrial',
        'products': {'iron_nail': 3044, 'cutlery': 3047, 'charcoal_brush': 3042, 'cable': 3043},
    },
    'manufacturing_crafts': {
        'line': 'IslandManufacture.Handmade',
        'products': {'leather': 3036, 'boot': 3040, 'peanut_oil': 4012, 'cloth': 3035, 'rope': 3037,
                     'shepherd_purse': 4027, 'summer_bouquet': 4042,
                     'plum_blossom_sachet': 4055, 'winter_bouquet': 4056},
    },
}
MANUFACTURE_LINES = {
    group: (f'{data["line"]}.Positions', set(data['products'].values()))
    for group, data in MANUFACTURE_PRODUCTS.items()
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


def restrict_calculator(calculator, meal_options, product_options, unlocked_fish=None):
    """求解前排除 AzurPilot 执行不了的配方与菜品。

    Args:
        calculator (ProductionPlanCalculator): 已按科技初始化，尚未求解。
        meal_options (dict): {餐厅编号: AzurPilot 后厨可选菜品名}。
        product_options (dict): {餐厅编号: AzurPilot 商区可选菜品名}。
        unlocked_fish (Iterable[str] | None): 已解锁的渔场产品名（UnlockedFish）。
            渔场产品的解锁条件不在岛屿科技里，游戏数据也查不到，由用户勾选；None 为全部可用。

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
    if unlocked_fish is not None:
        fish_ids = PRODUCT_ITEM_IDS['fishery']
        allowed_products['fishery'] &= {fish_ids[name] for name in unlocked_fish if name in fish_ids}
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
    """制造业各产线：启用的岗位数与生产顺序。

    岗位数为计划工作量需要的岗位，不超过已解锁岗位；生产顺序 `<产线>.Products` 为计划生产的
    产品按计划工作量降序排列，AzurPilot 按此顺序选品（材料不足时试下一个）。没有计划生产时
    顺序为空，AzurPilot 沿用产线的固定规则。
    """
    values = {}
    for group, data in MANUFACTURE_PRODUCTS.items():
        names = {item_id: name for name, item_id in data['products'].items()}
        workload = 0
        product_workload = {}
        for recipe_id, batches in calculator.production_plan.items():
            if calculator.recipe_group.get(recipe_id) != group or batches <= 1e-6:
                continue
            recipe = DIC_ISLAND_RECIPE[recipe_id]
            workload += recipe['workload'] * batches
            for item_id in recipe['commission_product']:
                if item_id in names:
                    product_workload[item_id] = product_workload.get(item_id, 0) + recipe['workload'] * batches
        unlocked = sum(
            1 for slot in calculator.GROUP_TO_SLOTS.get(group, [])
            if calculator.slot_available.get(slot, False))
        values[f'{data["line"]}.Positions'] = \
            min(ceil(workload / DAILY_WORKLOAD - 1e-6), unlocked, 2) if workload > 0 else 0
        order = sorted(product_workload, key=lambda i: (-product_workload[i], i))
        values[f'{data["line"]}.Products'] = ' > '.join(names[item_id] for item_id in order)
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


# 自动岗位数：店铺后厨的岗位数配置（选项 1–2）
KITCHEN_POST_NUMBERS = {
    kitchen['slot_group']: f'{kitchen["task"]}.{kitchen["task"]}.PostNumber' for kitchen in KITCHENS.values()
}


def auto_position_settings(calculator):
    """按岛屿科技解锁的岗位写入各区域岗位数（AutoPositions）。

    农田、果园、苗圃、矿山、林场、渔场写 Positions，店铺后厨写 PostNumber。区域一个岗位都
    没有解锁时不写（这些配置的最小值为 1），保留原值。

    Returns:
        dict: {配置路径: 已解锁岗位数}。
    """
    values = {}
    for group, path in {**POSITION_LIMITS, **KITCHEN_POST_NUMBERS}.items():
        unlocked = sum(1 for slot in calculator.GROUP_TO_SLOTS.get(group, [])
                       if calculator.slot_available.get(slot, False))
        if unlocked:
            values[path] = unlocked
    return values


# 闲时产能（目标都达标后的空余岗位）写入各区域的「默认产品」设置。
# products 为可选默认产品（名称 -> 物品ID），product_path 为默认产品配置；
# count 为默认产品岗位数配置及其上限（矿山/林场/渔场的配置名沿用旧的银矿/典雅之木/黄鳍金枪鱼）。
DEFAULT_PRODUCTS = {
    'field': {'products': CROP_ITEM_IDS['farm'], 'product_path': 'IslandFarm.IslandFarm.DefaultCrop',
              'count': ('IslandFarm.IslandFarm.PlantPotatoes', 4), 'place': 101},
    'orchard': {'products': CROP_ITEM_IDS['orchard'], 'product_path': 'IslandFarm.IslandOrchard.DefaultCrop',
                'count': ('IslandFarm.IslandOrchard.PlantRubber', 4), 'place': 501},
    'nursery': {'products': CROP_ITEM_IDS['nursery'], 'product_path': 'IslandFarm.IslandNursery.DefaultCrop',
                'count': ('IslandFarm.IslandNursery.PlantLavender', 2), 'place': 502},
    'mine': {'products': PRODUCT_ITEM_IDS['mine'], 'product_path': 'IslandMineForest.IslandMine.DefaultOre',
             'count': ('IslandMineForest.IslandMine.MineSilver', 4), 'place': 401},
    'wood': {'products': PRODUCT_ITEM_IDS['wood'], 'product_path': 'IslandMineForest.IslandForest.DefaultWood',
             'count': ('IslandMineForest.IslandForest.CutElegant', 4), 'place': 402},
    'fishery': {'products': PRODUCT_ITEM_IDS['fishery'], 'product_path': 'IslandRancher.IslandFishery.DefaultFish',
                'count': ('IslandRancher.IslandFishery.PlantYellowfinTuna', 3), 'place': None},
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


def producible_items(calculator, group):
    """该分组可用配方的产品 -> (单批产量, 单批工作量)；同一产品取工作量效率最高的配方。"""
    items = {}
    for recipe_id, recipe_group in calculator.recipe_group.items():
        if recipe_group != group or not calculator.recipe_available.get(recipe_id, False):
            continue
        recipe = DIC_ISLAND_RECIPE[recipe_id]
        for item_id, amount in recipe['commission_product'].items():
            best = items.get(item_id)
            if amount > 0 and (best is None or amount / recipe['workload'] > best[0] / best[1]):
                items[item_id] = (amount, recipe['workload'])
    return items


def fallback_product(calculator, group, candidates, priority='pt'):
    """没有闲时累积产品时，空余岗位的默认产品：可生产的候选里单位工作量价值最高的。

    priority 为 'pt' 时按季节 PT（pt_num），'coins' 时按订单价（order_price）。

    Returns:
        str | None: 产品名；该区域没有可生产的候选时为 None。
    """
    items = producible_items(calculator, group)
    key = 'order_price' if priority == 'coins' else 'pt_num'

    def value(name):
        amount, workload = items[candidates[name]]
        return DIC_ISLAND_ITEM[candidates[name]].get(key, 0) * amount / workload

    names = [name for name, item_id in candidates.items() if item_id in items]
    return max(names, key=lambda name: (value(name), name)) if names else None


def default_product_settings(calculator, fill_spare_posts=False, priority='pt'):
    """目标都达标后，空余岗位生产什么。

    默认产品取闲时累积量（为季节 PT）最多的产品；没有闲时产品时，fill_spare_posts 开启则取
    可生产产品中单位工作量价值最高的（fallback_product）。只选当前可生产的产品（科技、季节、
    已解锁的鱼），因此不会把空余岗位交给未解锁的产品。

    岗位数：fill_spare_posts 关闭时只写闲时累积需要的岗位数；开启时写满该区域已解锁的岗位。
    AzurPilot 只在所有底线达标后才把剩余空闲岗位交给默认产品，写满不会挤占底线需求。

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
        candidates = data['products']
        producible = producible_items(calculator, group)
        posts = {name: idle_posts(calculator, group, item_id) for name, item_id in candidates.items()
                 if item_id in producible}
        product = max(posts, key=lambda name: (posts[name], name)) if posts else None
        if product is not None and posts[product] > 0:
            count = limit if fill_spare_posts else min(posts[product], limit)
        elif fill_spare_posts:
            product = fallback_product(calculator, group, candidates, priority)
            count = limit if product else 0
            if product and limit:
                notes.append(f'{group_name}: no idle product planned, spare posts produce '
                             f'{DIC_ISLAND_ITEM[candidates[product]]["name"]["en"]}')
        else:
            product, count = None, 0
        if product is not None:
            values[data['product_path']] = product
        values[count_path] = count
    return values, notes


def build_settings(calculator, meal_options, product_options, fill_spare_posts=False, priority='pt',
                   auto_positions=False):
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
    if auto_positions:
        values.update(auto_position_settings(calculator))
    default_values, default_notes = default_product_settings(calculator, fill_spare_posts, priority)
    values.update(default_values)
    notes.extend(default_notes)
    return values, notes


def item_label(item_id):
    return DIC_ISLAND_ITEM[item_id]['name']['en']
