from module.combat.assets import GET_ITEMS_1
from module.logger import logger
from module.meowfficer.assets import *
from module.meowfficer.base import MeowfficerBase
from module.ocr.ocr import Digit, DigitCounter
from module.ui.assets import MEOWFFICER_GOTO_DORMMENU

BUY_MAX = 15
BUY_PRIZE = 1500
MEOWFFICER = DigitCounter(OCR_MEOWFFICER, letter=(140, 113, 99), threshold=64)
MEOWFFICER_CHOOSE = Digit(OCR_MEOWFFICER_CHOOSE, letter=(140, 113, 99), threshold=64)
MEOWFFICER_COINS = Digit(OCR_MEOWFFICER_COINS, letter=(99, 69, 41), threshold=64)


class MeowfficerBuy(MeowfficerBase):
    def meow_choose(self, count) -> bool:
        """
        Pages:
            in: page_meowfficer
            out: MEOWFFICER_BUY

        Args:
            count (int): 0 to 15.

        Returns:
            bool: If success.
        """
        remain, bought, total = MEOWFFICER.ocr(self.device.image)
        logger.attr('Meowfficer_remain', remain)

        # Check buy status
        if total != BUY_MAX:
            logger.warning(f'Invalid meowfficer buy limit: {total}, revise to {BUY_MAX}')
            total = BUY_MAX
            bought = total - remain
        if bought > 0:
            if bought >= count:
                logger.info(f'Already bought {bought} today, stopped')
                return False
            else:
                count -= bought
                logger.info(f'Already bought {bought} today, only need to buy {count} more')

        # Check coins
        coins = MEOWFFICER_COINS.ocr(self.device.image)
        if (coins < BUY_PRIZE) and (remain < total):
            logger.info('Not enough coins to buy one, stopped')
            return False
        elif (count - int(remain == total)) * BUY_PRIZE > coins:
            count = coins // BUY_PRIZE + int(remain == total)
            logger.info(f'Current coins only enough to buy {count}')

        self.meow_enter(MEOWFFICER_BUY_ENTER, check_button=MEOWFFICER_BUY)
        self.ui_ensure_index(count, letter=MEOWFFICER_CHOOSE, prev_button=MEOWFFICER_BUY_PREV,
                             next_button=MEOWFFICER_BUY_NEXT, skip_first_screenshot=True)
        return True

    def meow_confirm(self, skip_first_screenshot=True) -> None:
        """
        Pages:
            in: MEOWFFICER_BUY
            out: page_meowfficer
        """
        # Here uses a simple click, to avoid clicking MEOWFFICER_BUY multiple times.
        # Retry logic is in meow_buy()
        logger.hr('Meow confirm')
        executed = False
        with self.stat.new(
                genre="meowfficer_buy",
                method=self.config.DropRecord_MeowfficerBuy,
        ) as drop:
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                if self.appear(MEOWFFICER_BUY, offset=(20, 20), interval=3):
                    if executed:
                        self.device.click(MEOWFFICER_GOTO_DORMMENU)
                    else:
                        self.device.click(MEOWFFICER_BUY)
                    continue
                if self.handle_meow_popup_confirm():
                    executed = True
                    continue
                if self.appear_then_click(MEOWFFICER_BUY_SKIP, interval=3):
                    executed = True
                    continue
                if self.appear(GET_ITEMS_1, offset=5, interval=3):
                    if drop.save is True:
                        drop.handle_add(self, before=2)
                    self.device.click(MEOWFFICER_BUY_SKIP)
                    self.interval_clear(MEOWFFICER_BUY)
                    executed = True
                    continue
                # Rare case that MEOWFFICER_INFO popups here
                if self.meow_additional():
                    continue

                # End
                if self.match_template_color(MEOWFFICER_BUY_ENTER, offset=(20, 20)):
                    break

    def meow_buy(self) -> bool:
        """
        Pages:
            in: page_meowfficer
            out: page_meowfficer
        """
        logger.hr('Meowfficer buy', level=1)

        for _ in range(3):
            if self.meow_choose(count=self.config.Meowfficer_BuyAmount):
                self.meow_confirm()
            else:
                return True

        logger.warning('Too many trial in meowfficer buy, stopped.')
        return False

    def meow_overflow_buy(self, overflow_coins):
        """金币溢出时购买猫箱，直到金币降至阈值以下。

        根据当前金币与溢出阈值的差值计算需要购买的猫箱数量，
        考虑每日15个购买限制和首抽免费机制。
        不依赖金币OCR判断是否触发购买（由调用方判断），
        仅负责在指挥喵界面执行购买操作。

        Args:
            overflow_coins (int): 金币溢出阈值，金币超过此值时购买猫箱

        Pages:
            in: page_meowfficer
            out: page_meowfficer
        """
        logger.hr('Meowfficer overflow buy', level=1)

        # OCR识别剩余购买次数
        remain, bought, total = MEOWFFICER.ocr(self.device.image)
        logger.attr('Meowfficer_remain', remain)
        logger.attr('Meowfficer_bought', bought)

        # 每日限制检查
        if total != BUY_MAX:
            logger.warning(f'Invalid meowfficer buy limit: {total}, revise to {BUY_MAX}')
            total = BUY_MAX
            bought = total - remain

        if bought >= BUY_MAX:
            logger.info(f'Already bought {bought} today, reached daily limit, skip')
            return

        # OCR识别金币
        coins = MEOWFFICER_COINS.ocr(self.device.image)
        logger.attr('Meowfficer_coins', coins)

        if coins <= overflow_coins:
            logger.info(f'Coins {coins} <= threshold {overflow_coins}, skip')
            return

        # 计算溢出购买数量
        today_left = total - bought
        # 向上取整：需要购买多少个猫箱才能将金币降到阈值以下
        overflow_count = -(-(coins - overflow_coins) // BUY_PRIZE)
        # 限制在今日剩余数量内
        count = min(overflow_count, today_left)

        # 考虑首抽免费：如果剩余=总数（一个都没买），第一个免费
        free = 1 if remain == total else 0
        # 检查金币是否足够
        affordable = coins // BUY_PRIZE + free
        if count > affordable:
            count = affordable
            logger.info(f'Coins only enough for {count} meowfficers')

        if count <= 0:
            logger.info('No meowfficer to buy, skip')
            return

        logger.info(f'Overflow buy count: {count} (overflow_count={overflow_count}, today_left={today_left})')

        # 执行购买
        # 传入总共需要达到的数量（已买 + 还需买），meow_choose 会自动计算差额
        if self.meow_choose(count=count + bought):
            self.meow_confirm()
        else:
            logger.info('Meowfficer overflow buy skipped by meow_choose')
