"""岛屿每日采集模块。

管理岛屿资源采集的自动化流程，包括采集奖励领取、目标选择与角色派遣。
根据角色体力阈值和工作状态进行智能选择，按生活等级排序优先派遣空闲角色。
"""
from module.island.island import *
from datetime import timedelta

from module.config.time_source import now as current_time
from module.logger import logger

# 采集安全区域（无截图，固定坐标点击用于关闭弹窗）
ISLAND_GATHER_SAFE_AREA = Button(
    area={'cn': (1080, 650, 1180, 700), 'en': (1080, 650, 1180, 700), 'jp': (1080, 650, 1180, 700), 'tw': (1080, 650, 1180, 700)},
    color={'cn': (0, 0, 0), 'en': (0, 0, 0), 'jp': (0, 0, 0), 'tw': (0, 0, 0)},
    button={'cn': (1080, 650, 1180, 700), 'en': (1080, 650, 1180, 700), 'jp': (1080, 650, 1180, 700), 'tw': (1080, 650, 1180, 700)},
    file={'cn': './assets/cn/island/ISLAND_GATHER_SAFE_AREA.png', 'en': './assets/cn/island/ISLAND_GATHER_SAFE_AREA.png', 'jp': './assets/cn/island/ISLAND_GATHER_SAFE_AREA.png', 'tw': './assets/cn/island/ISLAND_GATHER_SAFE_AREA.png'}
)

GATHER_STAMINA_THRESHOLD = 100


