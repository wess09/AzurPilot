"""情绪管理系统。

追踪和管理舰队的情绪值（心情值）。碧蓝航线中，舰船在战斗中会消耗情绪，
情绪过低会导致经验加成失效、出现负面表情等。情绪通过以下方式恢复：
- 港区休息（不在后宅）：每 6 分钟恢复 2 点
- 后宅一楼：每 6 分钟恢复 4 点
- 后宅二楼：每 6 分钟恢复 5 点
- 誓约加成：额外 +1 点/6分钟
- 温泉加成：当前配置额外 +1 点/6分钟

情绪控制策略：
- 保持开心加成（>120）：最大化经验加成
- 防止绿脸（>40）：避免负面效果
- 防止黄脸（>30）：避免严重负面效果
- 防止红脸（>2）：最低限度保护

恢复批次相位未知时保存完整可能范围，显示中间值，出击控制使用下限。
首次使用及更换恢复条件后需填写实测心情建立基准。
"""

from time import sleep

import numpy as np

from module.combat.emotion_state import (DIC_RECOVER, DIC_RECOVER_MAX, OATH_RECOVER,
                                        ONSEN_RECOVER, EmotionRecoveryState)
from module.config.config import AzurLaneConfig
from module.config.time_source import now as current_time
from module.exception import ScriptEnd, ScriptError, RequestHumanTakeover
from module.logger import logger

# 情绪控制阈值：当情绪低于此值时触发等待/延迟
DIC_LIMIT = {
    'keep_exp_bonus': 120,     # 保持经验加成（心情开心）
    'prevent_green_face': 40,  # 防止绿脸
    'prevent_yellow_face': 30, # 防止黄脸
    'prevent_red_face': 2,     # 防止红脸
}


