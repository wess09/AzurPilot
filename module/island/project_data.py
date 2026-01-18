import module.config.server as server

__name_to_slot_cn = {
    '丰壤农田': 4, '悠然牧场': 4, '沉石矿山': 4, '翠土林场': 4, '坠香果园': 4, '青芽苗圃': 2,
    '有鱼餐馆': 2, '白熊饮品': 2, '啾啾简餐': 2, '乌鱼烤肉': 2, '木料加工设备': 2, '工业生产设备': 2,
    '电子加工设备': 2, '手工制作设备': 2, '啾咖啡': 2
}

__items_data_cn = {
    1: {
        1: '小麦', 2: '玉米', 3: '牧草', 4: '咖啡豆', 5: '大米', 6: '白菜',
        7: '土豆', 8: '大豆',
    },
    2: {
        1: '鸡蛋', 2: '鲜肉', 3: '牛奶', 4: '羊毛',
    },
    3: {
        1: '煤炭', 2: '铜矿', 3: '铝矿', 4: '铁矿', 5: '硫矿', 6: '银矿',
    },
    4: {
        1: '自然之木', 2: '实用之木', 3: '精选之木', 4: '典雅之木',
    },
    5: {
        1: '秋月梨', 2: '柿子', 3: '苹果', 4: '柑橘', 5: '香蕉', 6: '芒果',
        7: '柠檬', 8: '牛油果', 9: '橡胶',
    },
    6: {
        1: '亚麻', 2: '草莓', 3: '棉花', 4: '茶叶', 5: '薰衣草', 6: '胡萝卜',
        7: '洋葱',
    },
    7: {
        1: '柿子饼', 2: '松茸鸡汤', 3: '豆腐', 4: '肉末烧豆腐', 5: '蛋包饭',
        6: '白菜豆腐汤', 7: '蔬菜沙拉', 8: '经典豆腐套餐', 9: '绵玉定食',
    },
    8: {
        1: '胡萝卜秋梨汁', 2: '菊花茶', 3: '苹果汁', 4: '香蕉芒果汁',
        5: '蜂蜜柠檬水', 6: '草莓蜜沁', 7: '薰衣草茶', 8: '草莓蜂蜜冰沙',
        9: '阳光蜜水', 10: '花香果韵', 11: '缤纷果乐园',
    },
    9: {
        1: '玉米杯', 2: '苹果派', 3: '香橙派', 4: '芒果糯米饭', 5: '香蕉可丽饼',
        6: '草莓夏洛特', 7: '香甜组合', 8: '果园二重奏', 9: '莓果香橙甜点组',
    },
    10: {
        1: '炭烤肉串', 2: '禽肉土豆拼盘', 3: '爆炒禽肉', 4: '胡萝卜厚蛋烧',
        5: '汉堡肉饭', 6: '烤肉狂欢', 7: '能量双拼套餐',
    },
    11: {
        1: '纸张', 2: '记事本', 3: '桌椅', 4: '精选木桶', 5: '文件柜',
    },
    12: {
        1: '炭笔', 2: '铁钉', 3: '电缆', 4: '硫酸', 5: '火药', 6: '刀叉餐具',
    },
    13: {
        1: '墨盒', 2: '钟表', 3: '蓄电池', 4: '净水滤芯',
    },
    14: {
        1: '秋季花束', 2: '花生油', 3: '布料', 4: '皮革', 5: '绳索', 6: '手套',
        7: '香囊', 8: '鞋靴', 9: '绷带',
    },
    15: {
        1: '欧姆蛋', 2: '冰咖啡', 3: '芝士', 4: '拿铁', 5: '柑橘咖啡',
        6: '草莓奶绿', 7: '晨光活力组合', 8: '醒神套餐', 9: '果香双杯乐',
    },
}


__name_to_slot_en = {
    'faircropfields': 4, 'laidbackranch': 4, 'rockheapmine': 4, 'verdantwoods': 4, 'sweetscentorchard': 4, 'newsproutnursery': 2,
    'goldenkoirestaurant': 2, 'polarbearteahouse': 2, 'manjuueatery': 2, "finnfeathergrill": 2, 'lumberprocessing': 2, 'machineryproduction': 2,
    'electronicproduction': 2, 'arts&craftsproduction': 2, 'cafemanjuu': 2
}

