import numpy as np
import numba as nb
import threading
import time
from tqdm import tqdm
from datetime import datetime

from module.config.config import AzurLaneConfig
from module.log_res.log_res import LogRes
from module.statistics.cl1_database import db
from module.statistics.ship_exp_stats import get_ship_exp_stats

from module.os_simulator.constants import *
from module.os_simulator.plotter import OSSimulatorPlotter
from module.os_simulator.logger import OSSLogger, TqdmToLogger

@nb.njit(cache=True, fastmath=True)
def _akashi_sample():
    """
    不放回采样: 从 AKASHI (长度24) 中选6个。
    """
    total = 0.0
    mask = 0
    for _ in range(6):
        while True:
            idx = np.random.randint(0, 24)
            if not ((mask >> idx) & 1):
                mask |= (1 << idx)
                total += AKASHI[idx]
                break
    return total

@nb.njit(cache=True, fastmath=True)
def _handle_akashi(s, akashi_prob, deterministic):
    if deterministic:
        # 确定性模式：使用预计算的期望值
        total_reward = akashi_prob * AKASHI_EXPECT_REWARD_6
        s[AP] += total_reward
        s[COIN] -= total_reward * 40.0
        return

    if np.random.random() < akashi_prob:
        reward = _akashi_sample()
        s[AP] += reward
        s[COIN] -= reward * 40.0

