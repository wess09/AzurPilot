from module.base.base import ModuleBase
from module.base.timer import Timer
from module.exception import ScriptError
from module.logger import logger


class Switch:
    """
    游戏开关控件的封装，支持在多个状态间切换并带有重试机制。

    Examples:
        # 定义
        submarine_hunt = Switch('Submarine_hunt', offset=120)
        submarine_hunt.add_state('on', check_button=SUBMARINE_HUNT_ON)
        submarine_hunt.add_state('off', check_button=SUBMARINE_HUNT_OFF)

        # 切换到 ON 状态
        submarine_view.set('on', main=self)
    """

    def __init__(self, name='Switch', is_selector=False, offset=0):
        """
        Args:
            name (str): 开关名称。
            is_selector (bool): True 表示多选选择器，点击可切换不同选项。
                例如：| [每日] | 紧急 | -> 点击 -> | 每日 | [紧急] |
                False 表示开关，在同一位置点击切换状态。
                例如：| [开] | -> 点击 -> | [关] |
        """
        self.name = name
        self.is_selector = is_selector
        self._offset = offset
        self.state_list = []
        self.set_unknown_timer = Timer(5, count=10)
        self.set_click_timer = Timer(1, count=2)
        self.wait_timeout = Timer(2, count=4)

    def add_state(self, state, check_button, click_button=None, offset=0, similarity=0.85):
        """
        添加一个可切换的状态。

        Args:
            state (str): 状态名称，不能使用 'unknown'。
            check_button (Button): 用于检测该状态的按钮。
            click_button (Button): 点击切换到该状态的按钮，默认与 check_button 相同。
            offset (bool, int, tuple): 匹配偏移量。
            similarity (float): 使用偏移量时的模板匹配阈值。
        """
        if state == 'unknown':
            raise ScriptError(f'Cannot use "unknown" as state name')
        self.state_list.append({
            'state': state,
            'check_button': check_button,
            'click_button': click_button if click_button is not None else check_button,
            'offset': offset if offset else self._offset,
            'similarity': similarity,
        })

    @property
    def offset(self):
        return self._offset

    @offset.setter
    def offset(self, value):
        self._offset = value
        for data in self.state_list:
            data['offset'] = value

    def appear(self, main):
        """
        检测开关是否出现在屏幕上（即状态不是 'unknown'）。

        Args:
            main (ModuleBase): 模块基类实例。

        Returns:
            bool: 是否出现。
        """
        return self.get(main=main) != 'unknown'

    def get(self, main):
        """
        获取当前开关状态。

        Args:
            main (ModuleBase): 模块基类实例。

        Returns:
            str: 状态名称或 'unknown'。
        """
        for data in self.state_list:
            if main.appear(data['check_button'], offset=data['offset'], similarity=data['similarity']):
                return data['state']

        return 'unknown'

    def click(self, state, main):
        """
        点击指定状态对应的按钮。

        Args:
            state (str): 目标状态名称。
            main (ModuleBase): 模块基类实例。
        """
        button = self.get_data(state)['click_button']
        main.device.click(button)

    def get_data(self, state):
        """
        获取指定状态的数据。

        Args:
            state (str): 状态名称。

        Returns:
            dict: add_state 中添加的状态数据。

        Raises:
            ScriptError: 如果状态无效。
        """
        for row in self.state_list:
            if row['state'] == state:
                return row

        raise ScriptError(f'Switch {self.name} received an invalid state: {state}')

    def handle_additional(self, main):
        """
        处理额外弹窗，子类可重写此方法。

        Args:
            main (ModuleBase): 模块基类实例。

        Returns:
            bool: 是否处理了弹窗。
        """
        return False

    def set(self, state, main, skip_first_screenshot=True):
        """
        设置开关到指定状态，带重试和超时机制。

        Args:
            state: 目标状态名称。
            main (ModuleBase): 模块基类实例。
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 是否发生了点击操作。
        """
        logger.info(f'{self.name} set to {state}')
        self.get_data(state)

        changed = False
        has_unknown = False
        unknown_timer = self.set_unknown_timer.reset()
        click_timer = self.set_click_timer.clear()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            # 检测当前状态
            current = self.get(main=main)
            logger.attr(self.name, current)

            # 到达目标状态则退出
            if current == state:
                return changed

            # 处理额外弹窗
            if self.handle_additional(main=main):
                continue

            # 未知状态警告
            if current == 'unknown':
                if unknown_timer.reached():
                    logger.warning(f'Switch {self.name} has states evaluated to unknown, '
                                   f'asset should be re-verified')
                    has_unknown = True
                    unknown_timer.reset()
                # 如果 unknown_timer 从未触发，不点击未知状态（可能是切换动画）。
                # 如果 unknown_timer 曾触发过一次，则忽略未知状态直接点击目标状态
                # （可能是尚未添加的新状态）。
                # 通过忽略新状态，Switch.set() 仍可在已知状态间切换。
                if not has_unknown:
                    continue
            else:
                # 已知状态，重置计时器
                unknown_timer.reset()

            # 点击切换
            if click_timer.reached():
                if self.is_selector:
                    # 选择器模式：点击目标状态
                    click_state = state
                else:
                    # 开关模式：点击当前状态来切换到另一个状态
                    # 但 'unknown' 不可点击，此时改为点击目标状态
                    # 假设所有选择器状态共享同一位置
                    if current == 'unknown':
                        click_state = state
                    else:
                        click_state = current
                self.click(click_state, main=main)
                changed = True
                click_timer.reset()
                unknown_timer.reset()

        return changed

    def wait(self, main, skip_first_screenshot=True):
        """
        等待直到任意状态被激活。

        Args:
            main (ModuleBase): 模块基类实例。
            skip_first_screenshot: 是否跳过首次截图。

        Returns:
            bool: 是否成功检测到状态。
        """
        timeout = self.wait_timeout.reset()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            # 检测当前状态
            current = self.get(main=main)
            logger.attr(self.name, current)

            # 检测到已知状态则退出
            if current != 'unknown':
                return True
            if timeout.reached():
                logger.warning(f'{self.name} wait activated timeout')
                return False

            # 处理额外弹窗
            if self.handle_additional(main=main):
                continue
