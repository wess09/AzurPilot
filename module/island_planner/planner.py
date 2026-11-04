"""岛屿生产规划器（工具页任务）。

思路与算法来自 AzurLaneAutoScript（LmeSzinc/AzurLaneAutoScript，GPL-3.0）的
IslandProductionPlanner：扫描岛屿科技，用线性规划求出每日生产/出售方案，
在每日岛币净收入不低于下限的前提下最大化季节 PT。AzurPilot 版只做「计算器」：
把方案写进 AzurPilot 已有的岛屿配置（店铺后厨、商区、农田作物目标），
实际生产仍由 AzurPilot 自己的岛屿任务执行。
"""
import module.config.server as server
from module.base.decorator import cached_property
from module.config.deep import deep_get
from module.config.utils import filepath_args, read_file
from module.island_planner import settings_map
from module.island.assets import ISLAND_BACK
from module.island_planner.calculator import ProductionPlanCalculator
from module.island_planner.cargo import partial_order_targets, partial_orders_fully_read, read_cargo_slots
from module.island_planner.data import DIC_ISLAND_ITEM
from module.island_planner.scanner import IslandTechnologyScanner
from module.island_planner.priorities import solve_with_priorities
from module.island_planner.season_tasks import IslandSeasonTaskScanner
from module.island_planner.utils import (
    get_current_activity_list,
    get_current_season_remaining_days,
    item_mapping_to_yaml,
    load_item_mapping,
    load_technology_status,
    normalize_item_id,
)
from module.logger import logger
from module.ui.page import page_island, page_island_phone

TASK = 'IslandProductionPlanner'
TECHNOLOGY_STORAGE = f'{TASK}.Storage.Storage.IslandTechnologyStatus'
GRADE_KEYS = {
    601: 'RestaurantGrade',
    602: 'TeahouseGrade',
    603: 'JuuEateryGrade',
    604: 'GrillGrade',
    901: 'JuuCoffeeGrade',
}


