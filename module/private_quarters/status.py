import module.config.server as server
from module.ocr.ocr import Digit, DigitCounter
from module.private_quarters.assets import *
from module.shop.shop_status import ShopStatus

if server.server in ['cn', 'jp', 'tw']:
    OCR_DAILY_COUNT = DigitCounter(PRIVATE_QUARTERS_DAILY_COUNT, letter=(218, 219, 221))
else:
    OCR_DAILY_COUNT = DigitCounter(PRIVATE_QUARTERS_DAILY_COUNT, letter=(255, 247, 247))

if server.server != 'jp':
    OCR_SHOP_GOLD_COINS = Digit(PRIVATE_QUARTERS_SHOP_GOLD_COINS, letter=(239, 239, 239), name='OCR_SHOP_GOLD_COINS')
else:
    OCR_SHOP_GOLD_COINS = Digit(PRIVATE_QUARTERS_SHOP_GOLD_COINS, letter=(201, 201, 201), name='OCR_SHOP_GOLD_COINS')

if server.server != 'jp':
    OCR_SHOP_GEMS = Digit(PRIVATE_QUARTERS_SHOP_GEMS, letter=(255, 243, 82), name='OCR_SHOP_GEMS')
else:
    OCR_SHOP_GEMS = Digit(PRIVATE_QUARTERS_SHOP_GEMS, letter=(190, 180, 82), name='OCR_SHOP_GEMS')

OCR_SHOP_PRICE = Digit([], letter=(64, 72, 77), name='OCR_SHOP_PRICE')


class PQStatus(ShopStatus):
    def status_get_gold_coins(self):
        """
        OCR 识别商店金币数量。

        Returns:
            int: 金币数量

        Pages:
            in: 私人宿舍商店页
        """
        amount = OCR_SHOP_GOLD_COINS.ocr(self.device.image)
        return amount

    def status_get_gems(self):
        """
        OCR 识别商店钻石数量。

        Returns:
            int: 钻石数量

        Pages:
            in: 私人宿舍商店页
        """
        amount = OCR_SHOP_GEMS.ocr(self.device.image)
        return amount

    def status_get_daily_count(self):
        """
        OCR 识别每日互动剩余次数。

        Returns:
            int: 剩余互动次数

        Pages:
            in: 私人宿舍主页
        """
        count, _, _ = OCR_DAILY_COUNT.ocr(self.device.image)
        return count
