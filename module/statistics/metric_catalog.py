"""统计分类、指标键与字段说明的单一来源。

统计服务的报表结构在这里登记稳定的机器可读键：WebUI 继续只使用中文标签，
MCP 则把键、标签、单位和说明一并返回，调用方不必猜中文名或依赖顺序。

本模块刻意不导入数据库、配置或设备依赖，既能被接口层直接引用，也能在
只读的 MCP 进程里单独导入。
"""

#: 统计分类的固定顺序，与 WebUI 导航顺序一致；overview / flows 不是报表分类。
CATEGORY_ORDER = (
    'overview', 'resources', 'action', 'opsi', 'commission',
    'ships', 'loot', 'research', 'storage', 'flows',
)

CATEGORY_INFO = {
    'overview': {
        'label': '概览资源',
        'description': '概览页资源卡片：资源当前值、上限、总量与最近同步时间，'
                       '另含本月大世界海里数与行动力资产。',
    },
    'resources': {
        'label': '资源趋势',
        'description': '石油、物资、钻石等九项资源的快照时间线；只返回实际写下的点，'
                       '缺失值不补零。',
    },
    'action': {
        'label': '大世界趋势',
        'description': '行动力、行动力资产、海里数、作战补给凭证与特别兑换凭证的时间线。',
    },
    'opsi': {
        'label': '大世界总结',
        'description': '选定月份的战斗、出击、明石遭遇、塞壬研究装置与行动力循环指标，'
                       '附短猫运行统计表。',
    },
    'commission': {
        'label': '委托收益',
        'description': '所选汇总周期内完成的委托数量、各项资源收益与结算明细。',
    },
    'ships': {
        'label': '舰船经验',
        'description': '舰船经验效率、今日进度、每日经验历史与各位置升级进度。',
    },
    'loot': {
        'label': '大世界掉落',
        'description': '大世界任务的金色研发材料、SSR/UR 图纸、实验计划与突破部件掉落，'
                       '含按任务筛选与短猫掉落收益。',
    },
    'research': {
        'label': '科研掉落',
        'description': '科研领奖获得的图纸、彩装，以及心智单元与物资；'
                       '可分查看某一期或心智/物资口径。',
    },
    'storage': {
        'label': '仓库统计',
        'description': '最近一次完整仓库扫描的逐物品数量与时间线；未发现的物品保持 null。',
    },
    'flows': {
        'label': '资源流向',
        'description': '资源管理页的库存、区间收入/支出/调整与逐条流水明细，数据源为资源流水库。',
    },
}

#: 每个分类在报表里使用的表格键；顺序与界面从上到下一致。
CATEGORY_TABLES = {
    'storage': ('storage_items',),
    'opsi': ('meow_runs',),
    'commission': ('commission_rewards', 'commission_records'),
    'ships': ('ship_progress',),
    'research': ('research_rewards', 'research_records'),
    'loot': ('loot_rewards', 'loot_records', 'meow_loot'),
    'flows': ('flows_resources', 'flows_detail', 'flows_entries'),
}

#: 名称随数据变化的指标：键前缀与说明模板。目录里列规则，报表里列实际键。
DYNAMIC_METRICS = {
    'commission': [{'prefix': 'resource:', 'meaning': '委托获得的{名称}总量。'}],
    'research': [{'prefix': 'item:', 'meaning': '{名称} 在统计区间内的累计数量。'}],
    'loot': [{'prefix': 'item:', 'meaning': '{名称} 在统计区间内的累计数量。'}],
}

#: 概览资源卡片与资源流水的资源键说明。
RESOURCE_MEANINGS = {
    'Oil': '石油当前值；limit 为软上限。',
    'Coin': '物资当前值；limit 为软上限。',
    'Gem': '钻石当前值。',
    'Cube': '心智魔方当前值。',
    'Pt': '活动 PT 当前值。',
    'Core': '核心数据当前值。',
    'Medal': '荣誉勋章当前值。',
    'Merit': '功勋当前值。',
    'GuildCoin': '舰队币当前值。',
    'ActionPoint': '行动力当前值；total 为总行动力（含储备）。',
    'YellowCoin': '作战补给凭证当前值。',
    'PurpleCoin': '特别兑换凭证当前值。',
    'Distance': '本月大世界累计海里数。',
    'ActionAsset': '本月行动力资产（行动力与储备折算值）。',
}