def efficiency_rate(value):
    """效率加成配置转成比例。

    配置以整数百分比保存（0/4/12）：WebUI 用「.」分隔翻译键，0.04 这类小数选项会被拆开，
    无法正常选择。早期保存的小数（0.04）与无法解析的值也兼容处理。
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        logger.warning(f'[岛屿-规划] 效率加成无法识别: {value}，按 0 处理')
        return 0.
    return value / 100 if value >= 1 else max(value, 0.)


def resolve_item(key):
    """物品名或 ID 转物品 ID。同名物品（如两个 Corn）优先取可以生产的那个。"""
    if isinstance(key, str) and not key.strip().isdigit() and '(' not in key:
        for language in dict.fromkeys((server.server, 'en')):
            matches = [item_id for item_id, item in DIC_ISLAND_ITEM.items()
                       if item['name'].get(language) == key.strip()]
            if matches:
                produced = [item_id for item_id in matches
                            if item_id in ProductionPlanCalculator.RECIPE_PRODUCT_IDS]
                return (produced or matches)[0]
    return normalize_item_id(key)


def parse_targets(text, name):
    """解析目标文本（YAML 映射，键为物品英文名或 ID）。

    值可以是数量（期限默认为本季剩余天数）、`{count: 数量, period: 天数}`，或这些的列表。
    无法识别的物品记录警告后跳过，不影响其他条目。

    Returns:
        dict[int, list]: {物品ID: [单条需求, ...]}，供 merge_targets 合并。
    """
    try:
        mapping = load_item_mapping(text, config_name=name)
    except Exception as e:
        logger.warning(f'[岛屿-规划] {name} 格式错误，已忽略: {e}')
        return {}
    targets = {}
    for key, value in mapping.items():
        try:
            item_id = resolve_item(key)
        except ValueError as e:
            logger.warning(f'[岛屿-规划] {name}: {e}，已忽略')
            continue
        entries = value if isinstance(value, list) else [value]
        targets.setdefault(item_id, []).extend(entries)
    return targets


def with_period(targets, days):
    """给未写期限的目标加上统一期限（天）。货运缺口需要尽快补齐，不按季节剩余天数平均。"""
    try:
        days = float(days)
    except (TypeError, ValueError):
        days = 1.
    days = days if days > 0 else 1.
    return {
        item_id: [entry if isinstance(entry, dict) else {'count': entry, 'period': days} for entry in entries]
        for item_id, entries in targets.items()
    }


def merge_targets(*target_maps):
    """合并多份目标。每条需求独立计入（同一物品的数量相加），
    交给 calculator 的 normalize_item_needs 按期限换算成每日速率。"""
    merged = {}
    for targets in target_maps:
        for item_id, entries in targets.items():
            merged.setdefault(item_id, []).extend(entries)
    return merged


class IslandProductionPlanner(IslandSeasonTaskScanner, IslandTechnologyScanner):
    """
    Pages:
        in: 任意页面（需要扫描科技时）
        out: page_island_technology（扫描时），否则不操作游戏
    """

    def get(self, key):
        return getattr(self.config, f'{TASK}_{key}')

    @cached_property
    def args(self):
        return read_file(filepath_args())

    def options(self, task, group, key):
        """配置项的可选值（去掉 None），用于限定规划只用 AzurPilot 支持的菜品。"""
        return [name for name in deep_get(self.args, [task, group, key, 'option'], default=[]) if name != 'None']

    def load_technology(self):
        """读取已保存的科技状态；没有保存或要求重新扫描时扫描游戏。

        Returns:
            dict[int, bool]: {科技ID: 是否解锁}。
        """
        saved = self.config.cross_get(TECHNOLOGY_STORAGE, None)
        if saved and not self.get('RescanTechnology'):
            logger.info('[岛屿-规划] 使用已保存的岛屿科技状态')
            return load_technology_status(saved)

        logger.hr('Scan island technology', level=1)
        status = self.get_technology_status()
        unlocked = sum(1 for value in status.values() if value)
        logger.info(f'[岛屿-规划] 科技扫描完成：已解锁 {unlocked}/{len(status)}')
        with self.config.multi_set():
            # 键转成字符串保存，load_technology_status 读回时转成 int
            self.config.cross_set(TECHNOLOGY_STORAGE, {str(key): value for key, value in status.items()})
            self.config.cross_set(f'{TASK}.{TASK}.RescanTechnology', False)
        return status

    def load_targets(self):
        """季节任务目标（可扫描更新）与手动额外目标。

        ALAS 的「卡住的季节订单」由其订单任务自动记录；AzurPilot 不处理季节订单，
        需要为订单备货时把物品写进 ExtraTargets。
        """
        targets = self.scan_season_task_targets() if self.get('ScanSeasonTasks') else None
        if targets is not None:
            text = item_mapping_to_yaml(targets, use_item_name=True) if targets else ''
            # 扫描结果属于规划器自己的输入，预览模式也保存，便于查看和手动修改
            self.config.cross_set(f'{TASK}.{TASK}.SeasonTaskTargets', text)
        else:
            # 未扫描或扫描失败（识别不到任务卡片）时沿用上次保存的目标
            text = self.get('SeasonTaskTargets')
        season = parse_targets(text, 'SeasonTaskTargets')
        if self.get('ScanCargoOrders'):
            missing = self.scan_cargo_targets()
        else:
            missing = None
        if missing is not None:
            cargo_text = item_mapping_to_yaml(missing, use_item_name=True) if missing else ''
            self.config.cross_set(f'{TASK}.{TASK}.CargoTargets', cargo_text)
        else:
            # 未扫描或扫描不完整时沿用上次保存的目标
            cargo_text = self.get('CargoTargets')
        cargo = with_period(parse_targets(cargo_text, 'CargoTargets'), self.get('CargoTargetDays'))
        extra = parse_targets(self.get('ExtraTargets'), 'ExtraTargets')
        for name, targets in (('季节任务目标', season), ('货运缺口', cargo), ('额外目标', extra)):
            if targets:
                logger.info(f'[岛屿-规划] {name}: {targets}')
        return merge_targets(season, cargo, extra)

    def scan_cargo_targets(self):
        """读取货运页面，返回已部分提交的委托还缺的货物 {物品ID: 数量}。

        Returns:
            dict[int, int] | None: 缺口；已部分提交的委托有格子识别失败时返回 None，
                调用方沿用已保存的目标，避免用不完整的结果清空缺口。

        Pages:
            in: 任意页面
            out: page_island_phone
        """
        logger.hr('Scan island cargo orders', level=1)
        self.ui_ensure(page_island)
        self.ui_goto(page_island_phone, get_ship=False)
        self.island_transport_enter()
        # island_transport_enter 只确认了页面模板，已提交标记和货物格数字可能还没显示；
        # 连续两次截图读到相同且完整的结果才采用，最多 5 秒，否则沿用已保存的目标
        slots, previous, settled = [], None, False
        for _ in self.loop(skip_first=False, timeout=5):
            slots = read_cargo_slots(self.device.image)
            if slots == previous and partial_orders_fully_read(slots):
                settled = True
                break
            previous = slots
        for index, slot in enumerate(slots):
            items = ', '.join(f'{DIC_ISLAND_ITEM[i]["name"]["en"]} {stock}/{need}' for i, stock, need in slot['items'])
            logger.info(f'[岛屿-货运] 栏位 {index + 1}: 已提交 {slot["completed"]} 格; {items}')
        if settled:
            missing = partial_order_targets(slots)
            logger.info(f'[岛屿-货运] 已部分提交委托的缺口: {missing}')
        else:
            missing = None
            logger.warning('[岛屿-货运] 货运页在 5 秒内未读到稳定完整的结果，沿用上次保存的货运目标')
        for _ in self.loop(timeout=30):
            if self.ui_page_appear(page_island_phone):
                break
            if self.appear_then_click(ISLAND_BACK, interval=2):
                continue
            if self.ui_additional():
                continue
        return missing

    def create_calculator(self, technology_status):
        grades = {rid: self.get(key) for rid, key in GRADE_KEYS.items()}
        chars = {
            rid: (getattr(self.config, f'{kitchen["business"]}_Char1', None),
                  getattr(self.config, f'{kitchen["business"]}_Char2', None))
            for rid, kitchen in settings_map.KITCHENS.items()
        }
        open_ids = settings_map.open_restaurants(
            getattr(self.config, 'IslandBusiness_BatchEnabled', True),
            getattr(self.config, 'IslandBusiness_Batch1Shops', []),
            getattr(self.config, 'IslandBusiness_Batch2Shops', []),
        )
        return ProductionPlanCalculator(
            technology_status=technology_status,
            activity_list=get_current_activity_list(),
            place_efficiency={
                101: efficiency_rate(self.get('FieldsEfficiency')),
                501: efficiency_rate(self.get('OrchardEfficiency')),
                502: efficiency_rate(self.get('NurseryEfficiency')),
            },
            restaurant_settings=settings_map.restaurant_settings(grades, chars, open_ids),
            daily_profit_lower_limit=self.get('DailyProfitLowerLimit'),
            daily_buffer_safety_margin=self.get('DailyBufferSafetyMargin'),
            slot_limit=settings_map.position_limits(lambda path: self.config.cross_get(path, None)),
        )

    def run(self):
        logger.hr('Island production planner', level=1)
        technology_status = self.load_technology()
        targets = self.load_targets()
        calculator = self.create_calculator(technology_status)

        meal_options = {
            rid: self.options(kitchen['task'], kitchen['task'], 'Meal1')
            for rid, kitchen in settings_map.KITCHENS.items()
        }
        product_options = {
            rid: self.options(settings_map.BUSINESS_TASK, kitchen['business'], 'Product1')
            for rid, kitchen in settings_map.KITCHENS.items()
        }
        excluded = settings_map.restrict_calculator(calculator, meal_options, product_options)
        if excluded:
            logger.info(f'[岛屿-规划] AzurPilot 不支持、已排除的配方: {", ".join(excluded)}')

        remaining = get_current_season_remaining_days()
        if remaining is not None:
            logger.info(f'[岛屿-规划] 本季剩余 {remaining:.1f} 天')
        elif targets:
            # 没有进行中的季节时目标没有默认期限，按 1 天处理，避免整体求解失败
            logger.warning('[岛屿-规划] 没有进行中的季节，未写期限的目标按 1 天计算')
            remaining = 1
        # 目标物品当前无法生产时由 calculator 记录警告后忽略，不影响其他物品
        # 目标 → 季节 PT → 岛币：先满足目标与岛币下限并最大化 PT，再保持 PT 最大化岛币
        solve_with_priorities(calculator, task_target_items=targets, task_target_period=remaining)
        calculator.print_solved_production_plan()
        if not calculator.lp_success:
            logger.warning('[岛屿-规划] 没有可行方案，配置未修改。可降低「每日岛币净收入下限」后重试')
            return False

        values, notes = settings_map.build_settings(calculator, meal_options, product_options)
        for note in notes:
            logger.info(f'[岛屿-规划] {note}')
        changed = {path: value for path, value in values.items() if self.config.cross_get(path) != value}
        logger.hr('Planned settings', level=2)
        for path, value in values.items():
            mark = '*' if path in changed else ' '
            text = str(value).replace('\n', ', ')
            logger.info(f'{mark} {path} = {text}')

        if not self.get('ApplySettings'):
            logger.info(f'[岛屿-规划] 预览模式：{len(changed)} 项配置会改变，未写入。勾选「写入配置」后再次运行即可应用')
            return True
        with self.config.multi_set():
            self.config.cross_set_many(changed)
        logger.info(f'[岛屿-规划] 已写入 {len(changed)} 项配置')
        return True
