"""Android 设备文本输入。"""

from module.device.method.fastinput_ime import FastInputIME
from module.logger import logger


class Input(FastInputIME):
    """设备文本输入处理器。

    保留已聚焦输入框的 UIAutomator2 接口，并提供 FastInputIME 输入备用路径。

    Methods:
        input_text_fastinput_ime: 聚焦指定输入框，替换文本并提交。
        ime_shown: 检测输入法窗口是否显示。
        text_input_and_confirm: 输入文本并发送确认动作。
    """

    def ime_shown(self) -> bool:
        """检测当前输入法（IME）窗口是否正在显示。

        Returns:
            bool: 输入法窗口可见返回 True，否则返回 False。
        """
        _, shown = self.u2_current_ime()
        return shown

    def text_input_and_confirm(self, text: str, clear: bool=False):
        """向当前焦点输入框发送文本并按确认键（IME_ACTION_DONE）。

        失败时最多重试 3 次，适用于输入法偶尔无响应的场景。

        Args:
            text (str): 要输入的文本内容。
            clear (bool): 输入前是否清空输入框已有内容。
        """
        for fail_count in range(3):
            try:
                self.u2_send_keys(text=text, clear=clear)
                self.u2_send_action(6)
                break
            except EnvironmentError as e:
                if fail_count >= 2:
                    raise e
                logger.exception(f'{e} 正在重试 {fail_count + 1}/3')
