from datetime import datetime, timedelta

import module.config.server as server
from module.base.decorator import Config
from module.base.filter import Filter
from module.base.utils import *
from module.commission.project_data import *
from module.logger import logger
from module.ocr.ocr import Duration, Ocr
from module.reward.assets import *

COMMISSION_FILTER = Filter(
    regex=re.compile(
        '(major|daily|extra|urgent|night)?'
        '-?'
        '(resource|chip|event|drill|part|cube|oil|book|retrofit|box|gem|ship)?'
        '-?'
        '(\d\d?:\d\d)?'
        '(\d\d?.\d\d?|\d\d?)?'
    ),
    attr=('category_str', 'genre_str', 'duration_hm', 'duration_hour'),
    preset=('shortest', 'expire')
)


class SuffixOcr(Ocr):
    """后缀 OCR 识别器，用于识别委托名称末尾的罗马数字后缀。

    预处理时裁剪掉图像右侧空白区域，只保留后缀部分以提高识别准确率。
    """

    def pre_process(self, image):
        """预处理图像，裁剪右侧空白区域以聚焦后缀字符。

        通过检测每列像素最小值定位文本右边界，再向左回退若干像素
        以确保完整保留后缀字符。日服字符较宽，需要更大的回退量。

        Args:
            image: 输入的灰度图像。

        Returns:
            裁剪后的图像。
        """
        image = super().pre_process(image)

        left = np.where(np.min(image[5:-5, :], axis=0) < 85)[0]
        # 日服字符较宽，需要回退更多像素
        if server.server in ['jp']:
            look_back = 21
        else:
            look_back = 18
        if len(left):
            image = image[:, left[-1] - look_back:]

        return image