#: 每个分类接受哪些业务筛选参数；instance 对所有分类必填，不在此列。
CATEGORY_FILTERS = {
    'overview': (),
    'resources': ('month', 'days', 'period', 'include_series', 'max_points'),
    'action': ('month', 'include_series', 'max_points'),
    'opsi': ('month',),
    'commission': ('month', 'period'),
    'ships': (),
    'loot': ('month', 'period', 'task'),
    'research': ('month', 'period', 'series', 'scope'),
    'storage': ('month', 'days', 'period', 'include_series', 'max_points'),
    'flows': ('days', 'start', 'end', 'resource', 'task', 'offset', 'limit'),
}

FILTER_INFO = {
    'month': {'type': 'string', 'description': '统计月份，YYYY-MM；period=month 时作为汇总窗口。'},
    'days': {'type': 'integer', 'description': '趋势窗口天数（1-365），period=day 时生效。'},
    'period': {'type': 'string', 'description': '汇总周期：day=今天、week=本周、month=选定月份。'},
    'series': {'type': 'integer', 'description': '科研期数（1-9）；0 表示最新有记录的一期。'},
    'scope': {'type': 'string', 'description': '科研口径：series=按期，consumable=心智/物资。'},
    'task': {'type': 'string', 'description': '大世界任务标识（如 opsi_abyssal）或资源流水任务名；空表示全部。'},
    'include_series': {'type': 'boolean', 'description': '是否返回时间线；关闭后响应更小。'},
    'max_points': {'type': 'integer', 'description': '每条时间线最多返回的点数（0=全部），超过时等距抽样。'},
    'start': {'type': 'string', 'description': '资源流水区间起点（本地时间），与 end 成对使用。'},
    'end': {'type': 'string', 'description': '资源流水区间终点（本地时间，不含）。'},
    'resource': {'type': 'string', 'description': '只看某个资源键（如 Oil）；空表示全部。'},
    'offset': {'type': 'integer', 'description': '资源流水明细的起始偏移。'},
    'limit': {'type': 'integer', 'description': '资源流水明细的页大小（1-1000）。'},
}

#: (分类, 指标键) -> 说明。动态指标（item:/resource:）由 metric_meaning 生成。
METRIC_MEANINGS = {
    ('opsi', 'battles'): '选定月份内完成的战斗场次。',
    ('opsi', 'sorties'): '按每 2 场战斗折算的出击轮数（向上取整）。',
    ('opsi', 'action_point_cost'): '出击消耗的行动力，每轮按 5 点计算。',
    ('opsi', 'akashi_encounters'): '明石遭遇次数。',
    ('opsi', 'akashi_encounter_rate'): '明石遭遇次数 ÷ 出击轮数。',
    ('opsi', 'siren_research_devices'): '获得的塞壬研究装置数量。',
    ('opsi', 'siren_research_rate'): '塞壬研究装置数量 ÷ 出击轮数。',
    ('opsi', 'action_point_purchased'): '本月通过明石购买的行动力总量。',
    ('opsi', 'action_point_per_purchase'): '购买行动力 ÷ 明石遭遇次数。',
    ('opsi', 'net_action_point'): '购买行动力 − 出击消耗。',
    ('opsi', 'loop_efficiency'): '净行动力 ÷ 出击消耗，表示行动力循环效率。',
    ('opsi', 'average_battle_time'): '最近战斗的平均耗时（秒）。',
    ('opsi', 'exp_per_hour'): '按平均战斗时长估算的每小时舰船经验。',
    ('opsi', 'today_battles'): '今日完成的战斗场次。',
    ('opsi', 'today_exp'): '今日获得的舰船经验。',
    ('opsi', 'today_runtime_minutes'): '今日累计运行分钟数。',
    ('commission', 'commissions'): '所选汇总周期内完成的委托数量。',
    ('ships', 'target_level'): '舰船经验统计使用的目标等级。',
    ('ships', 'exp_per_hour'): '按平均战斗时长估算的每小时舰船经验。',
    ('ships', 'average_battle_time'): '最近战斗的平均耗时（秒）。',
    ('ships', 'average_round_time'): '最近一轮战斗的平均耗时（秒）。',
    ('ships', 'average_meow_battle_time'): '短猫（大世界侵蚀）战斗的平均耗时（秒）。',
    ('ships', 'today_battles'): '今日完成的战斗场次。',
    ('ships', 'today_exp'): '今日获得的舰船经验。',
    ('ships', 'today_runtime_minutes'): '今日累计运行分钟数。',
    ('research', 'drops'): '统计区间内产生有效科研掉落的记录数。',
    ('research', 'today_total'): '今日获得的统计物品总数。',
    ('research', 'month_total'): '本月获得的统计物品总数。',
    ('research', 'selected_month_total'): '选定月份获得的统计物品总数。',
    ('loot', 'drops'): '统计区间内含统计物品的大世界掉落记录数。',
    ('loot', 'today_total'): '今日获得的统计物品总数。',
    ('loot', 'month_total'): '本月获得的统计物品总数。',
    ('loot', 'selected_month_total'): '选定月份获得的统计物品总数。',
}

