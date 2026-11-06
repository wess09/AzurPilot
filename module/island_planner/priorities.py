"""岛屿生产规划的优先级：目标 → 季节 PT → 岛币。

ALAS 的规划只求一次：满足目标与岛币下限后最大化季节 PT。PT 相同的方案可能有很多，
求解器任选一个，岛币可能白白少拿。这里在第一次求解后再求一次：保持 PT 不低于最优值，
在此基础上最大化每日岛币净收入。

1. 目标（季节任务、额外目标、货运缺口）与每日岛币下限是约束，必须满足；
2. 第一次求解最大化季节 PT（ALAS 原目标）；
3. 第二次求解固定 PT ≥ 最优值，最大化岛币。
"""
import numpy as np
from scipy.optimize import milp

from module.island_planner.calculator import extend_problem
from module.logger import logger

# PT 下限留一点余量，避免浮点误差让第二次求解不可行
PT_TOLERANCE = 1e-6


def solve_with_priorities(calculator, task_target_items=None, task_target_period=None, current_time=None,
                          priority='pt'):
    """按「目标 → PT → 岛币」求解，结果写回 calculator（与 solve_production_plan 相同的属性）。

    Args:
        priority (str): 'pt' 为先 PT 后岛币（ALAS 原目标）；'coins' 为先最大化每日岛币，
            再保持岛币不低于最优值最大化 PT。目标与岛币下限两种模式都必须满足。

    Returns:
        bool: 是否求解成功。第二次求解失败时保留第一次的方案。
    """
    # 只建模一次，两次求解共用，避免「无法生产的目标」等警告重复输出
    calculator.hard_floor_items = calculator._build_planner_hard_floor_items(None)
    problem = calculator.build_production_problem(
        task_target_items=task_target_items, task_target_period=task_target_period, current_time=current_time)
    pt_objective = np.asarray(problem['c'], dtype=float)
    coin_column = problem['end_offset'] + problem['item_index'][1]
    coin_objective = np.zeros(len(pt_objective))
    coin_objective[coin_column] = -1
    if priority == 'coins':
        first_objective, second_objective, first_name = coin_objective, pt_objective, '岛币'
    else:
        first_objective, second_objective, first_name = pt_objective, coin_objective, 'PT'

    first = milp(first_objective, constraints=problem['constraints'], bounds=problem['bounds'])
    if not first.success:
        # 不可行时走 ALAS 原流程，输出瓶颈诊断
        calculator.solve_production_plan(
            task_target_items=task_target_items, task_target_period=task_target_period, current_time=current_time)
        return calculator.lp_success
    calculator._apply_production_lp_result(first, problem)
    first_pt, first_coins = calculator.total_pt, calculator.daily_profit

    # 第一目标不低于最优值（留一点余量避免浮点误差），再求第二目标
    floor_columns = {index: value for index, value in enumerate(first_objective) if value}
    limit = first.fun + PT_TOLERANCE * max(abs(first.fun), 1)
    extended = extend_problem(problem, rows=[{'label': ('first_floor', 0), 'columns': floor_columns, 'ub': limit}])
    second_objective = np.concatenate([second_objective, np.zeros(len(extended['c']) - len(second_objective))])
    second = milp(second_objective, constraints=extended['constraints'], bounds=extended['bounds'])
    if not second.success:
        logger.warning(f'[岛屿-规划] 保持{first_name}时求解第二目标失败，沿用第一次方案: {second.message}')
        return True
    calculator._apply_production_lp_result(second, extended)
    logger.info(f'[岛屿-规划] 优先级求解：季节 PT {first_pt:.0f} → {calculator.total_pt:.0f}，'
                f'每日岛币 {first_coins:.0f} → {calculator.daily_profit:.0f}')
    return True