class IslandDailyGather(Island):
    """岛屿每日资源采集自动化执行器。

    支持每日凌晨 3:10 和下午 18:00 自动采集岛屿资源。
    包含采集奖励领取、目标选择开关切换、空闲角色智能派遣以及采集完成弹窗关闭。
    """

    def run(self):
        """任务主入口，执行采集流程并根据当前时间调度下次运行时间。

        Pages:
            in: page_island
            out: page_island
        """
        now = current_time()

        # 无论何时运行，都执行采集
        logger.info(f"[岛屿-每日采集] 开始执行每日采集 (当前时间: {now.strftime('%H:%M')})")
        self.dispatch_collection()

        # 调度下次运行时间
        next_run = self._schedule_next_run(now)
        self.config.task_delay(target=next_run)
        logger.info(f"[岛屿-每日采集] 下次运行时间: {next_run}")

    def _schedule_next_run(self, now):
        """计算下次自动采集的调度时间。

        调度规则：凌晨 3:10 执行后调度至当天下午 18:00，下午 18:00 执行后调度至次日凌晨 3:10。

        Args:
            now (datetime): 当前时间对象。

        Returns:
            datetime: 下次运行的期望时间点。
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
        """执行完整的岛屿资源采集 UI 交互流程。"""
        logger.info("[岛屿-每日采集] === 开始UI模拟点击采集流程 ===")

        # 1. 进入管理界面
        logger.info("[岛屿-每日采集] 步骤1: 进入管理界面")
        self.goto_management()

        # 2. 进入管理 → 切换到"采集"页签
        logger.info("[岛屿-每日采集] 步骤2: 切换到采集页签")
        self.ui_goto(page_island_postmanage, get_ship=False)
        self.post_manage_mode_collection()

        # 3. 检查并领取已有采集奖励（如果有的话）
        logger.info("[岛屿-每日采集] 步骤3: 检查并领取已有采集奖励")
        self._claim_existing_rewards()

        # 4. 点击"选择采集目标"按钮 → 切换开关 → 点击确定
        #    如果所有采集物已采集完毕，确定时会弹出提示弹窗
        logger.info("[岛屿-每日采集] 步骤4: 处理选择采集目标确认")
        if self._handle_target_selection():
            worker_list = self._daily_gather_worker_list()
            # 如果成功选择了采集目标，继续后续流程
            # 5. 依次点击三个"+"按钮并选择角色
            character_selected = True
            for i in range(3):
                logger.info(f"[岛屿-每日采集] 步骤5-{i+1}: 点击第{i+1}个+按钮并选择角色")
                if not self._click_plus_and_select_character(i, worker_list):
                    logger.warning(f"[岛屿-每日采集] 第{i + 1}个槽位角色选择失败，终止本次采集派遣")
                    character_selected = False
                    break

            if character_selected:
                # 6. 点击"出发"按钮
                logger.info("[岛屿-每日采集] 步骤6: 点击出发按钮")
                if self._click_depart():
                    # 7. 处理采集完成页面
                    logger.info("[岛屿-每日采集] 步骤7: 等待采集完成并关闭完成页面")
                    self._handle_collection_complete()
                else:
                    # 出发按钮未出现（体力或资金不足时为灰色，或缺少对应服务器的识别图），
                    # 采集没有开始，不会有完成页面，无需再等待 30 秒
                    logger.warning("[岛屿-每日采集] 未能出发（体力或资金不足，或出发按钮识别失败），跳过等待采集完成")
        else:
            logger.info("[岛屿-每日采集] 所有采集物已采集完毕，跳过后续步骤")

        # 8. 退出管理界面
        self._exit_management()
        logger.info("[岛屿-每日采集] === UI模拟点击采集流程完成 ===")

    # ==================== 步骤方法 ====================

    def _claim_existing_rewards(self):
        """检查并领取已完成的前次采集奖励。"""
        max_attempts = 5
        for _ in range(max_attempts):
            self.device.screenshot()
            if self.appear(ISLAND_GET, offset=30):
                logger.info("[岛屿-每日采集] 检测到可领取的奖励，正在领取")
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
        """点击「选择采集目标」按钮并等待目标配置弹窗出现。"""
        while True:
            self.device.screenshot()
            # 检查弹窗是否已经出现
            if self.appear(ISLAND_GATHER_TARGET_POPUP, offset=30):
                logger.info("[岛屿-每日采集] 选择采集目标弹窗已出现")
                break
            # 点击选择采集目标按钮
            if self.appear_then_click(ISLAND_GATHER_SELECT_TARGET, offset=30):
                self.device.sleep(0.5)
                continue
            self.device.sleep(0.3)

    def _toggle_switches(self):
        """将采集目标配置弹窗中的两个分类开关切换至激活状态。"""
        for toggle_name, toggle_on, toggle_off in [
            ("开关A", ISLAND_GATHER_TOGGLE_A_ON, ISLAND_GATHER_TOGGLE_A_OFF),
            ("开关B", ISLAND_GATHER_TOGGLE_B_ON, ISLAND_GATHER_TOGGLE_B_OFF),
        ]:
            self._ensure_toggle_active(toggle_name, toggle_on, toggle_off)

    def _ensure_toggle_active(self, toggle_name, toggle_on, toggle_off):
        """确保指定的分类开关处于激活状态。

        Args:
            toggle_name (str): 开关名称（用于日志记录）。
            toggle_on (Button): 开关激活状态的按钮资源。
            toggle_off (Button): 开关未激活状态的按钮资源。

        Returns:
            bool: 开关是否成功处于激活状态。
        """
        max_attempts = 5
        for attempt in range(max_attempts):
            self.device.screenshot()

            # 检查是否已激活
            if self.appear(toggle_on, offset=10):
                logger.info(f"[岛屿-每日采集] {toggle_name} 已处于激活状态")
                return True

            # 检查是否未激活，点击切换
            if self.appear(toggle_off, offset=10):
                logger.info(f"[岛屿-每日采集] {toggle_name} 未激活，点击切换")
                self.device.click(toggle_off)
                self.device.sleep(0.3)
                continue

            # 没有检测到任何状态，尝试点击开关默认位置
            self.device.click(toggle_off)
            self.device.sleep(0.3)

        logger.warning(f"[岛屿-每日采集] {toggle_name} 切换超时")
        return False

    def _confirm_selection(self):
        """点击采集目标弹窗中的「确定」按钮并处理弹窗关闭。

        最多尝试 3 次，如果检测到「已全部采集」提示弹窗则停止。

        Returns:
            bool: 成功确认并可继续派遣返回 True；若已全部采集或确认超时返回 False。
        """
        max_attempts = 3
        for attempt in range(max_attempts):
            self.device.screenshot()

            # 检查是否已全部采集弹窗出现
            if self.appear(ISLAND_GATHER_ALREADY_COLLECTED, offset=30):
                logger.info("[岛屿-每日采集] 检测到「已全部采集」提示弹窗")
                return False

            if self.appear_then_click(ISLAND_GATHER_CONFIRM, offset=30):
                self.device.sleep(0.5)
                continue

            # 弹窗关闭后检测采集页签是否恢复
            if not self.appear(ISLAND_GATHER_TARGET_POPUP, offset=30):
                logger.info("[岛屿-每日采集] 弹窗已关闭，确定成功")
                return True

            self.device.sleep(0.3)

        # 尝试3次后还未关闭，可能是已全部采集弹窗遮盖了目标弹窗
        self.device.screenshot()
        if self.appear(ISLAND_GATHER_ALREADY_COLLECTED, offset=30):
            logger.info("[岛屿-每日采集] 检测到「已全部采集」提示弹窗")
            return False
        # 也可能是目标弹窗仍然开着但确定按钮失效
        if self.appear(ISLAND_GATHER_TARGET_POPUP, offset=30):
            logger.warning("[岛屿-每日采集] 确定按钮点击超时，目标弹窗仍未关闭")
            # 尝试通过安全区域关闭
            self.device.click(ISLAND_GATHER_SAFE_AREA)
            self.device.sleep(0.3)
        return False

    def _daily_gather_worker_list(self):
        """解析并返回每日采集自定义角色派遣配置列表。

        每日采集界面无 WorkerJuu（黄鸡），若配置中包含会自动忽略；最多保留前 3 个有效角色。

        Returns:
            list[str]: 过滤后的有效自定义角色名称列表。
        """
        config = self.config.IslandDailyGather_WorkerFilter
        characters = self.parse_character_filter(config)
        if not characters:
            return []

        filtered = []
        ignored_worker = False
        for character in characters:
            if character == "WorkerJuu":
                ignored_worker = True
                continue
            filtered.append(character)

        if ignored_worker:
            logger.warning("[岛屿-每日采集] 每日采集不能选择 WorkerJuu，已自动忽略")

        if len(filtered) > 3:
            logger.warning(f"[岛屿-每日采集] 每日采集最多指定 3 个有效角色，已忽略后续角色: {filtered[3:]}")
            filtered = filtered[:3]

        logger.info(f"[岛屿-每日采集] 每日采集自定义角色: {filtered}")
        return filtered

    def _click_plus_and_select_character(self, index, worker_list=None):
        """点击指定槽位的「+」按钮并派遣空闲角色。

        Args:
            index (int): 槽位索引 (0, 1, 2)。
            worker_list (list[str], optional): 每日采集自定义角色列表。

        Returns:
            bool: 角色选择并确认成功返回 True，失败返回 False。
        """
        plus_buttons = [ISLAND_GATHER_PLUS_A, ISLAND_GATHER_PLUS_B, ISLAND_GATHER_PLUS_C]
        plus_button = plus_buttons[index]
        worker_list = worker_list or []

        # 点击"+"按钮，若页面动画或点击未生效则重试，避免无限等待。
        for attempt in range(3):
            logger.info(f"[岛屿-每日采集] 点击第{index + 1}个+按钮")
            self.device.click(plus_button)
            if self._wait_for_character_select(timeout=6):
                break
            logger.warning(f"[岛屿-每日采集] 第{index + 1}个槽位角色选择界面未出现，重试 {attempt + 1}/3")
        else:
            logger.warning(f"[岛屿-每日采集] 第{index + 1}个槽位无法打开角色选择界面")
            return False

        # 按"生活等级"进行升序排序
        self._sort_by_life_level()

        # 选择体力达标且非工作中的角色
        selected = False
        if index < len(worker_list):
            character = worker_list[index]
            logger.info(f"[岛屿-每日采集] 第{index + 1}个槽位尝试选择指定角色: {character}")
            selected = self.select_specific_character(character, min_stamina=GATHER_STAMINA_THRESHOLD)
            if not selected:
                logger.warning(f"[岛屿-每日采集] 第{index + 1}个槽位指定角色不可用，回退旧逻辑: {character}")

        if not selected and not self._select_character_with_stamina_check():
            logger.warning(f"[岛屿-每日采集] 第{index + 1}个槽位未找到可用角色，跳过")
            self.device.click(SELECT_UI_BACK)
            self.device.sleep(0.3)
            return False

        # 点击确认按钮完成选择
        self.device.sleep(0.3)
        if not self.confirm_selected_character_closed(f"每日采集第{index + 1}个槽位"):
            self.device.click(SELECT_UI_BACK)
            self.device.sleep(0.3)
            return False
        logger.info(f"[岛屿-每日采集] 第{index + 1}个槽位角色选择完成")
        return True

    def _wait_for_character_select(self, timeout=8):
        """等待角色选择界面出现。

        Args:
            timeout (float): 最长等待时间（秒），默认为 8。

        Returns:
            bool: 角色选择界面是否成功出现。
        """
        for _ in self.loop(timeout=timeout, skip_first=False):
            if self.appear(ISLAND_SELECT_CHARACTER_CHECK, offset=1):
                logger.info("[岛屿-每日采集] 角色选择界面已出现")
                return True

        return False

    def _sort_by_life_level(self):
        """通过模板匹配检测升序箭头，确保按生活等级升序排序。

        按钮颜色不变仅箭头不同，截取按钮区域图像后匹配升序箭头模板来判断。
        """
        # 截取排序按钮区域，检测当前是否为升序
        self.device.screenshot()
        sort_area = crop(self.device.image, ISLAND_GATHER_SORT_LIFE.area)
        if TEMPLATE_GATHER_SORT_LIFE_ASC.match(sort_area, similarity=0.8):
            logger.info("[岛屿-每日采集] 当前已是生活等级升序排序，无需操作")
            return

        # 不是升序，点击排序按钮切换到升序
        logger.info("[岛屿-每日采集] 点击生活等级排序按钮切换为升序")
        self.device.click(ISLAND_GATHER_SORT_LIFE)
        self.device.sleep(0.3)

        # 验证是否成功切换为升序
        self.device.screenshot()
        sort_area = crop(self.device.image, ISLAND_GATHER_SORT_LIFE.area)
        if TEMPLATE_GATHER_SORT_LIFE_ASC.match(sort_area, similarity=0.8):
            logger.info("[岛屿-每日采集] 成功切换为生活等级升序排序")
        else:
            logger.warning("[岛屿-每日采集] 升序切换可能未生效，尝试再次点击")
            self.device.click(ISLAND_GATHER_SORT_LIFE)
            self.device.sleep(0.3)

        logger.info("[岛屿-每日采集] 生活等级升序排序完成")

    def _select_character_with_stamina_check(self):
        """从当前角色列表中选择体力达标且非工作中的角色。

        若没有达到阈值的角色，则回退选择当前页体力最高的空闲角色，避免流程卡住。
        注：采集界面的角色选择没有黄鸡角色。

        Returns:
            bool: 是否成功选择角色。
        """
        screenshot = self.device.screenshot()
        detected = False
        available = []

        for row, col, button in self.select_character_grid.generate():
            character_status = self._recognize_character_status(screenshot, button)
            if not character_status:
                continue

            detected = True
            char_info = {
                "grid_position": (row, col),
                "button_area": button.area,
                **character_status,
            }
            if char_info["is_working"] or char_info["is_selected"]:
                continue

            if char_info.get("stamina", 0) >= GATHER_STAMINA_THRESHOLD:
                return self._click_character(char_info, f"体力达标 >= {GATHER_STAMINA_THRESHOLD}")

            available.append(char_info)

        if not detected:
            logger.warning("[岛屿-每日采集] 未检测到任何角色")
            return False

        if not available:
            logger.warning("[岛屿-每日采集] 所有角色均在工作中或已被选中，无法选择空闲角色")
            return False

        best_char = max(available, key=lambda item: item.get("stamina", 0))
        logger.warning(
            f"未找到体力达标角色，回退选择当前页体力最高角色: "
            f"{best_char['character_name']} ({best_char.get('stamina', 0)})"
        )
        return self._click_character(best_char, "体力最高回退")

    def _click_character(self, char_info, reason):
        """点击指定角色网格槽位。

        Args:
            char_info (dict): 角色信息字典（包含 grid_position、character_name、stamina 等）。
            reason (str): 选择原因说明（日志用）。

        Returns:
            bool: 恒返回 True。
        """
        row, col = char_info["grid_position"]
        stamina = char_info.get("stamina", 0)
        logger.info(
            f"选择角色: {char_info['character_name']} "
            f"(位置: {row},{col}, 体力: {stamina}, 原因: {reason})"
        )
        button = self.select_character_grid[row, col]
        self.device.click(button)
        self.device.sleep(0.3)
        return True

    def _select_first_idle_character(self):
        """选择第一个空闲角色（兼容旧调用）。

        Returns:
            bool: 是否成功选择空闲角色。
        """
        screenshot = self.device.screenshot()
        characters = self.recognize_all_characters(screenshot)

        for char_info in characters:
            if not char_info["is_working"] and not char_info["is_selected"]:
                return self._click_character(char_info, "空闲且未选中")

        logger.warning("[岛屿-每日采集] 所有角色均在工作中或已被选中，无法选择空闲角色")
        return False

    def _click_depart(self):
        """点击「出发」按钮开始采集。

        Returns:
            bool: 是否成功点击出发按钮。
        """
        max_attempts = 10
        for attempt in range(max_attempts):
            self.device.screenshot()
            if self.appear_then_click(ISLAND_GATHER_DEPART, offset=30):
                self.device.sleep(0.5)
                logger.info("[岛屿-每日采集] 点击出发按钮成功")
                return True
            self.device.sleep(0.3)

        logger.warning("[岛屿-每日采集] 出发按钮点击超时")
        return False

    def _handle_target_selection(self):
        """处理选择采集目标的确认流程。

        如果所有采集物已采集完毕，确定时会弹出提示弹窗，需要关闭后退出。

        Returns:
            bool: True 表示成功选择目标可继续，False 表示已全部采集需退出。
        """
        # 点击"选择采集目标"按钮
        self._click_select_target()

        # 在弹窗中将两个toggle开关切换至激活状态
        self._toggle_switches()

        # 点击"确定"按钮（内部已检测已全部采集弹窗）
        confirm_result = self._confirm_selection()

        if not confirm_result:
            # 检测到已全部采集弹窗，点击安全区域关闭
            logger.info("[岛屿-每日采集] 点击安全区域关闭提示弹窗")
            self.device.click(ISLAND_GATHER_SAFE_AREA)
            self.device.sleep(0.5)
            return False

        logger.info("[岛屿-每日采集] 采集目标选择成功")
        return True

    def _handle_collection_complete(self):
        """处理采集完成页面：等待采集完成，点击安全区域关闭完成界面。

        Returns:
            bool: 采集完成页面是否出现并成功关闭。
        """
        max_wait = 30  # 最多等待30秒
        for i in range(max_wait):
            self.device.screenshot()
            if self.appear(ISLAND_GATHER_COMPLETE, offset=30):
                logger.info("[岛屿-每日采集] 采集完成页面已出现，点击安全区域关闭")
                self.device.click(ISLAND_GATHER_SAFE_AREA)
                self.device.sleep(0.5)
                return True
            self.device.sleep(1)

        logger.warning("[岛屿-每日采集] 采集完成页面等待超时")
        return False

    def _exit_management(self):
        """退出管理界面，返回到小岛主界面。

        Returns:
            bool: 恒返回 True。
        """
        logger.info("[岛屿-每日采集] 退出管理界面")
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
        logger.info("[岛屿-每日采集] 已回到小岛主界面")
        return True


if __name__ == "__main__":
    az = IslandDailyGather('alas', task='Alas')
    az.device.screenshot()
    az.run()
