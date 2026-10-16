"""舰船科技的独立扫描任务；仅复用船坞定位与滚动，不套用心智身份和计费筛选。"""
import copy
from datetime import datetime

import module.config.server as server
from module.base.timer import Timer
from module.config.deep import deep_get, deep_set
from module.config.transaction import config_transaction
from module.config.utils import filepath_config
from module.exception import MindCalculatorScanError
from module.logger import logger
from module.retire.assets import DOCK_EMPTY, DOCK_SEARCH_ACTIVE, DOCK_SEARCH_CLOSED
from module.retire.dock import DOCK_SCROLL
from module.retire.mind_scan import MindCalculatorScan
from module.runtime import fleet_tech as tech
from module.runtime.fleet_tech_identity import FleetTechIdentity
from module.runtime.mind_recognition import ScanMerger, ScanPolicy, recognize_cards
from module.runtime.scan_metrics import CachedOcr, ScanMetrics


class FleetTechScan(MindCalculatorScan):
    evidence_folder = 'fleet_tech_scan'
    scan_label = '舰船科技'

    def _make_merger(self):
        return ScanMerger(group_identity=True)

    def _read_cards(self, image, source, names, levels):
        return recognize_cards(image, source, name_ocr=names, level_ocr=levels, identity=self._identity, metrics=getattr(self, '_metrics', None))

    def _restricted_identity(self, nationalities):
        return FleetTechIdentity([row for row in tech.catalog()['ships'] if row['nationality'] in nationalities])

    def _close_search(self):
        """以已关闭搜索按钮确认恢复，不能把带关键词的船坞视为完整范围。

        Pages:
            in: page_dock
            out: page_dock
        """
        timeout = Timer(20).start()
        while True:
            self.device.screenshot()
            if self.appear(DOCK_SEARCH_CLOSED):
                return
            if timeout.reached():
                raise MindCalculatorScanError('未能确认船坞搜索已关闭，保留原科技记录')
            if self.appear_then_click(DOCK_SEARCH_ACTIVE, interval=2):
                continue
            if self.handle_popup_confirm():
                continue

    def run(self):
        """范围扫描只更新正向证据；满足完整无过滤扫描证明时才记录缺失。

        Pages:
            in: Any
            out: page_dock
        """
        if server.server != 'cn':
            raise MindCalculatorScanError('舰船科技自动扫描当前仅支持国服')
        from module.ocr.al_ocr import AlOcr
        from module.runtime.scan_dock_amount import SCAN_DOCK_AMOUNT
        logger.hr('舰船科技船坞扫描', level=0)
        try:
            self._policy = ScanPolicy(self.config.FleetTech_MinLevel, self.config.FleetTech_MaxLevel, sorted_desc=True)
        except ValueError as exc:
            raise MindCalculatorScanError(str(exc)) from exc
        try:
            self._identity = FleetTechIdentity()
        except (MemoryError, ValueError, KeyError, OSError) as exc:
            raise MindCalculatorScanError(f'舰船目录初始化失败，保留旧科技记录：{type(exc).__name__}') from exc
        self._scan_evidence_paths = set()
        self._metrics = ScanMetrics()
        self._scan_metadata = dict(reached_bottom=False, physical_count=0)
        logger.attr('科技扫描等级范围', f'{self._policy.min_level}–{self._policy.max_level}（含边界）')
        # 收起搜索框不会清除关键词；重建船坞场景，才能清空隐藏搜索条件。
        self._enter_scan_dock()
        self.dock_reset()
        self.dock_sort_method_dsc_set(True)
        try:
            expected_count, remaining, capacity = SCAN_DOCK_AMOUNT.ocr(self.device.image)
        except (MemoryError, RuntimeError, ValueError) as exc:
            raise MindCalculatorScanError('船坞数量读取失败，保留原科技记录') from exc
        if (capacity <= 0 or not 0 <= expected_count <= capacity or remaining + expected_count != capacity):
            expected_count = None
            logger.warning('船坞数量未确认，本轮不能据缺失清空已有记录')
        logger.attr('船坞舰船数量', expected_count)
        if self.appear(DOCK_EMPTY):
            ships = []
            self._scan_metadata['reached_bottom'] = True
        else:
            DOCK_SCROLL.set_top(self)
            if not DOCK_SCROLL.appear(self) or not (DOCK_SCROLL.at_top(self) or DOCK_SCROLL.length == DOCK_SCROLL.total):
                raise MindCalculatorScanError('未能确认船坞顶部，保留原科技记录')
            try:
                names = AlOcr(config=self.config, name='ppocr_v6', save_debug_images=False)
                levels = AlOcr(config=self.config, name='azur_lane', save_debug_images=False)
                names, levels = CachedOcr(names, self._metrics, 'name_ocr'), CachedOcr(levels, self._metrics, 'level_ocr')
                ships = self._scan_pages(names, levels)
                ships = self._resolve_group_reviews(ships, names, levels)
            except (MemoryError, RuntimeError) as exc:
                raise MindCalculatorScanError(f'扫描识别引擎失败，已保留原科技记录：{exc}') from exc
        if not self.appear(DOCK_SEARCH_CLOSED):
            raise MindCalculatorScanError('扫描结束时搜索状态发生变化，保留原科技记录')
        # 复读最新人工记录；扫描只修改自动证据，不覆盖期间的校正。
        with self._metrics.measure('save'), config_transaction(filepath_config(self.config.config_name)):
            latest = self.config.read_file(self.config.config_name)
            record = tech.read_record(latest)
            merged = tech.merge_scan(record, ships, min_level=self._policy.min_level,
                                     max_level=self._policy.max_level, filters_clear=True,
                                     expected_count=expected_count, updated_at=datetime.now().isoformat(timespec='seconds'),
                                     **self._scan_metadata)
            if hasattr(self.config, '_loaded_data'):
                deep_set(self.config._loaded_data, tech.RECORD_PATH,
                         copy.deepcopy(deep_get(latest, tech.RECORD_PATH, {})))
            self.config.modified[tech.RECORD_PATH] = merged
            self.config.save()
        self._prune_scan_evidence()
        import json
        logger.attr('扫描阶段基准', json.dumps(self._metrics.snapshot(), ensure_ascii=False))
        scan = merged['last_scan']
        logger.attr('科技扫描结果摘要', scan['fingerprint'])
        logger.info(f'[舰船科技] 已保存 {scan["matched_count"]} 个群组，待核对 {scan["review_count"]} 条；'
                    f'完整无过滤扫描：{scan["complete"]}')
