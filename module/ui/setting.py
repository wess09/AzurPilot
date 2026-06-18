import copy
import typing as t

from module.base.base import ModuleBase
from module.base.button import Button, ButtonGrid
from module.base.timer import Timer
from module.config.utils import dict_to_kv
from module.exception import ScriptError
from module.logger import logger


class Setting:
    def __init__(self, name='Setting', main: ModuleBase = None):
        self.name = name
        # Alas 模块对象
        self.main: ModuleBase = main
        # 设置选项前先重置为默认值
        self.reset_first = True
        # 是否需要取消已激活的选项
        self.need_deselect = False
        # (设置名, 选项名): 选项按钮
        # {
        #     ('sort', 'rarity'): Button(),
        #     ('sort', 'level'): Button(),
        #     ('sort', 'total'): Button(),
        # }
        self.settings: t.Dict[(str, str), Button] = {}
        # 设置名: 选项名
        # {
        #     'sort': 'rarity',
        #     'index': 'all',
        # }
        self.settings_default: t.Dict[str, str] = {}

    def add_setting(self, setting, option_buttons, option_names, option_default):
        """
        添加一组设置选项。

        Args:
            setting (str): 设置名称。
            option_buttons (list[Button], ButtonGrid): 选项按钮列表，可由 ButtonGrid.buttons 生成。
            option_names (list[str]): 每个选项的名称，长度必须与 option_buttons 一致。
            option_default (str): 默认选项名称，必须在 option_names 中。
        """
        if isinstance(option_buttons, ButtonGrid):
            option_buttons = option_buttons.buttons
        for option, option_name in zip(option_buttons, option_names):
            self.settings[(setting, option_name)] = option

        if option_default not in option_names:
            raise ScriptError(f'Define option_default="{option_default}", '
                              f'but default is not in option_names={option_names}')
        self.settings_default[setting] = option_default

    def is_option_active(self, option: Button) -> bool:
        return self.main.image_color_count(option, color=(181, 142, 90), threshold=235, count=250) \
               or self.main.image_color_count(option, color=(74, 117, 189), threshold=235, count=250)

    def _product_setting_status(self, **kwargs) -> t.Dict[Button, bool]:
        """
        生成每个选项按钮的目标激活状态。

        Args:
            **kwargs: 键为设置名，值为所需选项或选项列表。
                例如 `sort=['rarity', 'level']` 或 `sort='rarity'`，
                `sort=None` 表示不更改该设置。

        Returns:
            dict: 键为选项按钮，值为是否应激活。
        """
        # Add defaults
        required_options = copy.deepcopy(self.settings_default)
        required_options.update(kwargs)

        # option_button: Whether should be active
        # {BUTTON_1: True, BUTTON_2: False, ...}
        status: t.Dict[Button, bool] = {}
        for key, option_button in self.settings.items():
            setting, option_name = key
            required = required_options[setting]
            if required is not None:
                required = required if isinstance(required, list) else [required]
                status[option_button] = option_name in required

        return status

    def show_active_buttons(self):
        """
        记录当前激活的选项按钮。

        Logs:
            [Setting] sort/rarity, sort/level
        """
        active = []
        for key, option_button in self.settings.items():
            setting, option_name = key
            if self.is_option_active(option_button):
                active.append(f'{setting}/{option_name}')

        logger.attr(self.name, ', '.join(active))

    def get_buttons_to_click(self, status: t.Dict[Button, bool]) -> t.List[Button]:
        """
        根据目标状态计算需要点击的按钮列表。

        Args:
            status: 键为选项按钮，值为是否应激活。

        Returns:
            list[Button]: 需要点击的按钮列表。
        """
        click = []
        for option_button, enable in status.items():
            active = self.is_option_active(option_button)
            if enable and not active:
                click.append(option_button)
            if self.need_deselect:
                if not enable and active:
                    click.append(option_button)
        return click

    def _set_execute(self, **kwargs):
        """
        执行设置选项的切换，带超时和重试机制。

        Args:
            **kwargs: 键为设置名，值为所需选项或选项列表。
                例如 `sort=['rarity', 'level']` 或 `sort='rarity'`，
                `sort=None` 表示不更改该设置。

        Returns:
            bool: 是否设置成功。
        """
        status = self._product_setting_status(**kwargs)

        logger.info(f'Setting options {self.name}, {dict_to_kv(kwargs)}')
        skip_first_screenshot = True
        retry = Timer(1, count=2)
        timeout = Timer(10, count=20).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.main.device.screenshot()

            if timeout.reached():
                logger.warning(f'设置 {self.name} 选项超时，假定当前选项已正确。')
                return False

            self.show_active_buttons()
            clicks = self.get_buttons_to_click(status)
            if clicks:
                if retry.reached():
                    for button in clicks:
                        self.main.device.click(button)
                    retry.reset()
            else:
                return True

    def set(self, **kwargs):
        """
        设置选项，若 reset_first 为 True 则先重置为默认值。

        Args:
            **kwargs: 键为设置名，值为所需选项或选项列表。
                例如 `sort=['rarity', 'level']` 或 `sort='rarity'`，
                `sort=None` 表示不更改该设置。

        Returns:
            bool: 是否设置成功。
        """
        if self.reset_first:
            self._set_execute()  # Reset options
        self._set_execute(**kwargs)