class FleetEmotion:
    """单个舰队的情绪追踪器。

    管理一个舰队的情绪值、恢复速度和控制阈值。
    支持独立配置和公海舰队（Public Fleet）模式。

    Attributes:
        config (AzurLaneConfig): 配置对象。
        fleet (str): 舰队索引（1、2 或 'Public'）。
        current (int): 当前计算的情绪值。
    """

    def __init__(self, config, fleet):
        """初始化舰队情绪追踪器。

        Args:
            config (AzurLaneConfig): 配置对象。
            fleet (str | int): 舰队索引（1、2 或 'Public'）。
        """
        self.config = config
        self.fleet = fleet
        self.current = 0
        self.state = None
        self.calibration_error = '尚未校准'

    @property
    def _key_prefix(self):
        if self.fleet == 'Public':
            return 'PublicEmotion_Fleet'
        return f'Emotion_Fleet{self.fleet}'

    @property
    def value(self):
        """获取配置中记录的情绪数值。

        Returns:
            int: 情绪值，范围 0 到 150。
        """
        return getattr(self.config, f'{self._key_prefix}Value')

    @property
    def value_name(self):
        """获取配置中情绪数值的键名。

        Returns:
            str: 情绪数值配置键名。
        """
        return f'{self._key_prefix}Value'

    @property
    def state_name(self):
        return f'{self._key_prefix}RecoveryState'

    @property
    def lower(self):
        self.require_calibration()
        return self.state.lower

    @property
    def upper(self):
        self.require_calibration()
        return self.state.upper

    def require_calibration(self):
        if self.state is None:
            logger.critical(f'[心情-校准] 舰队 {self.fleet}：{self.calibration_error}。'
                            '请暂停出击，确认恢复条件，并重新填写该舰队的实测最低心情值。')
            raise RequestHumanTakeover

    @property
    def record(self):
        """获取配置中记录的情绪更新时间戳。

        Returns:
            datetime: 情绪记录时间戳。
        """
        return getattr(self.config, f'{self._key_prefix}Record')

    @property
    def recover(self):
        """获取配置的情绪恢复地点。

        Returns:
            str: 恢复地点类型，如 not_in_dormitory、dormitory_floor_1、dormitory_floor_2。
        """
        return getattr(self.config, f'{self._key_prefix}Recover')

    @property
    def control(self):
        """获取情绪控制策略。

        Returns:
            str: 控制策略，如 keep_exp_bonus、prevent_green_face、prevent_yellow_face、prevent_red_face。
        """
        return getattr(self.config, f'{self._key_prefix}Control')

    @property
    def oath(self):
        """获取是否所有舰船均已誓约。

        Returns:
            bool: 是否所有舰船已誓约。
        """
        return getattr(self.config, f'{self._key_prefix}Oath')

    @property
    def onsen(self):
        """获取是否所有舰船均在温泉中。

        Returns:
            bool: 是否所有舰船在温泉中。
        """
        return getattr(self.config, f'{self._key_prefix}Onsen')

    @property
    def speed(self):
        """获取情绪每 6 分钟的恢复点数。

        Returns:
            int: 每 6 分钟恢复点数。
        """
        speed = DIC_RECOVER[self.recover]
        if self.oath:
            speed += OATH_RECOVER
        if self.onsen:
            speed += ONSEN_RECOVER
        return speed

    @property
    def limit(self):
        """获取情绪控制的最低阈值。

        Returns:
            int: 情绪控制的最低阈值。
        """
        return DIC_LIMIT[self.control]

    @property
    def max(self):
        """获取当前恢复模式下的最大情绪上限。

        Returns:
            int: 最大情绪值。
        """
        return 150 if self.onsen else DIC_RECOVER_MAX[self.recover]

    def update(self, now=None, require_calibration=True):
        """读取最新存档后推进所有恢复相位，避免跨任务复用旧的缓存状态。"""
        self.state = None
        try:
            state = EmotionRecoveryState.restore(getattr(self.config, self.state_name, None),
                                                self.value, self.record, self.recover, self.oath, self.onsen)
            state.advance(current_time() if now is None else now)
        except (ValueError, TypeError) as exc:
            self.calibration_error = str(exc)
            if require_calibration:
                self.require_calibration()
            return
        self.state = state
        self.current = state.value

    def _migrate_config(self):
        """修复不可用的恢复存档：按当前心情值重建三件套并回写。

        存档缺失、版本不可用或与配置的心情值和记录时刻不一致时，以配置的值为基准
        重建恢复起点；配置值始终作为权威，避免从不可信的相位估算出偏高的心情。

        Returns:
            bool: 是否已完成修复；未绑定或值不可信时为 False。
        """
        value = self.value
        if type(value) is not int or not 0 <= value <= 150:
            return False
        bound = getattr(self.config, 'bound', None)
        if isinstance(bound, dict) and self.state_name not in bound:
            # 未绑定则赋值不会回写配置，迁移结果会丢失，不如此处不做迁移。
            return False
        if current_time() < self.record:
            # 记录时刻晚于当前时间时不修复，避免拿未来的账本出击。
            return False
        try:
            state = EmotionRecoveryState.calibrate(value, current_time(),
                                                  self.recover, self.oath, self.onsen)
        except (ValueError, TypeError):
            return False
        logger.info('[心情-兼容] 恢复存档不可用，已按当前值重建恢复起点：'
                    f'心情 {value}；要获得相位精度，可在任务页重新填写该舰队的实测最低心情值')
        # 三个字段必须一起写入：只写相位会让下一次 restore 因与值或时间不一致而失败。
        with self.config.multi_set():
            setattr(self.config, self.state_name, state.export())
            setattr(self.config, self.value_name.replace('Value', 'Record'), state.record)
            setattr(self.config, self.value_name, state.value)
        self.state = state
        self.calibration_error = ''
        return True

    def consume(self, amount):
        self.require_calibration()
        self.state.consume(amount)
        self.current = self.state.value

    def get_recovered(self, expected_reduce=0):
        """计算情绪恢复到控制阈值的时间。

        Args:
            expected_reduce (int, optional): 预期的情绪减少量。默认为 0。

        Returns:
            datetime: 情绪达到控制阈值的时间。如果当前已满足阈值，则返回当前时间。

        Raises:
            RequestHumanTakeover: 控制策略与恢复地点冲突时抛出，请求人工接管。
        """
        if self.state is None:
            # 升级前的配置只有数值与时间：在需要恢复时间时补建起点，不阻断任务。
            if not self._migrate_config():
                self.require_calibration()
        if self.control == 'keep_exp_bonus' and self.recover == 'not_in_dormitory' and not self.onsen:
            logger.critical(f'[战斗] 舰队 {self.fleet} 的情绪控制设置为"保持开心加成"，且恢复地点设置为"港区"，两者不能同时使用，请检查情绪设置')
            raise RequestHumanTakeover
        # 在 14-4 使用双倍经验书时，预期情绪减少为 32，无法保持开心加成（>120）
        # 否则会导致无限任务延迟
        if self.control == 'keep_exp_bonus' and expected_reduce >= 29:
            expected_reduce = 29
            logger.info(f'[情绪-舰队] 舰队 {self.fleet} 预期扣减限制为29 '
                        f'当情绪控制="保持快乐奖励"时')

        try:
            return self.state.recovered_at(int(self.limit + expected_reduce))
        except ValueError as exc:
            logger.critical(f'[心情-配置] 舰队 {self.fleet}：{exc}')
            raise RequestHumanTakeover from exc