__items_data_en = {
    1: {
        1: 'Wheat', 2: 'Corn', 3: 'Grass', 4: 'CoffeeBeans', 5: 'Rice', 6: 'Napa Cabbage',
        7: 'Potato', 8: 'Soy Beans',
    },
    2: {
        1: 'Eggs', 2: 'Fresh Meat', 3: 'Milk', 4: 'Wool',
    },
    3: {
        1: 'Coal', 2: 'Copper Ore', 3: 'Bauxite Ore', 4: 'Iron Ore', 5: 'Sulfur', 6: 'Silver Ore',
    },
    4: {
        1: 'Raw Timber', 2: 'Workable Wood', 3: 'remium Wood', 4: 'Elegant Wood', # remium Wood because it overruns on the left
    },
    5: {
        1: 'Yoizuki Pear', 2: 'Kaki Persimmon', 3: 'Apple', 4: 'Citrus Fruit', 5: 'Banana', 6: 'Mango',
        7: 'Lemon', 8: 'Avocado', 9: 'Rubber',
    },
    6: {
        1: 'Flax', 2: 'Strawberries', 3: 'Cotton', 4: 'Tea Leaves', 5: 'Lavender', 6: 'Carrot',
        7: 'Onion',
    },
    7: {
        1: 'Dried Persimmon', 2: 'Matsutake and Chicken Soup', 3: 'Tofu', 4: 'Tofu with Minced Meat', 5: 'Omurice',
        6: 'Cabbage and Tofu Soup', 7: 'Vegetable Salad', 8: 'Classic Tofu Combo', 9: 'Hearty Meal',
    },
    8: {
        1: 'Carrot and Pear Juice', 2: 'Chrysanthemum Tea', 3: 'Apple Juice', 4: 'Banana and Mango Juice',
        5: 'Honey and Lemon Water', 6: 'Strawberry Lemon Drink', 7: 'Lavender Tea', 8: 'Strawberry Honey Frappe',
        9: 'Floral and Fruity', 10: 'Colorful Fruit Paradise', 11: 'Sunny Honey',
    },
    9: {
        1: 'Corn Cup', 2: 'Apple Pie', 3: 'Orange Pie', 4: 'Sticky Rice with Mango', 5: 'Banana Crepe',
        6: 'Strawberry Charlotte', 7: 'Succulently Sweet', 8: 'Orchard Duo', 9: 'Berry and Orange Dessert',
    },
    10: {
        1: 'Coal-Roasted Skewer', 2: "Chicken and Potato Hors d'Oeuvre", 3: 'Stir-Fried Chicken', 4: 'Rolled Carrot Omelette',
        5: 'Steak Bowl', 6: 'The Carne-val', 7: 'Double Energy Combo',
    },
    11: {
        1: 'Paper', 2: 'Notebook', 3: 'Chair and Desk', 4: 'Choice Wooden Barrel', 5: 'Filing Cabinet',
    },
    12: {
        1: 'Charcoal Brush', 2: 'Cable', 3: 'Nails', 4: 'Chemicals', 5: 'Gunpowder', 6: 'Utensils',
    },
    13: {
        1: 'Ink Cartridge', 2: 'Clock', 3: 'Battery', 4: 'Water Filter',
    },
    14: {
        1: 'Autumn Bouquet', 2: 'Peanut Oil', 3: 'Cloth', 4: 'Leather', 5: 'Rope', 6: 'Gloves',
        7: 'Aroma Sachet', 8: 'Shoes', 9: 'Wound Dressings',
    },
    15: {
        1: 'Omelette', 2: 'Iced Coffee', 3: 'Cheese', 4: 'Latte', 5: 'Citrus Coffee',
        6: 'Strawberry Milkshake', 7: 'Morning Light Energy Combo', 8: 'The Wake-Up Call', 9: 'Fruity & Fruitier',
    },
}


if server.server == 'cn':
    name_to_slot = __name_to_slot_cn
    items_data = __items_data_cn
elif server.server == 'en':
    name_to_slot = __name_to_slot_en
    items_data = __items_data_en
else:
    name_to_slot = __name_to_slot_cn
    items_data = __items_data_cn
