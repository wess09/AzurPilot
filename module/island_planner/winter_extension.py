"""Local island data for the winter season.

ALAS' generated ``data.py`` still ends at the summer season. Keep the winter
extension separate so the upstream file can be replaced verbatim when ALAS
publishes the new data, and apply it once while the planner package initializes.
"""

WINTER_ITEMS = {
    1023: {
        'name': {'cn': '砂糖橘树种', 'en': 'Sugar Tangerine Tree Seeds', 'jp': '砂糖橘の木の種', 'tw': '砂糖橘樹種'},
        'pt_num': 1, 'manage_influence': 0, 'order_price': 0,
    },
    1024: {
        'name': {'cn': '青枣树种', 'en': 'Green Jujube Tree Seeds', 'jp': '青棗の木の種', 'tw': '青棗樹種'},
        'pt_num': 1, 'manage_influence': 0, 'order_price': 0,
    },
    2023: {
        'name': {'cn': '砂糖橘', 'en': 'Sugar Tangerine', 'jp': '砂糖橘', 'tw': '砂糖橘'},
        'pt_num': 12, 'manage_influence': 0, 'order_price': 160,
    },
    2024: {
        'name': {'cn': '青枣', 'en': 'Green Jujube', 'jp': '青棗', 'tw': '青棗'},
        'pt_num': 15, 'manage_influence': 0, 'order_price': 180,
    },
    4043: {
        'name': {'cn': '冬菇', 'en': 'Shiitake', 'jp': '椎茸', 'tw': '冬菇'},
        'pt_num': 8, 'manage_influence': 0, 'order_price': 50,
    },
    4044: {
        'name': {'cn': '马蹄', 'en': 'Water Chestnut', 'jp': 'クワイ', 'tw': '荸薺'},
        'pt_num': 6, 'manage_influence': 0, 'order_price': 40,
    },
    4045: {
        'name': {'cn': '梅花', 'en': 'Plum Blossom', 'jp': '梅の花', 'tw': '梅花'},
        'pt_num': 10, 'manage_influence': 0, 'order_price': 65,
    },
    4046: {
        'name': {'cn': '冬季花卉', 'en': 'Winter Flower', 'jp': '冬の花', 'tw': '冬季花卉'},
        'pt_num': 10, 'manage_influence': 0, 'order_price': 65,
    },
    4047: {
        'name': {'cn': '梅花香包', 'en': 'Plum Blossom Sachet', 'jp': '梅の花の香袋', 'tw': '梅花香包'},
        'pt_num': 160, 'manage_influence': 280, 'order_price': 1200,
    },
    4048: {
        'name': {'cn': '冬季花束', 'en': 'Winter Bouquet', 'jp': '冬のブーケ', 'tw': '冬季花束'},
        'pt_num': 180, 'manage_influence': 280, 'order_price': 1350,
    },
    4049: {
        'name': {'cn': '冬菇炖鸡', 'en': 'Shiitake Chicken Soup', 'jp': '椎茸と鶏のスープ', 'tw': '冬菇燉雞'},
        'pt_num': 150, 'manage_influence': 280, 'order_price': 980,
    },
    4050: {
        'name': {'cn': '青枣粥', 'en': 'Green Jujube Porridge', 'jp': '青棗粥', 'tw': '青棗粥'},
        'pt_num': 120, 'manage_influence': 270, 'order_price': 860,
    },
    4051: {
        'name': {'cn': '马蹄糕', 'en': 'Water Chestnut Cake', 'jp': 'クワイの蒸し糕', 'tw': '馬蹄糕'},
        'pt_num': 90, 'manage_influence': 260, 'order_price': 700,
    },
    4052: {
        'name': {'cn': '砂糖橘大福', 'en': 'Sugar Tangerine Daifuku', 'jp': '砂糖橘大福', 'tw': '砂糖橘大福'},
        'pt_num': 110, 'manage_influence': 270, 'order_price': 820,
    },
}


def _recipe(name, workload, commission_cost, commission_product):
    return {
        'name': name,
        'workload': workload,
        'commission_cost': commission_cost,
        'production_limit': 5,
        'commission_product': commission_product,
        'second_product_display': {},
    }


WINTER_RECIPES = {
    501008: _recipe(
        {'cn': '砂糖橘', 'en': 'Sugar Tangerine', 'jp': '砂糖橘', 'tw': '砂糖橘'},
        45000, {1023: 4}, {2023: 8},
    ),
    501009: _recipe(
        {'cn': '青枣', 'en': 'Green Jujube', 'jp': '青棗', 'tw': '青棗'},
        54000, {1024: 4}, {2024: 12},
    ),
    9900025: _recipe(
        {'cn': '冬菇炖鸡', 'en': 'Shiitake Chicken Soup', 'jp': '椎茸と鶏のスープ', 'tw': '冬菇燉雞'},
        18000, {2602: 1, 4043: 2}, {4049: 1},
    ),
    9900026: _recipe(
        {'cn': '青枣粥', 'en': 'Green Jujube Porridge', 'jp': '青棗粥', 'tw': '青棗粥'},
        18000, {2024: 2, 2002: 5}, {4050: 1},
    ),
    9900027: _recipe(
        {'cn': '马蹄糕', 'en': 'Water Chestnut Cake', 'jp': 'クワイの蒸し糕', 'tw': '馬蹄糕'},
        12000, {4044: 2}, {4051: 1},
    ),
    9900028: _recipe(
        {'cn': '砂糖橘大福', 'en': 'Sugar Tangerine Daifuku', 'jp': '砂糖橘大福', 'tw': '砂糖橘大福'},
        12000, {2023: 2, 3004: 3}, {4052: 1},
    ),
    9900029: _recipe(
        {'cn': '梅花香包', 'en': 'Plum Blossom Sachet', 'jp': '梅の花の香袋', 'tw': '梅花香包'},
        36000, {4045: 3}, {4047: 1},
    ),
    9900030: _recipe(
        {'cn': '冬季花束', 'en': 'Winter Bouquet', 'jp': '冬のブーケ', 'tw': '冬季花束'},
        18000, {4045: 1, 4046: 4}, {4048: 1},
    ),
}

WINTER_RESTAURANT_RECIPES = {
    601: {4049: 9900025, 4050: 9900026},
    603: {4051: 9900027, 4052: 9900028},
}


def apply_winter_extension(data):
    """Merge winter items, recipes and restaurant menu entries into generated data.

    Args:
        data (module): The imported ``module.island_planner.data`` module.

    Returns:
        module: The same module after applying the idempotent extension.
    """
    data.DIC_ISLAND_ITEM.update(WINTER_ITEMS)
    data.DIC_ISLAND_RECIPE.update(WINTER_RECIPES)
    for restaurant_id, menu in WINTER_RESTAURANT_RECIPES.items():
        data.DIC_ISLAND_RESTAURANT_MENU_TO_RECIPE.setdefault(restaurant_id, {}).update(menu)
    return data