class Emotion:
    """情绪管理主类。

    编排两个舰队（和可选的公海舰队）的情绪追踪、等待和扣减。
    在战役开始前检查情绪是否足够，在战斗后扣减情绪值，
    并在情绪不足时延迟任务执行。

    Attributes:
        map_is_2x_book (bool): 是否使用二倍经验书（影响情绪扣减量）。
        fleet_1 (FleetEmotion): 第一舰队的情绪追踪器。
        fleet_2 (FleetEmotion): 第二舰队的情绪追踪器。
        using_public (bool): 是否使用公海舰队统一情绪管理。
    """
    map_is_2x_book = False

    def __init__(self, config):
        """
        Args:
            config (AzurLaneConfig): 配置对象。
        """
        self.config = config
        self.fleet_1 = FleetEmotion(self.config, fleet=1)
        self.fleet_2 = FleetEmotion(self.config, fleet=2)
        self.fleets = [self.fleet_1, self.fleet_2]
        self.using_public = self._handle_public()
    
    def _handle_public(self):
        """检查并初始化公海舰队情绪管理。

        Returns:
            bool: 是否启用公海舰队管理。
        """
        if not getattr(self.config, 'PublicEmotion_Enable'):
            return False
        
        tasks = getattr(self.config, 'PublicEmotion_Tasks')

        if not tasks:
            return False

        tasks = [task.strip() for task in tasks.split(',')]

        if self.config.task.command not in tasks:
            return False

        self.public_fleet = FleetEmotion(self.config, fleet='Public')
        return True

    @property
    def is_calculate(self):
        """是否启用情绪计算模式。

        Returns:
            bool: 是否为计算模式。
        """
        return 'calculate' in self.config.Emotion_Mode

    @property
    def is_ignore(self):
        """是否启用忽略情绪模式。

        Returns:
            bool: 是否为忽略模式。
        """
        return 'ignore' in self.config.Emotion_Mode

    def update(self):
        """更新情绪值。应在执行任何操作之前调用。"""
        now = current_time()
        if self.using_public:
            self.public_fleet.update(now, require_calibration=False)
            return
        
        for fleet in self.fleets:
            fleet.update(now, require_calibration=False)

    def record(self):
        """原子保存同一计算时刻的数值、完整时间和相位；保存耗时留待下次推进。"""
        fleets = [self.public_fleet] if self.using_public else self.fleets
        with self.config.multi_set():
            for fleet in fleets:
                if fleet.state is None:
                    continue
                setattr(self.config, fleet.value_name, fleet.state.value)
                setattr(self.config, fleet.value_name.replace('Value', 'Record'), fleet.state.record)
                setattr(self.config, fleet.state_name, fleet.state.export())
        if getattr(self.config, 'auto_update', True):
            for fleet in fleets:
                if fleet.state is not None and (fleet.value != fleet.state.value or
                                                fleet.record != fleet.state.record or
                                                getattr(self.config, fleet.state_name) != fleet.state.export()):
                    fleet.state = None
                    fleet.calibration_error = '保存期间心情基准被修改，请重新检查实测值'

    def show(self):
        """显示中间值与可能范围，未校准状态不显示为准确心情。"""
        fleets = [self.public_fleet] if self.using_public else self.fleets
        for fleet in fleets:
            label = '情绪公海舰队' if self.using_public else f'情绪舰队_{fleet.fleet}'
            if fleet.state is None:
                logger.attr(label, '未校准')
            else:
                logger.attr(label, f'{fleet.current}（范围 {fleet.lower}–{fleet.upper}，控制使用下限）')

    @property
    def reduce_per_battle(self):
        """单场战斗的基础情绪扣减量。

        Returns:
            int: 扣减量（使用双倍书时为 4，否则为 2）。
        """
        if self.map_is_2x_book:
            return 4
        else:
            return 2

    @property
    def reduce_per_battle_before_entering(self):
        """进入战役前预估的单场战斗情绪扣减量。

        Returns:
            int: 扣减量。
        """
        if self.map_is_2x_book:
            return 4
        elif self.config.Campaign_Use2xBook:
            return 4
        else:
            return 2
    
    @property
    def reduce_shipwreck(self):
        """单次沉船额外扣减的情绪值。

        Returns:
            int: 扣减值，固定为 10。
        """
        return 10

    def _check_reduce(self, battle):
        """检查战役战斗带来的情绪减少量及是否需要延迟。

        Args:
            battle (int): 战役战斗总场次。

        Returns:
            tuple[datetime, bool]: 包含预期恢复时间与是否需要延迟的元组。

        Raises:
            ScriptError: 舰队出击顺序配置未知时抛出。
        """
        if self.using_public:
            reduce = battle * self.reduce_per_battle_before_entering
            logger.info(f'[情绪-检查] 预期情绪扣减: {reduce}')

            self.update()
            self.record()
            self.show()
            recovered = self.public_fleet.get_recovered(reduce)
            delay = recovered > current_time()
            return recovered, delay

        method = self.config.Fleet_FleetOrder

        if method == 'fleet1_mob_fleet2_boss':
            battle = (battle - 1, 1)
        elif method == 'fleet1_boss_fleet2_mob':
            battle = (1, battle - 1)
        elif method == 'fleet1_all_fleet2_standby':
            battle = (battle, 0)
        elif method == 'fleet1_standby_fleet2_all':
            battle = (0, battle)
        else:
            raise ScriptError(f'Unknown fleet order: {method}')

        battle = tuple(np.array(battle) * self.reduce_per_battle_before_entering)
        logger.info(f'[情绪-检查] 预期情绪扣减: {battle}')

        self.update()
        self.record()
        self.show()
        # 待命舰队不参与本图消耗，其未校准状态不能阻塞正在出击的舰队。
        recovered = max((f.get_recovered(b) for f, b in zip(self.fleets, battle) if b > 0),
                        default=current_time())
        delay = recovered > current_time()
        return recovered, delay

    def check_reduce(self, battle):
        """进入战役前检查情绪是否充足。

        若情绪不足以完成战役并保持控制阈值，将自动延迟任务并抛出 ScriptEnd。

        Args:
            battle (int): 本次战役中的战斗次数。

        Raises:
            ScriptEnd: 情绪不足导致当前任务被延迟时抛出。
        """
        if not self.is_calculate:
            return

        recovered, delay = self._check_reduce(battle)
        if delay:
            logger.info('[情绪-延迟] 延迟当前任务以防止未来的情绪控制问题')
            self.config.task_delay(target=recovered)
            raise ScriptEnd('[情绪-延迟] 情绪控制')

    def wait(self, fleet_index):
        """等待指定舰队的情绪恢复到控制阈值。应在进入任何战斗之前调用。

        Args:
            fleet_index (int): 舰队编号（1 或 2）。
        """
        self.update()
        self.record()
        self.show()
        if self.using_public:
            fleet = self.public_fleet
        else:
            fleet = self.fleets[fleet_index - 1]

        recovered = fleet.get_recovered(expected_reduce=self.reduce_per_battle)
        if recovered > current_time():
            logger.hr('情绪等待')
            if self.using_public:
                logger.info(f'[情绪-等待] 公海舰队情绪将恢复到 {fleet.limit}，时间 {recovered}')
            else:
                logger.info(f'[情绪-等待] 舰队 {fleet_index} 情绪将恢复到 {fleet.limit}，时间 {recovered}')

            while 1:
                if current_time() > recovered:
                    break

                logger.attr('等待直到', recovered)
                sleep(60)

    def reduce(self, fleet_index, shipwreck=False):
        """减少指定舰队的情绪值。应在战斗执行完成后调用。

        服务端在战斗加载完成后即扣减情绪。

        Args:
            fleet_index (int): 舰队编号（1 或 2）。
            shipwreck (bool, optional): 舰队是否遭遇船难。默认为 False。
        """
        # 部分沉船任务直接调用此入口；忽略模式不需要心情校准或写入估计值。
        if not self.is_calculate:
            return
        # 无视沉船心情惩罚：沉船的额外扣减发生在结算阶段，而进入战斗时
        # 已扣过基础扣减（reduce_per_battle），因此这里直接返回即可。
        if shipwreck and self.config.Emotion_IgnoreShipwreck:
            logger.info('[情绪-忽略] 已开启无视沉船心情惩罚，本次不额外扣减沉船心情')
            return

        logger.hr('情绪扣减')
        self.update()

        if self.using_public:
            fleet = self.public_fleet
        else:
            fleet = self.fleets[fleet_index - 1]

        if not shipwreck:
            fleet.consume(self.reduce_per_battle)
        else:
            fleet.consume(self.reduce_shipwreck)
        self.record()
        self.show()

    def emergency_reset(self):
        """心情清零保底。计算模式下出现红脸弹窗时调用。

        将受管理舰队的账本从当前时刻按 0 重新计算，保留全部未知恢复相位。
        0 是保守起点，不代表每艘船的实测心情；在恢复条件正确且无额外消耗时，
        下限恢复到出击要求后即可自动继续，无需人工校准或重启模拟器。
        """
        if self.using_public:
            fleets = [self.public_fleet]
        else:
            fleets = self.fleets

        with self.config.multi_set():
            record_time = current_time()
            for fleet in fleets:
                state = EmotionRecoveryState.calibrate(
                    0, record_time, fleet.recover, fleet.oath, fleet.onsen)
                fleet.current = 0
                fleet.state = state
                fleet.calibration_error = ''
                setattr(self.config, fleet.value_name, 0)
                setattr(self.config, fleet.value_name.replace('Value', 'Record'),
                        record_time)
                setattr(self.config, fleet.state_name, state.export())
        logger.info('[心情-保底] 已将受管理舰队心情按0重新计时，恢复到出击要求后自动继续')
