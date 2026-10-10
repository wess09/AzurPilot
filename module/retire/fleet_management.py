"""舰队管理扫描任务。"""

from module.base.timer import Timer
from module.config.time_source import now as current_time
from module.logger import logger
from module.retire.dock import Dock
from module.retire.fleet_emotion import learn_fleet_emotion, screenshot_window
from module.retire.scanner import FleetManagementScanner
from module.ui.page import page_dock


class FleetManagement(Dock):
    """扫描船坞内已编入舰队的舰船，并持久化舰队信息。"""

    SCAN_CATEGORIES = {
        "vanguard": "vanguard",
        "main": "main",
        "submarine": "ss",
    }
    RESULT_PATH = "FleetInfo.FleetInfo.Result"
    RECORD_PATH = "FleetInfo.FleetInfo.Record"
    FILTER_LOADING_DELAY = 0.2

    @staticmethod
    def _normalize_result(result):
        """将舰队编号规范化为 JSON 对象可用的字符串键。

        Args:
            result (dict): 扫描器返回的舰队舰船字典，键为舰队编号，值为舰船属性字典列表。

        Returns:
            dict: 规范化后的字典，键为字符串类型的舰队编号。
        """
        return {
            str(fleet): [
                {
                    'name': str(ship.get('name', '')),
                    'level': int(ship.get('level', 0)),
                    'emotion': ship.get('emotion'),
                }
                for ship in names
            ]
            for fleet, names in result.items()
        }

    def _save_result(self, result) -> None:
        """一次性保存全部扫描结果，避免留下不完整的分类数据。

        Args:
            result (dict): 包含各分类舰队舰船信息的最终结果字典。
        """
        self.config.modified[self.RESULT_PATH] = result
        self.config.modified[self.RECORD_PATH] = current_time().replace(microsecond=0)
        self.config.save()

    def _wait_dock_filter_loaded(self) -> None:
        """等待筛选后的船坞卡片开始加载并确认画面稳定。"""
        timer = Timer(self.FILTER_LOADING_DELAY).start()
        while not timer.reached():
            self.device.screenshot()
        self.handle_dock_cards_loading()

    def run(self) -> None:
        """执行一次舰队扫描。

        Pages:
            in: Any
            out: page_dock
        """
        logger.hr("舰队扫描", level=0)
        self.ui_ensure(page_dock)
        scanner = FleetManagementScanner()
        result = {}
        windows = {}
        reset_first = self.dock_filter.reset_first

        try:
            # 所有筛选条件已显式指定；避免后续分类先重置排序为等级。
            self.dock_filter.reset_first = False
            self.dock_favourite_set(False, wait_loading=False)
            self.dock_sort_method_dsc_set(False, wait_loading=False)
            for category, index in self.SCAN_CATEGORIES.items():
                logger.hr(f"舰队扫描-{category}", level=1)
                self.dock_filter_set(
                    sort="mood" if category == "vanguard" else None,
                    index=index,
                    faction="all",
                    rarity="all",
                    extra="no_limit",
                    wait_loading=False,
                    reset_index=True,
                )
                self._wait_dock_filter_loaded()
                if category != 'submarine':
                    windows[category] = screenshot_window(self.device)
                result[category] = self._normalize_result(scanner.scan(self.device.image))

            learn_fleet_emotion(self.config, result, windows, set(scanner.name_scanner.name_matcher.names))
            self._save_result(result)
        finally:
            self.dock_filter.reset_first = reset_first
            # 扫描结束后恢复船坞默认筛选和排序状态。
            self.dock_reset()