class Commission:
    """单条委托信息。

    封装从委托界面截图中解析出的所有属性，包括名称、类型、状态、时长等。
    支持 CN/EN/JP/TW 四个服务器，通过 `@Config.when` 装饰器分发不同的解析逻辑。
    """

    # 进入委托详情的按钮
    button: Button
    # OCR 识别出的委托名称
    name: str
    # 委托名称是否解析成功
    valid: bool
    # 罗马数字后缀，委托无后缀时可能识别错误
    # 值: ⅠⅡⅢⅤⅣⅥ
    suffix: str
    # 委托类型名称，定义在 project_data.py 中
    # 值: major_comm, daily_resource, urgent_cube, ...
    genre: str
    # 委托状态
    # 值: finished, running, pending
    status: str
    # 委托执行时长
    duration: timedelta
    # 过期时间，仅紧急委托有值，其他委托为 None
    expire: timedelta
    # 过滤器用分类
    # 值: major|daily|extra|urgent|night
    category_str: str
    # 过滤器用类型
    # 值: resource|chip|event|drill|part|cube|oil|book|retrofit|box|gem|ship
    genre_str: str
    # 时长（小时），如 0.5, 1, 1.16, 2.5
    duration_hour: str
    # 时长（HH:MM 格式），如 1:30, 1:45, 2:00, 8:00, 12:00
    duration_hm: str

    def __init__(self, image, y, config):
        """从截图中解析委托信息。

        根据 y 坐标确定委托条目的裁剪区域，调用 commission_parse 解析各项属性，
        并计算过滤器所需的分类和时长字段。

        Args:
            image: 游戏截图。
            y: 委托条目底部的 y 坐标。
            config: AzurPilot 配置对象。
        """
        self.config = config
        self.y = y
        self.area = (188, y - 119, 1199, y)
        self.image = image
        self.valid = True
        self.commission_parse()

        if not self.duration.total_seconds():
            self.valid = False

        self.create_time = datetime.now()
        self.repeat_count = 1
        self.category_str = 'unknown'
        self.genre_str = 'unknown'
        self.duration_hour = 'unknown'
        self.duration_hm = 'unknown'
        if self.valid:
            self.category_str, self.genre_str = self.genre.split('_', 1)
            self.duration_hour = str(int(self.duration.total_seconds() / 36) / 100).strip('.0')
            self.duration_hm = str(self.duration).rsplit(':', 1)[0]

    @Config.when(SERVER='en')
    def commission_parse(self):
        """解析委托信息（EN 服务器）。

        EN 服委托名称较长，OCR 裁剪区域与 CN 不同。
        需要对常见 OCR 识别错误进行修正（如 DALY -> DAILY）。

        解析内容：名称、后缀、时长、过期时间、状态。
        """
        # 名称识别——EN 服名称较长，使用更宽的裁剪区域
        area = area_offset((131, 23, 409, 53), self.area[0:2])
        button = Button(area=area, color=(), button=area, name='COMMISSION')
        ocr = Ocr(button, lang='cnocr')
        self.button = button
        result = ocr.ocr(self.image).upper()
        # 修正常见 OCR 识别错误
        result = result.replace('DALY', 'DAILY')
        result = result.replace('NVB', 'NYB')
        result = result.replace('PYEIN', 'VEIN').replace('YEIN', 'VEIN')
        self.name = result
        self.genre = self.commission_name_parse(self.name)

        # 后缀识别
        ocr = SuffixOcr(button, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet='IV')
        self.suffix = self.beautify_name(ocr.ocr(self.image))

        # 执行时长
        area = area_offset((290, 68, 390, 95), self.area[0:2])
        button = Button(area=area, color=(), button=area, name='DURATION')
        ocr = Duration(button)
        self.duration = ocr.ocr(self.image)

        # 过期时间——仅紧急委托有
        area = area_offset((-49, 68, -45, 84), self.area[0:2])
        button = Button(area=area, color=(189, 65, 66),
                        button=area, name='IS_URGENT')
        if button.appear_on(self.image, threshold=30):
            area = area_offset((-49, 67, 45, 94), self.area[0:2])
            button = Button(area=area, color=(), button=area, name='EXPIRE')
            ocr = Duration(button)
            self.expire = ocr.ocr(self.image)
        else:
            self.expire = timedelta(seconds=0)

        # 状态识别——通过 RGB 颜色通道判断
        area = area_offset((179, 71, 187, 93), self.area[0:2])
        dic = {
            0: 'finished',
            1: 'running',
            2: 'pending'
        }
        color = np.array(get_color(self.image, area))
        if self.genre == 'daily_event':
            color -= [50, 30, 20]
        self.status = dic[int(np.argmax(color))]

    @Config.when(SERVER='jp')
    def commission_parse(self):
        """解析委托信息（JP 服务器）。

        JP 服 OCR 使用日文模型，需修正阵营缩写识别错误。
        解析内容：名称、后缀、时长、过期时间、状态。
        """
        # 名称识别
        area = area_offset((176, 23, 420, 53), self.area[0:2])
        button = Button(area=area, color=(), button=area, name='COMMISSION')
        ocr = Ocr(button, letter=(201, 201, 201), lang='jp')
        self.button = button
        result = ocr.ocr(self.image).upper()
        # 修正阵营缩写：NB -> NYB，BW -> BIW
        result = result.replace('NB', 'BYB').replace('BW', 'BIW')
        self.name = result
        self.genre = self.commission_name_parse(self.name)

        # 后缀识别
        ocr = SuffixOcr(button, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet='IV')
        self.suffix = self.beautify_name(ocr.ocr(self.image))

        # 执行时长
        area = area_offset((290, 68, 390, 95), self.area[0:2])
        button = Button(area=area, color=(), button=area, name='DURATION')
        ocr = Duration(button)
        self.duration = ocr.ocr(self.image)

        # 过期时间——仅紧急委托有
        area = area_offset((-49, 68, -45, 84), self.area[0:2])
        button = Button(area=area, color=(189, 65, 66),
                        button=area, name='IS_URGENT')
        if button.appear_on(self.image, threshold=30):
            area = area_offset((-49, 67, 45, 94), self.area[0:2])
            button = Button(area=area, color=(), button=area, name='EXPIRE')
            ocr = Duration(button)
            self.expire = ocr.ocr(self.image)
        else:
            self.expire = timedelta(seconds=0)

        # 状态识别——通过 RGB 颜色通道判断
        area = area_offset((179, 71, 187, 93), self.area[0:2])
        dic = {
            0: 'finished',
            1: 'running',
            2: 'pending'
        }
        color = np.array(get_color(self.image, area))
        if self.genre == 'daily_event':
            color -= [50, 30, 20]
        self.status = dic[int(np.argmax(color))]

    @Config.when(SERVER='tw')
    def commission_parse(self):
        """解析委托信息（TW 服务器）。

        TW 服繁体中文 OCR 需要修正特定字符的识别错误。
        解析内容：名称、后缀、时长、过期时间、状态。
        """
        # 名称识别
        area = area_offset((176, 23, 420, 53), self.area[0:2])
        button = Button(area=area, color=(), button=area, name='COMMISSION')
        ocr = Ocr(button, lang='tw', threshold=256)
        self.button = button
        result = ocr.ocr(self.image).upper()
        # 训练数据集中没有"艦"字，用"鑑"/"盤"替代后修正
        result = result.replace('鑑', '艦').replace('盤', '艦')
        # 修正"支援土蒙爾島" -> "支援土豪爾島"
        result = result.replace('土蒙爾', '土豪爾')
        # 修正"资源原" -> "资源"
        result = result.replace('源原', '源')
        self.name = result
        self.genre = self.commission_name_parse(self.name)

        # 后缀识别
        ocr = SuffixOcr(button, lang='azur_lane', letter=(255, 255, 255), threshold=128, alphabet='IV')
        self.suffix = self.beautify_name(ocr.ocr(self.image))

        # 执行时长
        area = area_offset((290, 68, 390, 95), self.area[0:2])
        button = Button(area=area, color=(), button=area, name='DURATION')
        ocr = Duration(button)
        self.duration = ocr.ocr(self.image)

        # 过期时间——仅紧急委托有
        area = area_offset((-49, 68, -45, 84), self.area[0:2])
        button = Button(area=area, color=(189, 65, 66),
                        button=area, name='IS_URGENT')
        if button.appear_on(self.image, threshold=30):
            area = area_offset((-49, 67, 45, 94), self.area[0:2])
            button = Button(area=area, color=(), button=area, name='EXPIRE')
            ocr = Duration(button)
            self.expire = ocr.ocr(self.image)
        else:
            self.expire = timedelta(seconds=0)

        # 状态识别——通过 RGB 颜色通道判断
        area = area_offset((179, 71, 187, 93), self.area[0:2])
        dic = {
            0: 'finished',
            1: 'running',
            2: 'pending'
        }
        color = np.array(get_color(self.image, area))
        if self.genre == 'daily_event':
            color -= [50, 30, 20]
        self.status = dic[int(np.argmax(color))]

    @Config.when(SERVER=None)
    def commission_parse(self):
        """解析委托信息（CN 服务器，默认回退）。

        CN 服后缀直接从名称末尾提取罗马数字，不使用独立 OCR。
        解析内容：名称、后缀、时长、过期时间、状态。
        """
        # 名称识别
        area = area_offset((176, 23, 420, 53), self.area[0:2])
        button = Button(area=area, color=(), button=area, name='COMMISSION')
        ocr = Ocr(button, lang='cnocr', threshold=256)
        self.button = button
        result = ocr.ocr(self.image).upper()
        # 修正"资源原" -> "资源"
        result = result.replace('源原', '源')
        self.name = result
        self.genre = self.commission_name_parse(self.name)

        # 后缀——直接从名称末尾提取罗马数字
        self.suffix = self.beautify_name(''.join(c for c in result[-4:] if c in 'IV'))

        # 执行时长
        area = area_offset((290, 68, 390, 95), self.area[0:2])
        button = Button(area=area, color=(), button=area, name='DURATION')
        ocr = Duration(button)
        self.duration = ocr.ocr(self.image)

        # 过期时间——仅紧急委托有
        area = area_offset((-49, 68, -45, 84), self.area[0:2])
        button = Button(area=area, color=(189, 65, 66),
                        button=area, name='IS_URGENT')
        if button.appear_on(self.image, threshold=30):
            area = area_offset((-49, 67, 45, 94), self.area[0:2])
            button = Button(area=area, color=(), button=area, name='EXPIRE')
            ocr = Duration(button)
            self.expire = ocr.ocr(self.image)
        else:
            self.expire = timedelta(seconds=0)

        # 状态识别——通过 RGB 颜色通道判断
        area = area_offset((179, 71, 187, 93), self.area[0:2])
        dic = {
            0: 'finished',
            1: 'running',
            2: 'pending'
        }
        color = np.array(get_color(self.image, area))
        if self.genre == 'daily_event':
            color -= [50, 30, 20]
        self.status = dic[int(np.argmax(color))]

    def __str__(self):
        """返回委托的可读字符串表示，包含名称、类型、状态和时长。"""
        name = f'{self.name} | {self.suffix}'
        if not self.valid:
            return f'{name} (Invalid)'
        info = {'Genre': self.genre, 'Status': self.status, 'Duration': self.duration}
        if self.expire:
            info['Expire'] = self.expire
        if self.repeat_count > 1:
            info['Repeat'] = self.repeat_count
        info = ', '.join([f'{k}: {v}' for k, v in info.items()])
        return f'{name} ({info})'

    def __eq__(self, other):
        """判断两个委托是否为同一委托。

        通过类型、状态、后缀、时长（允许 120 秒误差）、过期时间和重复次数
        进行综合比较。紧急物资委托还需匹配阵营标签（NYB/BIW）。

        Args:
            other: 要比较的委托对象。

        Returns:
            是否为同一委托。
        """
        if not isinstance(other, Commission):
            return False
        threshold = timedelta(seconds=120)
        if not self.valid or not other.valid:
            return False
        if self.genre != other.genre or self.status != other.status:
            return False
        if self.category_str == 'daily':
            if self.suffix != other.suffix:
                return False
        if self.genre == 'urgent_box':
            for tag in ['NYB', 'BIW']:
                if tag in self.name.upper() and tag not in other.name.upper():
                    return False
                if tag not in self.name.upper() and tag in other.name.upper():
                    return False
        if (other.duration < self.duration - threshold) or (other.duration > self.duration + threshold):
            return False
        if (not self.expire and other.expire) or (self.expire and not other.expire):
            return False
        if self.expire and other.expire:
            if (other.expire < self.expire - threshold) or (other.expire > self.expire + threshold):
                return False
        if self.repeat_count != other.repeat_count:
            return False
        if self.genre in ['extra_oil', 'night_oil'] and self.suffix != other.suffix:
            return False

        return True

    def __hash__(self):
        """返回委托的哈希值，基于类型和名称。"""
        return hash(f'{self.genre}_{self.name}')

    def parse_time(self, string):
        """解析时间字符串为 timedelta 对象。

        Args:
            string: 时间字符串，格式如 '01:00:00', '05:47:10', '17:50:51'。

        Returns:
            解析后的 timedelta 实例，解析失败时返回 None。
        """
        # OCR 常将 0 识别为 D，此处修正
        string = string.replace('D', '0')
        result = re.search('(\d+):(\d+):(\d+)', string)
        if not result:
            logger.warning(f'Invalid time string: {string}')
            self.valid = False
            return None
        else:
            result = [int(s) for s in result.groups()]
            return timedelta(hours=result[0], minutes=result[1], seconds=result[2])

    @Config.when(SERVER='en')
    def commission_name_parse(self, string):
        """根据委托名称匹配委托类型（EN 服务器）。

        先判断是否为活动委托，再遍历 EN 名称字典进行关键词匹配。

        Args:
            string: 委托名称，如 'DAILY RESOURCE EXTRACTION'。

        Returns:
            委托类型字符串，如 'urgent_gem'，无法识别时返回空字符串。
        """
        if self.is_event_commission():
            return 'daily_event'
        for key, value in dictionary_en.items():
            for keyword in value:
                if keyword in string:
                    return key

        logger.warning(f'Name with unknown genre: {string}')
        self.valid = False
        return ''

    @Config.when(SERVER='jp')
    def commission_name_parse(self, string):
        """根据委托名称匹配委托类型（JP 服务器）。

        使用 Levenshtein 距离进行模糊匹配，允许最多 2 个字符的 OCR 识别误差。
        先判断是否为活动委托，再遍历 JP 名称字典计算编辑距离。

        Args:
            string: 委托名称，如 '短距離練習航海'。

        Returns:
            委托类型字符串，如 'extra_drill'，无法识别时返回空字符串。
        """
        if self.is_event_commission():
            return 'daily_event'
        import jellyfish
        min_key = ''
        min_distance = 100
        # 移除 ASCII 字符，只保留日文字符进行匹配
        string = re.sub(r'[\x00-\x7F]', '', string)
        for key, value in dictionary_jp.items():
            for keyword in value:
                distance = jellyfish.levenshtein_distance(keyword, string)
                if distance < min_distance:
                    min_key = key
                    min_distance = distance
        if min_distance < 3:
            return min_key

        logger.warning(f'Name with unknown genre: {string}')
        self.valid = False
        return ''

    @Config.when(SERVER='tw')
    def commission_name_parse(self, string):
        """根据委托名称匹配委托类型（TW 服务器）。

        先判断是否为活动委托，再遍历 TW 名称字典进行关键词匹配。

        Args:
            string: 委托名称，如 '日常資源開發'。

        Returns:
            委托类型字符串，如 'daily_resource'，无法识别时返回空字符串。
        """
        if self.is_event_commission():
            return 'daily_event'
        for key, value in dictionary_tw.items():
            for keyword in value:
                if keyword in string:
                    return key

        logger.warning(f'Name with unknown genre: {string}')
        self.valid = False
        return ''

    @Config.when(SERVER=None)
    def commission_name_parse(self, string):
        """根据委托名称匹配委托类型（CN 服务器，默认回退）。

        先判断是否为活动委托，再遍历 CN 名称字典进行关键词匹配。

        Args:
            string: 委托名称，如 'NYB要员护卫'。

        Returns:
            委托类型字符串，如 'urgent_gem'，无法识别时返回空字符串。
        """
        if self.is_event_commission():
            return 'daily_event'
        for key, value in dictionary_cn.items():
            for keyword in value:
                if keyword in string:
                    return key

        logger.warning(f'Name with unknown genre: {string}')
        self.valid = False
        return ''

    def is_event_commission(self):
        """判断是否为活动委托。

        通过检测委托条目左侧区域的颜色来判断。不同时期的活动使用不同的颜色标记，
        当前使用 2023.04.27 度假村复刻活动的粉黄色渐变作为识别依据。

        Returns:
            是否为活动委托。
        """
        # 当前活动委托：粉黄色渐变（度假村复刻 / Idol Master 活动风格）
        area = area_offset((5, 5, 30, 30), self.area[0:2])
        if color_similar(color1=get_color(self.image, area), color2=(235, 173, 161), threshold=30):
            return True

        return False

    def convert_to_night(self):
        """将 extra 类型委托转换为 night 类型。"""
        if self.valid and self.category_str == 'extra':
            self.category_str = 'night'
            self.genre = f'{self.category_str}_{self.genre_str}'

    def convert_to_running(self):
        """将委托状态设为运行中，并将创建时间重置为当前时间。"""
        if self.valid:
            self.status = 'running'
            self.create_time = datetime.now()

    @property
    def finish_time(self):
        """委托预计完成时间。

        Returns:
            运行中委托的完成时间，非运行状态返回 None。
        """
        if self.valid and self.status == 'running':
            return (self.create_time + self.duration).replace(microsecond=0)
        else:
            return None

    @staticmethod
    def beautify_name(name):
        """将名称末尾的 ASCII 罗马数字转换为 Unicode 特殊字符。

        将 I/II/III/IV/V/VI 替换为对应的 Unicode 罗马数字字符（Ⅰ~Ⅵ）。

        Args:
            name: 原始名称，可能包含 ASCII 罗马数字后缀。

        Returns:
            转换后的名称。
        """
        name = name.strip()
        name = re.sub(r'VI$', 'Ⅵ', name)
        name = re.sub(r'IV$', 'Ⅳ', name)
        name = re.sub(r'V$', 'Ⅴ', name)
        name = re.sub(r'III$', 'Ⅲ', name)
        name = re.sub(r'II$', 'Ⅱ', name)
        name = re.sub(r'I$', 'Ⅰ', name)
        return name