#: 时间线键 -> (单位, 说明)。标签由统计服务给出，这里只补充机器可读语义。
SERIES_INFO = {
    'resources': {
        'oil': ('数量', '石油快照值。'),
        'coin': ('数量', '物资快照值。'),
        'gem': ('数量', '钻石快照值。'),
        'pt': ('数量', '活动 PT 快照值。'),
        'cube': ('数量', '心智魔方快照值。'),
        'core': ('数量', '核心数据快照值。'),
        'medal': ('数量', '荣誉勋章快照值。'),
        'merit': ('数量', '功勋快照值。'),
        'guild_coin': ('数量', '舰队币快照值。'),
    },
    'action': {
        'ap': ('行动力', '当前行动力读数；估算来源记为 hazard1_estimate。'),
        'asset': ('行动力', '行动力资产（行动力与储备折算值）。'),
        'distance': ('海里', '大世界本月累计海里数。'),
        'yellow_coins': ('个', '作战补给凭证数量。'),
        'purple_coins': ('个', '特别兑换凭证数量。'),
    },
    'commission': {
        'Gem': ('个', '每次委托结算获得的钻石。'),
        'Cube': ('个', '每次委托结算获得的心智魔方。'),
        'Chip': ('个', '每次委托结算获得的心智单元。'),
        'Oil': ('数量', '每次委托结算获得的石油。'),
        'Coin': ('数量', '每次委托结算获得的物资。'),
    },
    'ships': {
        'total_exp_gained': ('经验', '每日获得的舰船经验。'),
        'battle_count': ('场', '每日完成的战斗场次。'),
        'total_run_time': ('秒', '每日累计运行秒数。'),
    },
    'storage': {},
}

