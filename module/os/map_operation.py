from module.base.decorator import Config
from module.base.timer import Timer
from module.base.utils import *
from module.exception import MapDetectionError, ScriptError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.os.assets import *
from module.os.globe_zone import Zone
from module.os.map_fleet_selector import OSFleetSelector
from module.os_handler.assets import AUTO_SEARCH_REWARD, EXCHANGE_CHECK
from module.os_handler.map_order import MapOrderHandler
from module.os_handler.mission import MissionHandler
from module.os_handler.port import PortHandler
from module.os_handler.storage import StorageHandler
from module.ui.assets import BACK_ARROW, OS_CHECK


def _remove_zone_suffix(name, suffixes, trim_chars=''):
    while trim_chars and any(name.endswith(char) for char in trim_chars):
        name = name[:-1]
    for suffix in suffixes:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


class OSMapOperation(MapOrderHandler, MissionHandler, PortHandler, StorageHandler, OSFleetSelector):
    zone: Zone
    is_zone_name_hidden = False

    def is_meowfficer_searching(self):
        """
        Returns:
            bool: 是否有指挥喵正在搜索中。

        Page:
            in: IN_MAP
        """
        return self.appear(MEOWFFICER_SEARCHING, offset=(10, 10))

    def no_meowfficer_searching(self):
        """
        Returns:
            bool: 是否没有指挥喵搜索中且没有自动搜索奖励。

        Page:
            in: IN_MAP
        """
        return not self.appear(AUTO_SEARCH_REWARD, offset=(50, 50)) and not self.is_meowfficer_searching()

    def get_meowfficer_searching_percentage(self):
        """
        Returns:
            float: 指挥喵搜索进度百分比，范围 0 到 1。

        Pages:
            in: IN_MAP, is_meowfficer_searching == True
        """
        return color_bar_percentage(
            self.device.image, area=MEOWFFICER_SEARCHING_PERCENTAGE.area, prev_color=(74, 223, 255))

    @Config.when(SERVER='en')
    def get_zone_name(self):
        # 仅用于 EN 服务器
        ocr = Ocr(MAP_NAME, lang='cnocr', letter=(206, 223, 247), threshold=96, name='OCR_OS_MAP_NAME')
        name = ocr.ocr(self.device.image)
        name = "".join(name.split())
        name = name.lower()
        name = name.strip('\\/-—–－')
        if '-' in name:
            name = name.split('-')[0]
        if 'é' in name:  # 地中海名称映射
            name = name.replace('é', 'e')
        if 'nvcity' in name:  # NY City 港口 OCR 误读 'Y' 为 'V'
            name = 'nycity'
        if 'cibraltar' in name:
            name = 'gibraltar'
        # OCR 偶尔误读修正
        name = name.replace('sate', 'safe')
        self.is_zone_name_hidden = 'safe' in name

        # OCR 偶尔误读，热修复
        name = name.replace('pasage', 'passage')
        name = name.replace('shef', 'shelf')
        name = name.replace('nnocean', 'naocean')
        # A OceanwsectorB-Safe zone 修正
        name = re.sub('^aocean', 'naocean',  name)

        # `-` 缺失或因字体大小被读为 '.'
        name = name.replace('safe', '')
        name = name.replace('zone', '')
        if name.endswith('.'):
            name = name[0:-1]
        return name

    @Config.when(SERVER='jp')
    def get_zone_name(self):
        # 仅用于 JP 服务器
        ocr = Ocr(MAP_NAME, lang='jp', letter=(157, 173, 192), threshold=127, name='OCR_OS_MAP_NAME')
        name = ocr.ocr(self.device.image)
        name = name.replace(' ', '')
        # 将各种破折号标准化为连字符
        import re
        name = re.sub(r'[\\/—–－−]', '-', name)
        name = name.strip('-')
        self.is_zone_name_hidden = '安全' in name
        # 移除标点符号
        for char in '・':
            name = name.replace(char, '')
        # 移除'異常海域'和'セイレーン要塞海域'
        if '異' in name:
            name = name.split('異')[0]
        if 'セ' in name:
            name = name.split('セ')[0]
        
        if '-' in name:
            name = name.split('-')[0]
        else:
            # 移除 JP OCR 末尾的'安全海域'或'秘密海域'。
            name = _remove_zone_suffix(
                name,
                ('安全海域', '秘密海域', '異常海域', '要塞海域', '安全', '秘密', '異常', '要塞'),
            )
        # 汉字'一'、'力'和'卜'不使用，而片假名'ー'、'カ'和'ト'有时被误读为汉字。
        # 片假名'ペ'可能被误读为平假名'ぺ'。
        name = name.replace('一', 'ー').replace('力', 'カ').replace('卜', 'ト').replace('ぺ', 'ペ')
        name = name.replace('ジブフルタル', 'ジブラルタル')
        name = name.replace('タント', 'タラント').replace('タフント', 'タラント')
        name = name.replace('N海域', 'NA海域')
        # リバプル -> リバープール
        name = name.replace('リバプル', 'リバープール')
        name = name.replace('リバープル', 'リバープール')
        name = name.replace('リバプール', 'リバープール')
        return name

    @Config.when(SERVER='tw')
    def get_zone_name(self):
        # 仅用于 TW 服务器
        ocr = Ocr(MAP_NAME, lang='tw', letter=(198, 215, 239), threshold=127, name='OCR_OS_MAP_NAME')
        name = ocr.ocr(self.device.image)
        name = name.replace(' ', '')
        # 将各种破折号标准化为连字符
        import re
        name = re.sub(r'[\\/—–－−一]', '-', name)
        name = name.strip('-')
        self.is_zone_name_hidden = '安全' in name
        # 移除'塞壬要塞海域'
        if '塞' in name:
            name = name.split('塞')[0]
            
        if '-' in name:
            name = name.split('-')[0]
        else:
            # 移除 TW OCR 末尾的'安全海域'、'隱秘海域'、'深淵海域'。
            name = _remove_zone_suffix(
                name,
                ('安全海域', '隱秘海域', '深淵海域', '塞壬要塞海域', '安全', '隱秘', '深淵'),
            )
        return name

    @Config.when(SERVER=None)
    def get_zone_name(self):
        # 仅用于 CN 服务器
        ocr = Ocr(MAP_NAME, lang='cnocr', letter=(214, 231, 255), threshold=127, name='OCR_OS_MAP_NAME')
        name = ocr.ocr(self.device.image)
        name = name.replace(' ', '')
        # 将各种破折号标准化为连字符
        import re
        name = re.sub(r'[\\/—–－−]', '-', name)
        name = name.strip('-')
        self.is_zone_name_hidden = '安全' in name
        if '-' in name:
            name = name.split('-')[0]
        else:
            name = _remove_zone_suffix(
                name,
                ('安全海域', '隐秘海域', '深渊海域', '塞壬要塞海域', '安全', '隐秘', '深渊'),
            )
        return name

    def get_current_zone(self):
        """
        Returns:
            Zone: 当前海域对象。

        Raises:
            MapDetectionError: 解析海域名称失败时抛出。
            ScriptError: 脚本错误时抛出。
        """
        name = self.get_zone_name()
        logger.info(f'Map name processed: {name}')
        try:
            self.zone = self.name_to_zone(name)
        except ScriptError as e:
            raise MapDetectionError(*e.args) from e
        logger.attr('Zone', self.zone)
        self.zone_config_set()
        return self.zone

    def zone_config_set(self):
        if self.zone.region == 5:
            self.config.HOMO_EDGE_COLOR_RANGE = (0, 8)
            self.config.MAP_ENSURE_EDGE_INSIGHT_CORNER = 'bottom'
        else:
            self.config.HOMO_EDGE_COLOR_RANGE = (0, 33)
            self.config.MAP_ENSURE_EDGE_INSIGHT_CORNER = ''

    def zone_init(self, fallback_init=True):
        """
        包装 get_current_zone()，设置 self.zone 为当前海域。
        进入新海域后必须调用此方法。处理地图事件和海域名称从顶部出现的动画。

        Args:
            fallback_init (bool): 无法解析海域名称时，是否从全球地图获取海域。

        Returns:
            Zone: 当前海域对象。

        Raises:
            MapDetectionError: 解析海域名称失败时抛出。
        """
        logger.hr('Zone init')
        self.wait_os_map_buttons()
        logger.info('Get zone name')
        timeout = Timer(1.5, count=5).start()
        for _ in self.loop():
            # 处理弹窗
            if self.handle_map_event():
                timeout.reset()
                continue
            # 游戏 bug：上一个已清理海域的 AUTO_SEARCH_REWARD 弹窗
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3):
                continue
            # 月度重置后 EXCHANGE_CHECK 弹窗
            if self.is_in_globe():
                self.os_globe_goto_map()
                timeout.reset()
                continue
            if self.appear(EXCHANGE_CHECK, offset=(30, 30), interval=3):
                self.device.click(BACK_ARROW)
                timeout.reset()
                continue
            # 处理任务完成标题，可能遮挡地图名称或因额外文本导致 OCR 误读
            if self.is_in_map() and \
                    not self.appear(OS_CHECK, offset=(20, 20)):
                self.wait_until_appear(OS_CHECK)
                timeout.reset()
                continue

            if timeout.reached():
                logger.warning('Zone init timeout')
                break
            if self.is_in_map():
                try:
                    return self.get_current_zone()
                except MapDetectionError:
                    continue
            else:
                timeout.reset()

        if fallback_init:
            logger.warning('Unable to get zone name, get current zone from globe map instead')
            if hasattr(self, 'get_current_zone_from_globe'):
                return self.get_current_zone_from_globe()
            else:
                logger.warning('OperationSiren.get_current_zone_from_globe() not exists')
                if not self.is_in_map():
                    logger.warning('Trying to get zone name, but not in OS map')
                return self.get_current_zone()

    def is_in_special_zone(self):
        """
        Returns:
            bool: 是否在隐秘海域、深渊海域或要塞中。
        """
        return self.appear(MAP_EXIT, offset=(20, 20), similarity=0.75)

    def map_exit(self):
        """
        从隐秘海域、深渊海域或要塞中退出。

        Pages:
            in: is_in_map
            out: is_in_map, 来源海域
        """
        logger.hr('Map exit')
        confirm_timer = Timer(1, count=2)
        changed = False
        for _ in self.loop():
            # 结束条件
            if changed and self.is_in_map():
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()
            # 如果 MAP_EXIT 仍显示，说明尚未退出此海域
            if self.appear(MAP_EXIT, offset=(20, 20), similarity=0.75):
                confirm_timer.reset()

            # 点击
            if self.appear_then_click(MAP_EXIT, offset=(20, 20), interval=3, similarity=0.75):
                continue
            if self.handle_popup_confirm('MAP_EXIT'):
                self.interval_reset(MAP_EXIT)
                continue
            if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50)):
                # 偶尔会出现
                self.device.screenshot_interval_set()
                continue
            if self.handle_map_event():
                self.interval_reset(MAP_EXIT)
                changed = True
                continue

        self.zone_init()