@nb.njit(cache=True, fastmath=True)
def _simulate_one(
    init_ap, init_coin,
    total_time, meow_hazard_level,
    coin_preserve, coin_threshold, ap_preserve,
    coin_expect_cl1, coin_expect_meow,
    modified_cl1_time, modified_meow_time,
    akashi_prob,
    daily_reward, stronghold_reward,
    cross_week, buy_ap, days_until_next_monday,
    deterministic,
    record_history=False
):
    """
    模拟单个样本的核心循环。
    支持 record_history 模式以记录轨迹。
    """
    s = np.zeros(8, dtype=np.float64)
    s[AP], s[COIN], s[STATUS] = init_ap, init_coin, 0.0

    # 历史记录初始化
    hist_time = hist_ap = hist_coin = hist_status = np.empty(0, dtype=np.float64)
    hist_idx = 0
    max_steps = 0
    last_time = 0.0

    if record_history:
        min_time = min(modified_cl1_time, modified_meow_time)
        max_steps = int(total_time / min_time) + 1000
        hist_time = np.empty(max_steps, dtype=np.float64)
        hist_ap = np.empty(max_steps, dtype=np.float64)
        hist_coin = np.empty(max_steps, dtype=np.float64)
        hist_status = np.empty(max_steps, dtype=np.float64)
        # 初始记录
        hist_time[0], hist_ap[0], hist_coin[0], hist_status[0] = 0.0, init_ap, init_coin, 0.0
        hist_idx, last_time = 1, 0.0

    while s[STATUS] != STATUS_DONE:
        # 1. 状态切换逻辑
        curr_status = s[STATUS]
        if curr_status == STATUS_CL1:
            if s[AP] < ap_preserve: s[STATUS] = STATUS_CRASHED
            elif s[COIN] < coin_preserve: s[STATUS] = STATUS_MEOW
        elif curr_status == STATUS_MEOW:
            if s[AP] < ap_preserve: s[STATUS] = STATUS_CRASHED
            elif s[COIN] >= coin_preserve + coin_threshold: s[STATUS] = STATUS_CL1
        elif curr_status == STATUS_CRASHED:
            if s[AP] >= AP_COSTS[1]: s[STATUS] = STATUS_CL1

        # 2. 样本步进动作
        active_status = s[STATUS]
        if active_status == STATUS_CL1:
            s[CL1_COUNT] += 1
            s[AP] -= AP_COSTS[1]
            s[COIN] += coin_expect_cl1
            step_time = modified_cl1_time
            s[AP] += AP_RECOVER * step_time
            s[USED_TIME] += step_time
            _handle_akashi(s, akashi_prob, deterministic)
        elif active_status == STATUS_MEOW:
            s[MEOW_COUNT] += 1
            s[AP] -= AP_COSTS[meow_hazard_level]
            s[COIN] += coin_expect_meow
            step_time = modified_meow_time
            s[AP] += AP_RECOVER * step_time
            s[USED_TIME] += step_time
            _handle_akashi(s, akashi_prob, deterministic)
        elif active_status == STATUS_CRASHED:
            s[HAS_CRASHED], s[USED_TIME], s[AP] = 1.0, s[USED_TIME] + 43200.0, s[AP] + 72.0

        # 3. 每日/周刷新检查
        sim_days = int(s[USED_TIME] // 86400)
        while sim_days > s[PASSED_DAYS]:
            s[PASSED_DAYS] += 1
            s[COIN] += daily_reward
            if cross_week and (s[PASSED_DAYS] - days_until_next_monday) % 7 == 0:
                if buy_ap: s[AP] += 1000.0
                s[AP], s[COIN] = s[AP] - 200.0, s[COIN] + stronghold_reward

        if s[USED_TIME] >= total_time:
            s[STATUS] = STATUS_DONE

        # 4. 轨迹记录
        if record_history and s[USED_TIME] > last_time:
            if hist_idx < max_steps:
                hist_time[hist_idx], hist_ap[hist_idx], hist_coin[hist_idx], hist_status[hist_idx] = \
                    s[USED_TIME], s[AP], s[COIN], s[STATUS]
                hist_idx += 1
                last_time = s[USED_TIME]

    return s, hist_time[:hist_idx], hist_ap[:hist_idx], hist_coin[:hist_idx], hist_status[:hist_idx], hist_idx

@nb.njit(cache=True, parallel=True, fastmath=True)
def _simulate_batch_kernel(results, record_multi, grid_ap, grid_coin, grid_crash, *params):
    for i in nb.prange(len(results)):
        res, h_time, h_ap, h_coin, h_status, h_len = _simulate_one(*params, record_multi)
        results[i] = res
        if record_multi:
            num_grids = grid_ap.shape[1]
            total_time = params[2]
            if num_grids > 1:
                dt = total_time / (num_grids - 1)
            else:
                dt = 1.0
            idx = 0
            has_crashed = 0.0
            for j in range(num_grids):
                t = j * dt
                while idx < h_len - 1 and h_time[idx + 1] <= t:
                    idx += 1
                    if h_status[idx] == 2.0:
                        has_crashed = 1.0
                if h_status[idx] == 2.0:
                    has_crashed = 1.0
                grid_ap[i, j] = h_ap[idx]
                grid_coin[i, j] = h_coin[idx]
                grid_crash[i, j] = has_crashed

class OSSimulator:
    def __init__(self):
        self.logger = OSSLogger()
        self.plotter = OSSimulatorPlotter(self.logger)
        self.config = None
        self.history_single = {}
        self._thread = None
        self._stop_event = threading.Event()

    def _get_azurstat_data(self):
        # 预计之后使用azurstat统计数据，目前先这样吧（
        
        # 目前包括吊机
        cl1_coin = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Cl1Coin')
        meow3_coin = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Meow3Coin')
        meow5_coin = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Meow5Coin')
        self.coin_expectation = {
            1: cl1_coin,
            3: meow3_coin,
            5: meow5_coin
        }
        self.logger.info(f'每轮对应侵蚀等级期望获得黄币: {self.coin_expectation}')
        
        self.akashi_probability = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.AkashiProbability')
        self.logger.info(f'遇见明石概率: {self.akashi_probability}')

        self.daily_reward = 6520
        self.logger.info(f'每日任务获得黄币: {self.daily_reward}')
        
        self.stronghold_reward = 40000
        self.logger.info(f'每周要塞期望获得黄币: {self.stronghold_reward}')
    
    def get_paras(self):
        self.config.load()
        
        self.samples = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Samples')
        self.logger.info(f'样本数: {self.samples}')

        self.draw_setting = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Draw')
        self.logger.info(f'绘图设置: {self.draw_setting}')
        
        self.total_time = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.TotalTime')
        if not self.total_time:
            self.total_time = self._get_remaining_seconds()
        self.logger.info(f'总模拟时间 (s): {self.total_time}')
        
        self.time_use_ratio = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.TimeUseRatio')
        self.logger.info(f'时间利用率: {self.time_use_ratio}')
        
        hazard_level = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.MeowHazardLevel', 'level5')
        if hazard_level == 'level3':
            self.meow_hazard_level = 3
        else:
            self.meow_hazard_level = 5
        self.logger.info(f'短猫侵蚀等级: {self.meow_hazard_level}')
        
        log_res = LogRes(self.config)
        ap = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.InitialAp')
        if not ap:
            ap = log_res.group('ActionPoint')
            ap = ap['Total'] if ap and 'Total' in ap else 0
        coin = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.InitialCoin')
        if not coin:
            coin = log_res.group('YellowCoin')
            coin = coin['Value'] if coin and 'Value' in coin else 0

        self.init_ap = float(ap)
        self.init_coin = float(coin)
        self.logger.info(f'初始黄币: {coin}')
        self.logger.info(f'初始行动力: {ap}')

        self.cross_week = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.CrossWeek')
        self.logger.info(f'是否计算跨周: {self.cross_week}')

        self.buy_ap = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.BuyAp')
        self.logger.info(f'每周是否购买行动力: {self.buy_ap}')
        
        self.coin_preserve = self.config.cross_get('OpsiScheduling.OpsiScheduling.OperationCoinsPreserve')
        self.logger.info(f'保留黄币: {self.coin_preserve}')
        self.ap_preserve = self.config.cross_get('OpsiScheduling.OpsiScheduling.ActionPointPreserve')
        self.logger.info(f'保留行动力: {self.ap_preserve}')
        self.coin_threshold = self.config.cross_get('OpsiScheduling.OpsiScheduling.OperationCoinsReturnThreshold')
        self.logger.info(f'短猫直到获得多少黄币: {self.coin_threshold}')
        
        self.instance_name = getattr(self.config, 'config_name', 'default')
        self.logger.info(f'实例名: {self.instance_name}')
        
        if self.meow_hazard_level == 3:
            self.meow_time = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Meow3Time')
            if not self.meow_time:
                # 尝试从数据库获取短猫统计，如果不区分等级则统一使用平均值
                self.meow_time = db.get_meow_stats(self.instance_name).get('avg_round_time', 100)
        else: # hazard level 5
            self.meow_time = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Meow5Time')
            if not self.meow_time:
                self.meow_time = db.get_meow_stats(self.instance_name).get('avg_round_time', 200)
        
        self.logger.info(f'每轮短猫时间: {self.meow_time}')

        self.cl1_time = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Cl1Time')
        if not self.cl1_time:
            self.cl1_time = get_ship_exp_stats(self.instance_name).get_average_round_time()
        self.logger.info(f'每轮侵蚀1时间: {self.cl1_time}')
        
        self.days_until_next_monday = self._get_days_until_next_monday()
        self.logger.info(f'距离下周一还有多少天: {self.days_until_next_monday}')

        # 调试模式开关：设置为 True 则取消随机性，按照期望值计算演化
        self.deterministic = self.config.cross_get('OpsiSimulator.OpsiSimulatorParameters.Deterministic', False)
        if self.deterministic:
            self.samples = 1
            self.logger.info('调试模式：使用确定性计算。采样数已强制设置为 1 以提高计算速度。')
            self.logger.info('（不使用随机概率，按期望演化）')

        # 修正后的单轮时间：包含了因"时间利用率"不足而产生的空闲时间，用于正确计算AP的自然恢复
        self.modified_meow_time = self.meow_time / self.time_use_ratio
        self.modified_cl1_time = self.cl1_time / self.time_use_ratio

        self._get_azurstat_data()

    def precompile(self):
        """
        预编译 Numba 函数，确保正式模拟时达到最高速度。
        即使已从缓存加载，也会在日志输出时间。
        """
        self.logger.info("检查预编译状态（第一次运行时会耗费一定时间）...")
        start_time = time.perf_counter()
        
        # 1. 编译基础采样函数
        _akashi_sample()
        
        # 2. 编译明石处理逻辑
        s = np.zeros(8, dtype=np.float64)
        _handle_akashi(s, 0.5, False)
        
        # 3. 编译核心模拟循环 (覆盖两种 record_history 情况)
        # 使用 dummy 参数确保立即返回
        _params = (
            0.0, 0.0, 0.0, 5, 
            0.0, 0.0, 0.0, 0.0, 0.0, 
            1.0, 1.0, 0.0, 0.0, 0.0, 
            False, False, 0, False
        )
        _simulate_one(*_params, False)
        _simulate_one(*_params, True)
        dummy_grid = np.empty((1, 2), dtype=np.float64)
        _simulate_batch_kernel(np.empty((1, 8), dtype=np.float64), False, dummy_grid, dummy_grid, dummy_grid, *_params)
        
        elapsed = time.perf_counter() - start_time
        self.logger.info(f"预编译检查完成，用时: {elapsed:.3f}s")
    
    @property
    def is_running(self):
        return bool(self._thread and self._thread.is_alive())
    
    @property
    def figure(self):
        return self.plotter.result_figure_path
    
    def _run(self):
        try:
            if not self.config:
                raise ValueError('缺少配置')
            
            self.get_paras()

            if self.meow_hazard_level not in self.coin_expectation:
                raise ValueError(f'不支持的短猫侵蚀等级: {self.meow_hazard_level}')

            self.precompile()

            self.logger.info("开始模拟...")
            start_time = time.time()
            result = self.simulate()
            self.logger.info(f"模拟完成，用时: {time.time() - start_time:.2f}秒")
            self._handle_result(result)
        except Exception as e:
            self.logger.exception(f"运行中出现错误: {e}")
    
    def set_config(self, config: AzurLaneConfig):
        self.config = config

    def start(self):
        if self.is_running:
            self.logger.warning("模拟正在进行，请耐心等待")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run)
        self._thread.start()
    
    def interrupt(self):
        if self.is_running:
            self.logger.info("等待模拟中断")
            self._stop_event.set()
        else:
            self.logger.info("无正在进行的模拟")

    def _get_remaining_seconds(self):
        now = datetime.now()
        if now.month == 12:
            next_month = datetime(now.year + 1, 1, 1)
        else:
            next_month = datetime(now.year, now.month + 1, 1)
        return (next_month - now).total_seconds()

    def _get_days_until_next_monday(self):
        now = datetime.now()
        current_weekday = now.weekday()
        days_ahead = 7 - current_weekday
        return days_ahead
    
    def simulate(self):
        if not hasattr(self, 'init_ap'):
            self.get_paras()
        
        # 准备传给 Numba kernel 的参数
        coin_expect_cl1 = float(self.coin_expectation[1])
        coin_expect_meow = float(self.coin_expectation[self.meow_hazard_level])

        # 结果数组: (samples, 8)
        results = np.empty((self.samples, 8), dtype=np.float64)

        # 绘图历史
        record_single = (self.draw_setting == 'single_sample')
        record_multi = (self.draw_setting == 'multi_sample')

        # 主循环：分批并行模拟
        batch_size = 1000
        start_idx = 0
        
        num_grids = 1000
        if record_multi:
            batch_grid_ap = np.empty((batch_size, num_grids), dtype=np.float64)
            batch_grid_coin = np.empty((batch_size, num_grids), dtype=np.float64)
            batch_grid_crash = np.empty((batch_size, num_grids), dtype=np.float64)
            grid_ap_sum = np.zeros(num_grids, dtype=np.float64)
            grid_coin_sum = np.zeros(num_grids, dtype=np.float64)
            grid_crash_sum = np.zeros(num_grids, dtype=np.float64)
            grid_ap_sq = np.zeros(num_grids, dtype=np.float64)
            grid_coin_sq = np.zeros(num_grids, dtype=np.float64)
        else:
            batch_grid_ap = np.empty((1, 1), dtype=np.float64)
            batch_grid_coin = np.empty((1, 1), dtype=np.float64)
            batch_grid_crash = np.empty((1, 1), dtype=np.float64)
        
        # 使用 tqdm 画图并重定向到 logger，mininterval 限制日志记录频率
        pbar = tqdm(
            range(self.samples), 
            file=TqdmToLogger(self.logger), 
            mininterval=1.0, 
            desc='[OSSimulator]',
            ncols=100
        )
        
        params = (
            self.init_ap, self.init_coin,
            float(self.total_time), self.meow_hazard_level,
            float(self.coin_preserve), float(self.coin_threshold), float(self.ap_preserve),
            coin_expect_cl1, coin_expect_meow,
            float(self.modified_cl1_time), float(self.modified_meow_time),
            float(self.akashi_probability),
            float(self.daily_reward), float(self.stronghold_reward),
            self.cross_week, self.buy_ap, self.days_until_next_monday,
            self.deterministic
        )

        # 绘图历史（仅 single_sample 时记录 sample 0）
        if record_single and self.samples > 0:
            result, h_time, h_ap, h_coin, h_status, h_len = _simulate_one(*params, True)
            results[0] = result
            self.history_single = {
                'time': h_time.tolist(),
                'ap': h_ap.tolist(),
                'coin': h_coin.tolist(),
                'status': h_status.tolist()
            }
            start_idx = 1
            pbar.update(1)

        for i in range(start_idx, self.samples, batch_size):
            if self._stop_event.is_set():
                self.logger.info("模拟中断")
                break
            
            this_batch = min(batch_size, self.samples - i)
            if record_multi:
                cur_batch_grid_ap = batch_grid_ap[:this_batch]
                cur_batch_grid_coin = batch_grid_coin[:this_batch]
                cur_batch_grid_crash = batch_grid_crash[:this_batch]
            else:
                cur_batch_grid_ap = batch_grid_ap
                cur_batch_grid_coin = batch_grid_coin
                cur_batch_grid_crash = batch_grid_crash
                
            _simulate_batch_kernel(results[i:i+this_batch], record_multi, cur_batch_grid_ap, cur_batch_grid_coin, cur_batch_grid_crash, *params)
            
            if record_multi:
                grid_ap_sum += np.sum(cur_batch_grid_ap, axis=0)
                grid_coin_sum += np.sum(cur_batch_grid_coin, axis=0)
                grid_crash_sum += np.sum(cur_batch_grid_crash, axis=0)
                grid_ap_sq += np.sum(cur_batch_grid_ap ** 2, axis=0)
                grid_coin_sq += np.sum(cur_batch_grid_coin ** 2, axis=0)
                
            pbar.update(this_batch)
        
        pbar.close()

        if record_multi and self.samples > 0:
            completed = self.samples
            mean_ap = grid_ap_sum / completed
            mean_coin = grid_coin_sum / completed
            mean_crash = grid_crash_sum / completed
            var_ap = grid_ap_sq / completed - mean_ap ** 2
            var_coin = grid_coin_sq / completed - mean_coin ** 2
            # 防止浮点误差造成的负方差
            var_ap[var_ap < 0] = 0
            var_coin[var_coin < 0] = 0
            self.history_multi_avg = {
                'time': np.linspace(0, self.total_time, num_grids),
                'ap': mean_ap,
                'ap_std': np.sqrt(var_ap),
                'coin': mean_coin,
                'coin_std': np.sqrt(var_coin),
                'crash': mean_crash
            }

        return results
    
    def _handle_result(self, result):
        self.logger.info('====================模拟结果====================')

        self.result_cl1_count = np.mean(result[:, CL1_COUNT])
        self.logger.info(f'[模拟结果] 侵蚀1次数: {self.result_cl1_count}')
        self.result_meow_count = np.mean(result[:, MEOW_COUNT])
        self.logger.info(f'[模拟结果] 短猫次数: {self.result_meow_count}')
        self.result_crashed_probability = np.mean(result[:, HAS_CRASHED])
        self.logger.info(f'[模拟结果] 坠机概率: {self.result_crashed_probability}')
        self.result_cl1_total_time = self.result_cl1_count * self.cl1_time
        self.logger.info(f'[模拟结果] 侵蚀一总时长 (h): {self.result_cl1_total_time / 3600}')
        self.result_meow_total_time = self.result_meow_count * self.meow_time
        self.logger.info(f'[模拟结果] 短猫总时长 (h): {self.result_meow_total_time / 3600}')
        self.result_ap = np.mean(result[:, AP])
        self.logger.info(f'[模拟结果] 最终行动力: {self.result_ap}')
        self.result_coin = np.mean(result[:, COIN])
        self.logger.info(f'[模拟结果] 最终黄币: {self.result_coin}')

        if self.draw_setting == 'single_sample':
            self.plotter.plot_single_sample_history(self.history_single)
        elif self.draw_setting == 'multi_sample':
            self.plotter.plot_multi_sample_history(result, self.history_multi_avg)