#: 表格键 -> 标题、说明与列（键, 中文列名, 说明）。中文列名用于文档，报表里的
#: columns 才是界面真实列名；column_keys 与 columns 一一对应。
TABLE_INFO = {
    'storage_items': {
        'title': '仓库物品',
        'meaning': '最近一次完整仓库扫描的逐物品数量；未发现的物品为 null，不当作 0。',
        'columns': (
            ('icon', '图标', '物品图标标识。'),
            ('item', '物品', '物品中文名。'),
            ('group', '分类', '物品分类。'),
            ('amount', '数量', '扫描确认的数量；null 表示未发现或未扫描。'),
            ('status', '状态', '未扫描 / 已复核 / 未发现。'),
        ),
    },
    'meow_runs': {
        'title': '短猫运行统计',
        'meaning': '按侵蚀等级统计的短猫运行效率与装置获取率。',
        'columns': (
            ('hazard', '侵蚀等级', '侵蚀等级（3 或 5）。'),
            ('battles', '战斗次数', '该等级的累计战斗场次。'),
            ('effective_rounds', '有效轮数', '计入统计的有效轮数。'),
            ('avg_battle_seconds', '平均战斗秒数', '平均每场战斗耗时（秒）。'),
            ('avg_round_seconds', '平均每轮秒数', '平均每轮耗时（秒）。'),
            ('research_devices', '研究装置', '获得的研究装置数量。'),
            ('research_rate', '获取率（%）', '研究装置获取率，百分比数值。'),
            ('source', '统计来源', '实测 / 估算 / 暂无记录。'),
        ),
    },
    'commission_rewards': {
        'title': '委托收益明细',
        'meaning': '按资源汇总的委托收益。',
        'columns': (
            ('resource', '资源', '资源名称。'),
            ('total', '总收益', '区间内该资源的总收益。'),
            ('records', '掉落记录数', '产生该资源收益的结算记录数。'),
            ('average', '平均每次掉落', '总收益 ÷ 掉落记录数。'),
        ),
    },
    'commission_records': {
        'title': '委托结算记录',
        'meaning': '每次委托结算的明细，按时间倒序。',
        'columns': (
            ('time', '时间', '结算时间（本地时间）。'),
            ('count', '委托数量', '本次结算完成的委托数量。'),
            ('gem', '钻石', '本次获得的钻石。'),
            ('cube', '魔方', '本次获得的心智魔方。'),
            ('chip', '心智单元', '本次获得的心智单元。'),
            ('oil', '石油', '本次获得的石油。'),
            ('coin', '物资', '本次获得的物资。'),
        ),
    },
    'ship_progress': {
        'title': '舰船升级进度',
        'meaning': '各位置舰船的等级、经验与预计战斗数；经验值以最近一次检测为基准。',
        'columns': (
            ('position', '位置', '舰队位置。'),
            ('level', '等级', '当前等级。'),
            ('current_exp', '当前经验', '当前等级内的经验。'),
            ('total_exp', '累计经验', '累计经验。'),
            ('target_exp', '目标经验', '达到目标等级所需经验。'),
            ('battles_done', '检测后战斗数', '上次检测后完成的战斗数。'),
            ('exp_needed', '还需经验', '距目标等级还差的经验。'),
            ('battles_needed', '还需战斗', '按平均每场经验估算的剩余战斗数。'),
            ('time_needed', '预估用时', '按平均战斗时长估算的剩余时间。'),
        ),
    },
    'research_rewards': {
        'title': '科研收获明细',
        'meaning': '按物品汇总的科研掉落；没掉过的物品也保留一行并显示 null。',
        'columns': (
            ('icon', '图标', '物品图标标识，形如 research:<模板名>。'),
            ('item', '物品', '物品中文名。'),
            ('rarity', '稀有度', '物品稀有度。'),
            ('total', '总收益', '区间内该物品的累计数量。'),
            ('records', '掉落记录数', '产生该物品的掉落记录数。'),
            ('average', '平均每次掉落', '总收益 ÷ 掉落记录数。'),
        ),
    },
    'research_records': {
        'title': '科研掉落记录',
        'meaning': '产生有效科研掉落的原始记录，按时间倒序，最多 200 条。',
        'columns': (
            ('time', '时间', '掉落时间（本地时间）。'),
            ('project', '项目', '科研项目名称。'),
            ('series', '期数', '科研期数。'),
            ('drops', '掉落物', '本次掉落的物品与数量，顿号分隔。'),
        ),
    },
    'loot_rewards': {
        'title': '大世界掉落明细',
        'meaning': '按物品汇总的大世界掉落；只统计页面列出的统计物品。',
        'columns': (
            ('icon', '图标', '物品图标标识，形如 opsi:<模板名>。'),
            ('item', '物品', '物品中文名。'),
            ('rarity', '稀有度', '物品稀有度。'),
            ('total', '总收益', '区间内该物品的累计数量。'),
            ('records', '掉落记录数', '产生该物品的掉落记录数。'),
            ('average', '平均每次掉落', '总收益 ÷ 掉落记录数。'),
        ),
    },
    'loot_records': {
        'title': '大世界掉落记录',
        'meaning': '含统计物品的大世界掉落原始记录，按时间倒序，最多 200 条。',
        'columns': (
            ('time', '时间', '掉落时间（本地时间）。'),
            ('task', '任务', '产生掉落的大世界任务。'),
            ('area', '海域', '掉落所在海域。'),
            ('drops', '掉落物', '本次掉落的物品与数量，顿号分隔。'),
        ),
    },
    'meow_loot': {
        'title': '短猫掉落收益',
        'meaning': '按侵蚀等级统计的短猫掉落收益；沿用本地缓存的旧口径。',
        'columns': (
            ('hazard', '侵蚀等级', '侵蚀等级。'),
            ('last_record', '上次记录时间', '该等级最近一次记录时间。'),
            ('effective_rounds', '有效战斗轮数', '计入统计的有效轮数。'),
            ('coins_per_round', '平均黄币/轮', '每轮平均获得的作战补给凭证。'),
            ('parts_per_round', '平均金菜/轮', '每轮平均获得的部件。'),
            ('abyssal_per_round', '平均深渊/轮', '每轮平均深渊收益。'),
            ('secret_per_round', '平均隐秘/轮', '每轮平均隐秘海域收益。'),
        ),
    },
    'flows_resources': {
        'title': '资源库存与区间收支',
        'meaning': '资源管理页的库存与区间收支汇总；未知模板按物品归入「物品」分类。',
        'columns': (
            ('resource', '资源', '资源键。'),
            ('group', '分类', '货币 / 材料 / 物品。'),
            ('current', '当前库存', '最近一次余额记录；null 表示尚未观测。'),
            ('income', '区间收入', '区间内正流水合计，不含手工调整。'),
            ('expense', '区间支出', '区间内负流水合计，不含手工调整。'),
            ('adjustment', '调整', '手工调整量。'),
            ('records', '记录数', '区间内该资源的流水条数。'),
            ('observed_at', '库存观测时间', '当前库存对应的时间。'),
        ),
    },
    'flows_detail': {
        'title': '资源流向汇总',
        'meaning': '按资源、任务、操作与证据类型汇总的区间收支。',
        'columns': (
            ('resource', '资源', '资源键。'),
            ('task', '任务', '产生流水的任务。'),
            ('operation', '操作', '产生流水的操作。'),
            ('evidence', '证据', '流水来源证据类型。'),
            ('income', '收入', '该组合的正流水合计。'),
            ('expense', '支出', '该组合的负流水合计。'),
            ('records', '记录数', '该组合的流水条数。'),
        ),
    },
    'flows_entries': {
        'title': '资源流水明细',
        'meaning': '区间内逐条资源流水，按时间倒序分页。',
        'columns': (
            ('time', '时间', '流水时间（本地时间）。'),
            ('resource', '资源', '资源键。'),
            ('amount', '数量', '正数为收入，负数为支出。'),
            ('task', '任务', '产生流水的任务。'),
            ('operation', '操作', '产生流水的操作。'),
            ('evidence', '证据', '流水来源证据类型。'),
            ('run_id', '运行标识', '产生流水的运行轮次标识。'),
        ),
    },
}

