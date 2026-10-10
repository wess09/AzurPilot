"""岛屿计划任务模块：走位校验。

`IslandPlan` 原本只是岛屿的全局配置（季节、走位规则），本模块给它加上“可运行”
的效果：在岛屿场景里把勾选了校验的走位路线各走一遍，供人工核对角色能否走到
目标位置（安卓桥接 swipe 的位移会随负载漂移，需要按路口径实际校准）。

跑完（或没有任何勾选）后把任务推迟到第二天，避免同一天反复执行。
"""
from module.island.island import *
from module.island.island_walk import ISLAND_WALK_ROUTES
from module.config.utils import get_server_next_update


class IslandPlan(Island):
    """岛屿计划走位校验执行器。"""

    def delay_to_next_day(self):
        """把岛屿计划任务推迟到第二天 0 点。"""
        target = get_server_next_update('00:00')
        logger.info(f'[岛屿-计划] 下次运行推迟到 {target}')
        self.config.task_delay(target=target, task='IslandPlan')

    def run(self):
        """执行勾选的走位校验，然后推迟到第二天。"""
        routes = [name for name in ISLAND_WALK_ROUTES if self.island_walk_enabled(name)]
        if not routes:
            logger.info('[岛屿-计划] 没有勾选走位校验路线，跳过移动并推迟到第二天')
            self.delay_to_next_day()
            return

        logger.hr('岛屿走位校验', level=1)
        logger.info(f'[岛屿-计划] 本次校验路线: {", ".join(routes)}')
        self.device.screenshot()
        self.ui_goto(page_island, get_ship=False)
        for name in routes:
            logger.hr(f'走位校验 {name}', level=2)
            # 人工接管、设备异常和卡死均应交由调度器处理，不应标记任务成功。
            self.island_walk_route(name)
            # 留一秒让角色停稳，方便截图/人工核对落点
            self.device.sleep(1)
        logger.info('[岛屿-计划] 走位校验结束')
        self.delay_to_next_day()
