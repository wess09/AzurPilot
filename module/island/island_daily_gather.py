from module.island.island import *
from datetime import datetime, timedelta
from module.logger import logger

# 采集安全区域（无截图，固定坐标点击用于关闭弹窗）
ISLAND_GATHER_SAFE_AREA = Button(
    area={'cn': (1080, 650, 1180, 700), 'en': (1080, 650, 1180, 700), 'jp': (1080, 650, 1180, 700), 'tw': (1080, 650, 1180, 700)},
    color={'cn': (0, 0, 0), 'en': (0, 0, 0), 'jp': (0, 0, 0), 'tw': (0, 0, 0)},
    button={'cn': (1080, 650, 1180, 700), 'en': (1080, 650, 1180, 700), 'jp': (1080, 650, 1180, 700), 'tw': (1080, 650, 1180, 700)},
    file={'cn': './assets/cn/island/ISLAND_GATHER_SAFE_AREA.png', 'en': './assets/cn/island/ISLAND_GATHER_SAFE_AREA.png', 'jp': './assets/cn/island/ISLAND_GATHER_SAFE_AREA.png', 'tw': './assets/cn/island/ISLAND_GATHER_SAFE_AREA.png'}
)


class IslandDailyGather(Island):
    """
    每日采集逻辑（UI模拟点击版）
    
    执行时间：每日凌晨3:10 和 下午6:00
    流程：
      1. 进入管理界面 → 切换到"采集"页签
      2. 领取已有采集奖励（如果有）
      3. 选择采集目标（_handle_target_selection内依次完成：点击选择目标按钮 → 切换两个toggle开关 → 点击确定）
      4. 依次点击三个"+"按钮，每个点击后：
         a. 等待角色选择界面出现
         b. 对角色列表按"生活等级"升序排序
         c. 选择第一个"非工作中"的角色
      5. 点击"出发"按钮完成采集
    """

    def run(self):
        """
        任务入口：执行采集流程，并根据当前时间调度下次运行
        每日自动运行两次：凌晨3:10 和 下午6:00
        """
        now = datetime.now()

        # 无论何时运行，都执行采集
        logger.info(f"开始执行每日采集 (当前时间: {now.strftime('%H:%M')})")
        self.dispatch_collection()

        # 调度下次运行时间
        next_run = self._schedule_next_run(now)
        self.config.task_delay(target=next_run)
        logger.info(f"下次运行时间: {next_run}")

    def _schedule_next_run(self, now):
        """
        计算下次运行时间
        规则：凌晨执行后调度到下午6:00，下午执行后调度到次日凌晨3:10

        Args:
            now: 当前时间

        Returns:
            datetime: 下次运行时间
        """
        morning = now.replace(hour=3, minute=10, second=0, microsecond=0)
        evening = now.replace(hour=18, minute=0, second=0, microsecond=0)

        if now < morning:
            # 凌晨3:10之前 → 下次下午6:00
            target = evening
        elif now < evening:
            # 凌晨3:10 ~ 下午6:00之间 → 下次下午6:00
            target = evening
        else:
            # 下午6:00之后 → 下次次日凌晨3:10
            target = morning + timedelta(days=1)

        return target

    def dispatch_collection(self):
        """
        完整的UI模拟点击采集流程
        """
        logger.info("=== 开始UI模拟点击采集流程 ===")

        # 1. 进入管理界面
        logger.info("步骤1: 进入管理界面")
        self.goto_management()

        # 2. 进入管理 → 切换到"采集"页签
        logger.info("步骤2: 切换到采集页签")
        self.ui_goto(page_island_postmanage, get_ship=False)
        self.post_manage_mode_collection()

        # 3. 检查并领取已有采集奖励（如果有的话）
        logger.info("步骤3: 检查并领取已有采集奖励")
        self._claim_existing_rewards()

        # 4. 点击"选择采集目标"按钮 → 切换开关 → 点击确定
        #    如果所有采集物已采集完毕，确定时会弹出提示弹窗
        logger.info("步骤4: 处理选择采集目标确认")
        if self._handle_target_selection():
            # 如果成功选择了采集目标，继续后续流程
            # 5. 依次点击三个"+"按钮并选择角色
            for i in range(3):
                logger.info(f"步骤5-{i+1}: 点击第{i+1}个+按钮并选择角色")
                self._click_plus_and_select_character(i)

            # 6. 点击"出发"按钮
            logger.info("步骤6: 点击出发按钮")
            self._click_depart()

            # 7. 处理采集完成页面
            logger.info("步骤7: 等待采集完成并关闭完成页面")
            self._handle_collection_complete()
        else:
            logger.info("所有采集物已采集完毕，跳过后续步骤")

        # 8. 退出管理界面
        self._exit_management()
        logger.info("=== UI模拟点击采集流程完成 ===")

    # ==================== 步骤方法 ====================

    def _claim_existing_rewards(self):
        """
        检查并领取已有采集奖励（到达时间后领取完成）
        """
        max_attempts = 5
        for _ in range(max_attempts):
            self.device.screenshot()
            if self.appear(ISLAND_GET, offset=30):
                logger.info("检测到可领取的奖励，正在领取")
                self.device.click(ISLAND_POST_SAFE_AREA)
                self.device.sleep(0.5)
                continue
            if self.appear_then_click(POST_GET, offset=(50, 0)):
                self.device.sleep(0.5)
                self.device.click(ISLAND_POST_SAFE_AREA)
                self.device.sleep(0.5)
                continue
            # 不再有可领取内容
            break

    def _click_select_target(self):
        """
        点击"选择采集目标"按钮并等待弹窗出现
        """
        while True:
            self.device.screenshot()
            # 检查弹窗是否已经出现
            if self.appear(ISLAND_GATHER_TARGET_POPUP, offset=30):
                logger.info("选择采集目标弹窗已出现")
                break
            # 点击选择采集目标按钮
            if self.appear_then_click(ISLAND_GATHER_SELECT_TARGET, offset=30):
                self.device.sleep(0.5)
                continue
            self.device.sleep(0.3)

    def _toggle_switches(self):
        """
        将弹窗中的两个toggle开关切换至激活状态
        """
        for toggle_name, toggle_on, toggle_off in [
            ("开关A", ISLAND_GATHER_TOGGLE_A_ON, ISLAND_GATHER_TOGGLE_A_OFF),
            ("开关B", ISLAND_GATHER_TOGGLE_B_ON, ISLAND_GATHER_TOGGLE_B_OFF),
        ]:
            self._ensure_toggle_active(toggle_name, toggle_on, toggle_off)

    def _ensure_toggle_active(self, toggle_name, toggle_on, toggle_off):
        """
        确保指定的toggle开关处于激活状态

        Args:
            toggle_name: 开关名称（日志用）
            toggle_on: 开关已激活状态的Button
            toggle_off: 开关未激活状态的Button
        """
        max_attempts = 5
        for attempt in range(max_attempts):
            self.device.screenshot()

            # 检查是否已激活
            if self.appear(toggle_on, offset=10):
                logger.info(f"{toggle_name} 已处于激活状态")
                return True

            # 检查是否未激活，点击切换
            if self.appear(toggle_off, offset=10):
                logger.info(f"{toggle_name} 未激活，点击切换")
                self.device.click(toggle_off)
                self.device.sleep(0.3)
                continue

            # 没有检测到任何状态，尝试点击开关默认位置
            self.device.click(toggle_off)
            self.device.sleep(0.3)

        logger.warning(f"{toggle_name} 切换超时")
        return False

    def _confirm_selection(self):
        """
        点击弹窗中的"确定"按钮关闭弹窗
        最多尝试3次，如果出现已全部采集弹窗则停止
        """
        max_attempts = 3
        for attempt in range(max_attempts):
            self.device.screenshot()

            # 检查是否已全部采集弹窗出现
            if self.appear(ISLAND_GATHER_ALREADY_COLLECTED, offset=30):
                logger.info("检测到「已全部采集」提示弹窗")
                return False

            if self.appear_then_click(ISLAND_GATHER_CONFIRM, offset=30):
                self.device.sleep(0.5)
                continue

            # 弹窗关闭后检测采集页签是否恢复
            if not self.appear(ISLAND_GATHER_TARGET_POPUP, offset=30):
                logger.info("弹窗已关闭，确定成功")
                return True

            self.device.sleep(0.3)

        # 尝试3次后还未关闭，可能是已全部采集弹窗遮盖了目标弹窗
        self.device.screenshot()
        if self.appear(ISLAND_GATHER_ALREADY_COLLECTED, offset=30):
            logger.info("检测到「已全部采集」提示弹窗")
            return False
        # 也可能是目标弹窗仍然开着但确定按钮失效
        if self.appear(ISLAND_GATHER_TARGET_POPUP, offset=30):
            logger.warning("确定按钮点击超时，目标弹窗仍未关闭")
            # 尝试通过安全区域关闭
            self.device.click(ISLAND_GATHER_SAFE_AREA)
            self.device.sleep(0.3)
        return False

    def _click_plus_and_select_character(self, index):
        """
        点击第index个"+"按钮并选择角色

        Args:
            index: 槽位索引 (0, 1, 2)
        """
        plus_buttons = [ISLAND_GATHER_PLUS_A, ISLAND_GATHER_PLUS_B, ISLAND_GATHER_PLUS_C]
        plus_button = plus_buttons[index]

        # 点击"+"按钮
        logger.info(f"点击第{index + 1}个+按钮")
        self.device.click(plus_button)
        self.device.sleep(0.5)

        # 等待角色选择界面出现
        self._wait_for_character_select()

        # 按"生活等级"进行升序排序
        self._sort_by_life_level()

        # 选择第一个"非工作中"的角色
        if not self._select_first_idle_character():
            logger.warning(f"第{index + 1}个槽位未找到可用角色，跳过")

        # 点击确认按钮完成选择
        self.device.sleep(0.3)
        self.appear_then_click(SELECT_UI_CONFIRM)
        self.device.sleep(0.5)
        logger.info(f"第{index + 1}个槽位角色选择完成")

    def _wait_for_character_select(self):
        """
        等待角色选择界面出现
        """
        while True:
            self.device.screenshot()
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                logger.info("角色选择界面已出现")
                break
            self.device.sleep(0.3)

    def _sort_by_life_level(self):
        """
        通过模板匹配检测升序箭头，确保按生活等级升序排序

        按钮颜色不变仅箭头不同，截取按钮区域图像后匹配升序箭头模板来判断
        """
        # 截取排序按钮区域，检测当前是否为升序
        self.device.screenshot()
        sort_area = crop(self.device.image, ISLAND_GATHER_SORT_LIFE.area)
        if TEMPLATE_GATHER_SORT_LIFE_ASC.match(sort_area, similarity=0.8):
            logger.info("当前已是生活等级升序排序，无需操作")
            return

        # 不是升序，点击排序按钮切换到升序
        logger.info("点击生活等级排序按钮切换为升序")
        self.device.click(ISLAND_GATHER_SORT_LIFE)
        self.device.sleep(0.3)

        # 验证是否成功切换为升序
        self.device.screenshot()
        sort_area = crop(self.device.image, ISLAND_GATHER_SORT_LIFE.area)
        if TEMPLATE_GATHER_SORT_LIFE_ASC.match(sort_area, similarity=0.8):
            logger.info("成功切换为生活等级升序排序")
        else:
            logger.warning("升序切换可能未生效，尝试再次点击")
            self.device.click(ISLAND_GATHER_SORT_LIFE)
            self.device.sleep(0.3)

        logger.info("生活等级升序排序完成")

    def _select_first_idle_character(self):
        """
        从当前角色列表中按网格位置顺序选择第一个"非工作中且非选中"的角色
        注：采集界面的角色选择没有黄鸡角色

        Returns:
            bool: 是否成功选择角色
        """
        screenshot = self.device.screenshot()
        characters = self.recognize_all_characters(screenshot)

        if not characters:
            logger.warning("未检测到任何角色")
            return False

        # 按网格位置排序，选择第一个非工作中且非选中的角色
        for char_info in characters:
            if not char_info["is_working"] and not char_info["is_selected"]:
                row, col = char_info["grid_position"]
                logger.info(f"选择空闲且未选中角色: {char_info['character_name']} (位置: {row},{col})")
                button = self.select_character_grid[row, col]
                self.device.click(button)
                self.device.sleep(0.3)
                return True

        # 所有角色都在工作中或已被选中
        logger.warning("所有角色均在工作中或已被选中，无法选择空闲角色")
        return False

    def _click_depart(self):
        """
        点击"出发"按钮开始采集
        """
        max_attempts = 10
        for attempt in range(max_attempts):
            self.device.screenshot()
            if self.appear_then_click(ISLAND_GATHER_DEPART, offset=30):
                self.device.sleep(0.5)
                logger.info("点击出发按钮成功")
                return True
            self.device.sleep(0.3)

        logger.warning("出发按钮点击超时")
        return False

    def _handle_target_selection(self):
        """
        处理选择采集目标的确认流程。
        如果所有采集物已采集完毕，确定时会弹出提示弹窗，需要关闭后退出。

        Returns:
            bool: True=成功选择目标可继续, False=已全部采集需退出
        """
        # 点击"选择采集目标"按钮
        self._click_select_target()

        # 在弹窗中将两个toggle开关切换至激活状态
        self._toggle_switches()

        # 点击"确定"按钮（内部已检测已全部采集弹窗）
        confirm_result = self._confirm_selection()

        if not confirm_result:
            # 检测到已全部采集弹窗，点击安全区域关闭
            logger.info("点击安全区域关闭提示弹窗")
            self.device.click(ISLAND_GATHER_SAFE_AREA)
            self.device.sleep(0.5)
            return False

        logger.info("采集目标选择成功")
        return True

    def _handle_collection_complete(self):
        """
        处理采集完成页面：等待采集完成，点击安全区域关闭完成界面
        """
        max_wait = 30  # 最多等待30秒
        for i in range(max_wait):
            self.device.screenshot()
            if self.appear(ISLAND_GATHER_COMPLETE, offset=30):
                logger.info("采集完成页面已出现，点击安全区域关闭")
                self.device.click(ISLAND_GATHER_SAFE_AREA)
                self.device.sleep(0.5)
                return True
            self.device.sleep(1)

        logger.warning("采集完成页面等待超时")
        return False

    def _exit_management(self):
        """
        退出管理界面，返回到小岛主界面
        """
        logger.info("退出管理界面")
        # 先点击安全区域关闭可能残留的弹窗
        for _ in range(3):
            self.device.screenshot()
            if self.appear(ISLAND_GATHER_ALREADY_COLLECTED, offset=30) or \
               self.appear(ISLAND_GATHER_COMPLETE, offset=30) or \
               self.appear(ISLAND_GATHER_TARGET_POPUP, offset=30):
                self.device.click(ISLAND_GATHER_SAFE_AREA)
                self.device.sleep(0.3)
            else:
                break
        # 使用ui_goto导航回小岛页面
        self.ui_goto(page_island, get_ship=False)
        logger.info("已回到小岛主界面")
        return True


if __name__ == "__main__":
    az = IslandDailyGather('alas', task='Alas')
    az.device.screenshot()
    az.run()