#: 概览/资源流向共用的 resources 数组字段说明。
RESOURCE_FIELDS = {
    'key': '资源标识，与 WebUI 资源卡片或资源流水键一致。',
    'label': '资源显示名。',
    'value': '概览卡片的资源当前值；未同步时为 null。',
    'limit': '资源上限；无上限时为 null。',
    'total': '资源总量（如总行动力）；不适用时为 null。',
    'record': '概览卡片最近同步时间；未同步时为 null。',
    'observed': '是否已同步到有效值（record 晚于 2020-01-01 且 value 非空）。',
    'group': '资源分类（资源流向：货币/材料/物品）。',
    'income': '区间收入合计（资源流向）。',
    'expense': '区间支出合计（资源流向）。',
    'adjustment': '手工调整量（资源流向）。',
    'records': '区间流水条数（资源流向）。',
    'observed_at': '当前库存的观测时间（资源流向）。',
    'meaning': '该资源在本分类里的口径说明。',
}

STATE_INFO = {
    'ready': '有可用数据；metrics、series、tables 至少一项非空。',
    'empty': '查询成功，但所选区间没有记录；hint 说明如何扩大范围或触发统计。',
    'loading': '统计任务正在运行，当前返回的是已有快照；完成后可重试。',
}

ERROR_INFO = {
    'STATISTICS_UNAVAILABLE': ('统计库不可读或尚未初始化，无法生成报表。', False),
    'STATISTICS_LOADING': ('统计库正被写入或初始化，暂时无法读取；稍后重试。', True),
    'PERMISSION_DENIED': ('没有读取统计库或配置目录的权限。', False),
    'INVALID_PARAMS': ('月份、区间或筛选参数不合法；按 details 修正后重试。', False),
    'NOT_FOUND': ('实例或统计分类不存在；先用 list_instances 确认实例。', False),
    'TOOL_BUSY': ('工具执行槽已满，稍后重试。', True),
    'TOOL_TIMEOUT': ('查询超时，统计可能仍在计算；稍后重试。', True),
}


def metric_meaning(category: str, key: str, label: str = '') -> str:
    """返回指标键对应的中文说明；动态物品/资源指标按名称生成。"""
    if key.startswith('item:'):
        name = label or key[5:]
        return f'{name} 在统计区间内的累计数量。'
    if key.startswith('resource:'):
        name = label or key[9:]
        return f'委托获得的{name}总量。'
    return METRIC_MEANINGS.get((category, key), '')


def series_info(category: str, key: str) -> tuple:
    """返回时间线键对应的 (单位, 说明)；未知键返回空语义而不是报错。"""
    info = (SERIES_INFO.get(category) or {}).get(key)
    if info:
        return info
    return '', ''


def table_header(key: str) -> dict:
    """生成表格的机器可读表头：键与中文列名、说明一一对应。"""
    info = TABLE_INFO.get(key) or {}
    columns = info.get('columns') or ()
    return {
        'keys': [item[0] for item in columns],
        'labels': [item[1] for item in columns],
        'meanings': [item[2] for item in columns],
    }
