import collections

from module.base.base import ModuleBase
from module.base.decorator import Config, cached_property, del_cached_property
from module.base.timer import Timer
from module.base.utils import *
from module.exception import CampaignNameError
from module.logger import logger
from module.map.assets import WITHDRAW
from module.ocr.ocr import Ocr
from module.template.assets import *


class CampaignOcr(ModuleBase):
    stage_entrance = {}
    campaign_chapter: str = '0'
    # 关卡入口的大致区域，用于加速模板匹配
    _stage_detect_area = (87, 117, 1151, 636)

    @staticmethod
    def _campaign_get_chapter_index(name):
        """
        获取章节索引。

        Args:
            name (str, int): 章节名称或索引。

        Returns:
            int: 章节索引。
        """
        if isinstance(name, int):
            return name
        else:
            if name.isdigit():
                return int(name)
            elif name in ['a', 'c', 'as', 'cs', 't', 'ht', 'ts', 'hts', 'sp', 'ex_sp']:
                return 1
            elif name in ['b', 'd', 'bs', 'ds', 'ex_ex']:
                return 2
            else:
                raise CampaignNameError

    @staticmethod
    def _campaign_ocr_result_process(result):
        # OCR 结果可能为 '7--2'，因为游戏中使用的是 '–' 而非 '-'
        result = result.replace('--', '-').replace('--', '-').lstrip('-')

        # 修正 OCR 将 '1' 误识别为 'I' 的情况，如 'I1-1'、'1I-1'、'I-I' 等
        # 同时保留 'isp-2'、'sp1' 等含字母的正常结果
        def replace_func(match):
            segment = match.group(0)
            return segment.replace('I', '1')

        result = re.sub(r'[0-9I]+-[0-9I]+', replace_func, result, count=1)

        # 将 '72' 转换为 '7-2'
        if len(result) == 2 and result[0].isdigit():
            result = '-'.join(result)

        result = result.lower()
        return result

    @staticmethod
    def _campaign_separate_name(name):
        """
        分离关卡名称为章节名和关卡索引。

        Args:
            name (str): 小写关卡名称，如 7-2、d3、sp3。

        Returns:
            tuple[str]: (章节名, 关卡索引)，均为小写。如 ['7', '2']、['d', '3']、['sp', '3']。
        """
        name = name.strip('-')
        if name == 'sp':
            return 'ex_sp', '1'
        elif name.startswith('extra') or name == 'ex':
            return 'ex_ex', '1'
        elif '-' in name:
            return name.split('-')
        elif name.startswith('sp'):
            return 'sp', name[-1]
        elif name[-1].isdigit():
            return name[:-1], name[-1]
        elif name[0].isdigit() and name[-1].isalpha():
            # 49X
            logger.warning(f'Unknown stage name: {name}')
            return '', ''

        logger.warning(f'Unknown stage name: {name}')
        return '', ''

    def campaign_match_multi(self, template, image, stage_image=None, name_offset=(75, 9), name_size=(60, 16),
                             name_letter=(255, 255, 255), name_thresh=128, similarity=0.85):
        """
        从给定图像中查找关卡入口。

        Args:
            template (Template): 模板图像。
            image: 截图。
            stage_image: 用于查找关卡入口的截图。
            name_offset (tuple[int]): 关卡名称偏移量。
            name_size (tuple[int]): 关卡名称区域大小。
            name_letter (tuple[int]): 关卡名称字母颜色。
            name_thresh (int): 关卡名称二值化阈值。
            similarity (float): 模板匹配相似度阈值。

        Returns:
            list[Button]: 关卡通关状态按钮列表。
        """
        digits = []
        stage_image = image if stage_image is None else stage_image
        result = template.match_multi(stage_image, similarity=similarity, name='STAGE')
        name_area = (name_offset[0], name_offset[1], name_offset[0] + name_size[0], name_offset[1] + name_size[1])
        for button in result:
            button = button.move(self._stage_detect_area[:2])
            button_name = button.crop(area=name_area, image=image)
            name = extract_letters(button_name.image, letter=name_letter, threshold=name_thresh)
            button_name = button_name.crop(area=self._extract_stage_name(name))
            # 对每个 Button 实例：
            # button.area: 关卡名称区域，如 '3-4'。临时替换用于 OCR。
            # button.color: 关卡图标颜色，如 'CLEAR' 和 '%'。
            # button.button: 关卡图标区域，如 'CLEAR' 和 '%'。
            # button.name: 'STAGE'，无实际意义的名称。
            button.load_color(image)
            button.area = button_name.area
            digits.append(button)

        return digits

    @cached_property
    def _stage_image(self):
        return crop(self.device.image, self._stage_detect_area, copy=False)

    @cached_property
    def _stage_image_gray(self):
        return rgb2gray(self._stage_image)

    @Config.when(SERVER='en')
    def campaign_extract_name_image(self, image):
        digits = []

        if 'normal' in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_CLEAR,
                image, self._stage_image_gray,
                name_offset=(70, 12), name_size=(60, 14)
            )
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_PERCENT,
                image, self._stage_image_gray,
                name_offset=(45, 3), name_size=(60, 14)
            )
        if 'half' in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_HALF_PERCENT,
                image, self._stage_image_gray,
                name_offset=(48, 0), name_size=(60, 16)
            )
        if 'blue' in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_BLUE_PERCENT,
                image, extract_letters(self._stage_image, letter=(255, 255, 255), threshold=153),
                name_offset=(55, 0), name_size=(60, 16)
            )
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_BLUE_CLEAR,
                image, extract_letters(self._stage_image, letter=(99, 223, 239), threshold=153),
                name_offset=(60, 12), name_size=(60, 16)
            )
        if 'green' in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_GREEN_CLEAR,
                image, self._stage_image_gray,
                name_offset=(60, 0), name_size=(60, 22)
            )
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_PERCENT,
                image, self._stage_image_gray,
                similarity=0.6,
                name_offset=(52, 0), name_size=(60, 22)
            )
        if '20240725' in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_CLEAR_20240725,
                image, self._stage_image_gray,
                name_offset=(73, -4), name_size=(60, 22)
            )

        return digits

    @Config.when(SERVER=None)
    def campaign_extract_name_image(self, image):
        """
        查找所有关卡入口并处理活动差异。
        关卡入口设置参见 ManualConfig.STAGE_ENTRANCE。

        Args:
            image: 截图。

        Returns:
            list[Button]: 关卡入口按钮列表。
        """
        digits = []

        if 'normal' in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_CLEAR,
                image, self._stage_image_gray,
                name_offset=(75, 9), name_size=(60, 16)
            )
            # 2024.04.11 游戏客户端出现 bug，TEMPLATE_STAGE_CLEAR 周围出现随机损坏的素材
            # digits += self.campaign_match_multi(
            #     TEMPLATE_STAGE_CLEAR_SMALL,
            #     image, self._stage_image_gray,
            #     name_offset=(53, 2), name_size=(60, 16)
            # )
            # digits += self.campaign_match_multi(
            #     TEMPLATE_STAGE_HALF_PERCENT,
            #     image, self._stage_image_gray,
            #     name_offset=(48, 0), name_size=(60, 16)
            # )
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_PERCENT,
                image, self._stage_image_gray,
                name_offset=(48, 0), name_size=(60, 16)
            )
        if 'half' in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_HALF_PERCENT,
                image, self._stage_image_gray,
                name_offset=(48, 0), name_size=(60, 16)
            )
        if 'blue' in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_BLUE_PERCENT,
                image, extract_letters(self._stage_image, letter=(255, 255, 255), threshold=153),
                name_offset=(55, 0), name_size=(60, 16)
            )
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_BLUE_CLEAR,
                image, extract_letters(self._stage_image, letter=(99, 223, 239), threshold=153),
                name_offset=(60, 12), name_size=(60, 16)
            )
        if 'green' in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_GREEN_CLEAR,
                image, self._stage_image_gray,
                name_offset=(60, 0), name_size=(60, 22)
            )
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_PERCENT,
                image, self._stage_image_gray,
                similarity=0.6,
                name_offset=(52, 0), name_size=(60, 22)
            )
        if '20240725' in self.config.STAGE_ENTRANCE:
            digits += self.campaign_match_multi(
                TEMPLATE_STAGE_CLEAR_20240725,
                image, self._stage_image_gray,
                name_offset=(73, -4), name_size=(60, 22)
            )

        return digits

    @staticmethod
    def _extract_stage_name(image):
        """
        从完整关卡名称图像中提取关卡编号区域。

        Args:
            image: 裁剪后的完整关卡名称图像，如 '3-4 Counterattack!'。

        Returns:
            关卡名称区域坐标，如输入图像中 '3-4' 的坐标。
        """
        x_skip = 10
        interval = 5
        x_color = np.convolve(np.mean(image, axis=0), np.ones(interval), 'valid') / interval
        x_list = np.where(x_color[x_skip:] > 245)[0]
        if x_list is None or len(x_list) == 0:
            logger.warning('数字与文本之间未找到间隔。')
            area = (0, 0, image.shape[1], image.shape[0])
        else:
            area = (0, 0, x_list[0] + 1 + x_skip, image.shape[0])
        return np.array(area) + (-3, -7, 3, 7)

    def _get_stage_name(self, image):
        """
        从给定图像中解析关卡名称。
        设置属性：
        self.campaign_chapter: str，当前章节名称。
        self.stage_entrance: dict，键为关卡名称(str)，值为进入关卡的按钮(Button)。

        Args:
            image (np.ndarray): 截图。
        """
        self.stage_entrance = {}
        del_cached_property(self, '_stage_image')
        del_cached_property(self, '_stage_image_gray')
        buttons = self.campaign_extract_name_image(image)
        del_cached_property(self, '_stage_image')
        del_cached_property(self, '_stage_image_gray')
        if len(buttons) == 0:
            logger.info('未找到关卡。')
            raise CampaignNameError

        ocr = Ocr(buttons, name='campaign', letter=(255, 255, 255), threshold=128,
                  alphabet='0123456789ABCDEFGHIJKLMNPQRSTUVWXYZ-')
        result = ocr.ocr(image)
        if not isinstance(result, list):
            result = [result]
        result = [self._campaign_ocr_result_process(res) for res in result]

        chapter = [self._campaign_separate_name(res)[0] for res in result if res]
        chapter = list(filter(('').__ne__, chapter))
        if not chapter:
            raise CampaignNameError

        counter = collections.Counter(chapter)
        self.campaign_chapter = counter.most_common()[0][0]

        if self.campaign_chapter == 0 or self.campaign_chapter == '0':
            # ['0F', 'F-IB', 'IGI']
            raise CampaignNameError

        # OCR 完成后恢复按钮属性。
        # 这些按钮将作为 `MapOperation.enter_map()` 的关卡入口。
        # button.area: 关卡图标区域，如 'CLEAR' 和 '%'。
        # button.color: 关卡图标颜色。
        # button.button: 关卡图标区域。
        # button.name: 关卡名称，来自 OCR 结果。
        for name, button in zip(result, buttons):
            button.area = button.button
            button.name = name
            self.stage_entrance[name] = button

        logger.attr('Chapter', self.campaign_chapter)
        logger.attr('Stage', ', '.join(self.stage_entrance.keys()))

    def handle_get_chapter_additional(self):
        """
        获取章节时的额外处理。

        Returns:
            bool: 是否进行了点击操作。
        """
        if self.appear(WITHDRAW, offset=(30, 30)):
            logger.warning(f'get_chapter_index: WITHDRAW appears')
            raise CampaignNameError

    def get_chapter_index(self, skip_first_screenshot=True):
        """
        获取当前章节索引，供 ui_ensure_index 使用。

        Args:
            skip_first_screenshot: 是否跳过首次截图。

        Returns:
            int: 章节索引。
        """
        timeout = Timer(2, count=4).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if timeout.reached():
                raise CampaignNameError
            image = self.device.image
            try:
                self._get_stage_name(image)
                break
            except (IndexError, CampaignNameError):
                pass

            if self.handle_get_chapter_additional():
                continue

        return self._campaign_get_chapter_index(self.campaign_chapter)
