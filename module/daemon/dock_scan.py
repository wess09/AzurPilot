from module.daemon.daemon_base import DaemonBase
from module.daemon.dock_scan_postprocess import process_dock_scan_result
from module.logger import logger
from module.retire.dock import Dock
from module.retire.scanner import DockScanner
from module.ui.page import page_dock
from pathlib import Path


class DockScanTask(DaemonBase, Dock):
    """
    Task: DockScan
    Dock scanning daemon - scans all ships in dock and displays statistics.
    """

    def run(self):
        """
        Pages:
            in: page_dock
            out: page_dock
        """
        logger.hr('Dock Scan', level=1)
        logger.info(f'Output files will be saved under: {Path(".").resolve()}')

        try:
            # Ensure we are on dock page
            self.ui_ensure(page_dock)

            # Create scanner and perform full dock scan
            logger.hr('Scanning Dock', level=2)
            scanner = DockScanner()
            ships = scanner.scan_whole_dock(self)

            # Display statistics
            logger.hr('Scan Results', level=2)
            logger.info(f'Total ships scanned: {len(ships)}')

            if not ships:
                logger.warning('No ships found in dock')
                return True

            # Statistics by rarity and name
            rarity_stat = {}
            level_stat = {}
            ship_list = []

            for ship in ships:
                # Count by rarity
                rarity = ship.rarity or 'Unknown'
                rarity_stat[rarity] = rarity_stat.get(rarity, 0) + 1

                # Count by level ranges
                level = ship.level or 0
                level_range = f'{(level // 10) * 10}-{(level // 10 + 1) * 10 - 1}'
                level_stat[level_range] = level_stat.get(level_range, 0) + 1
                
                # Collect ship info for detailed list
                ship_name = ship.name if ship.name else 'Unknown'
                ship_list.append(f'{ship_name:<15} Lv.{level:<3} Rarity: {rarity}')

            logger.hr('Rarity Distribution', level=3)
            for rarity in sorted(rarity_stat.keys()):
                logger.attr(rarity, rarity_stat[rarity])

            logger.hr('Level Distribution', level=3)
            for level_range in sorted(level_stat.keys()):
                logger.attr(level_range, level_stat[level_range])

            logger.hr('Ship List', level=3)
            for ship_info in ship_list:
                logger.info(ship_info)

            # 自动后处理：导出CSV并执行符号清理 + wiki名称匹配
            if self.config.DockScan_PostProcess:
                logger.hr('Post Process', level=2)
                artifacts = process_dock_scan_result(ships)
                logger.attr('Raw CSV', artifacts.get('raw_csv', ''))
                logger.attr('Cleaned CSV', artifacts.get('cleaned_csv', ''))
                logger.attr('Matched CSV', artifacts.get('matched_csv', ''))
                logger.attr('Unresolved CSV', artifacts.get('unresolved_csv', ''))
                logger.attr('Match Report CSV', artifacts.get('report_csv', ''))
            else:
                logger.info('Post process disabled by config')

            logger.info('Dock scan completed successfully')
            return True

        except Exception as e:
            logger.error(f'Dock scan failed: {e}')
            logger.exception(e)
            return False


def run_dock_scan(config, device, task):
    """
    Entry point for dock scan task.

    Args:
        config: AzurLaneConfig instance
        device: Device instance
        task: Task name string
    """
    DockScanTask(config=config, device=device, task=task).run()


if __name__ == '__main__':
    DockScanTask('alas', task='DockScan').run()
