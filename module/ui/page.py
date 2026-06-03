import traceback

from module.coalition.assets import *
from module.event_hospital.assets import HOSIPITAL_CHECK
from module.freebies.assets import MAIL_ENTER
from module.raid.assets import *
from module.retire.assets import DOCK_CHECK
from module.ui.assets import *
from module.ui_white.assets import *
import module.config.server as server


class Page:
    # 键: str, 页面名称如 "page_main"
    # 值: Page, 页面实例
    all_pages = {}

    @classmethod
    def clear_connection(cls):
        for page in cls.all_pages.values():
            page.parent = None

    @classmethod
    def init_connection(cls, destination):
        """初始化页面间的 A* 寻路连接。

        Args:
            destination (Page): 目标页面。
        """
        cls.clear_connection()

        visited = [destination]
        visited = set(visited)
        while 1:
            new = visited.copy()
            for page in visited:
                for link in cls.iter_pages():
                    if link in visited:
                        continue
                    if page in link.links:
                        link.parent = page
                        new.add(link)
            if len(new) == len(visited):
                break
            visited = new

    @classmethod
    def iter_pages(cls):
        return cls.all_pages.values()

    @classmethod
    def iter_check_buttons(cls):
        for page in cls.all_pages.values():
            yield page.check_button

    def __init__(self, check_button):
        self.check_button = check_button
        self.links = {}
        (filename, line_number, function_name, text) = traceback.extract_stack()[-2]
        self.name = text[:text.find('=')].strip()
        self.parent = None
        Page.all_pages[self.name] = self

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return self.name

    def link(self, button, destination):
        self.links[destination] = button


"""
定义 UI 页面
"""

# 主界面
# 使用 MAIN_GOTO_FLEET 代替 MAIN_GOTO_CAMPAIGN，配合 info_bar 可实现更快的页面切换
page_main = Page(MAIN_GOTO_FLEET)
page_campaign_menu = Page(CAMPAIGN_MENU_CHECK)
page_campaign = Page(CAMPAIGN_CHECK)
page_fleet = Page(FLEET_CHECK)
page_main.link(button=MAIN_GOTO_CAMPAIGN, destination=page_campaign_menu)
page_main.link(button=MAIN_GOTO_FLEET, destination=page_fleet)
page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_CAMPAIGN, destination=page_campaign)
page_campaign_menu.link(button=GOTO_MAIN, destination=page_main)
page_campaign.link(button=GOTO_MAIN, destination=page_main)
page_campaign.link(button=BACK_ARROW, destination=page_campaign_menu)
page_fleet.link(button=GOTO_MAIN, destination=page_main)

# 主界面（白色主题）
# 2024.05.22, 新 UI 中 MAIN_GOTO_CAMPAIGN_WHITE 是主界面最后显示的按钮
page_main_white = Page(MAIN_GOTO_CAMPAIGN_WHITE)
page_main_white.link(button=MAIN_GOTO_CAMPAIGN_WHITE, destination=page_campaign_menu)
page_main_white.link(button=MAIN_GOTO_FLEET_WHITE, destination=page_fleet)

# 未知页面
page_unknown = Page(None)
page_unknown.link(button=GOTO_MAIN, destination=page_main)

# 演习
# 不要从 page_campaign 进入 page_exercise
page_exercise = Page(EXERCISE_CHECK)
page_exercise.link(button=GOTO_MAIN, destination=page_main)
page_exercise.link(button=BACK_ARROW, destination=page_campaign_menu)
page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_EXERCISE, destination=page_exercise)

# 每日任务
# 不要从 page_campaign 进入 page_daily
page_daily = Page(DAILY_CHECK)
page_daily.link(button=GOTO_MAIN, destination=page_main)
page_daily.link(button=BACK_ARROW, destination=page_campaign_menu)
page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_DAILY, destination=page_daily)

# 活动
page_event = Page(EVENT_CHECK)
page_event.link(button=GOTO_MAIN, destination=page_main)
page_event.link(button=BACK_ARROW, destination=page_campaign)
page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_EVENT, destination=page_event)
page_campaign.link(button=CAMPAIGN_GOTO_EVENT, destination=page_event)
if server.server == 'tw':
    page_main.link(button=EVENT_20260430_ENTRANCE_TEMP, destination=page_event)

# SP 关卡
page_sp = Page(SP_CHECK)
page_sp.link(button=GOTO_MAIN, destination=page_main)
page_sp.link(button=BACK_ARROW, destination=page_campaign)
page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_EVENT, destination=page_sp)
page_campaign.link(button=CAMPAIGN_GOTO_EVENT, destination=page_sp)

# 联动活动
# 霜冻行动
# page_coalition = Page(FROSTFALL_COALITION_CHECK)
# page_coalition.link(button=GOTO_MAIN, destination=page_main)
# page_coalition.link(button=BACK_ARROW, destination=page_campaign_menu)
# page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_EVENT, destination=page_coalition)
# 小学院
# page_coalition_menu = Page(COALITION_ACADEMY_MAIN_CHECK)
# page_coalition_menu.link(button=COALITION_ACADEMY_HOME, destination=page_main)
# page_coalition = Page(COALITION_ACADEMY_CAMPAIGN_CHECK)
# page_coalition.link(button=COALITION_ACADEMY_HOME, destination=page_main)
# page_coalition.link(button=COALITION_ACADEMY_BACK, destination=page_coalition_menu)
# page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_EVENT, destination=page_coalition)
# page_coalition_menu.link(button=COALITION_ACADEMY_GOTO_CAMPAIGN, destination=page_coalition)
# 霓虹都市
# page_coalition = Page(NEONCITY_COALITION_CHECK)
# page_coalition.link(button=NEONCITY_UI_HOME, destination=page_main)
# page_coalition.link(button=NEONCITY_UI_BACK, destination=page_campaign_menu)
# page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_EVENT, destination=page_coalition)
# DATE A LANE
# page_coalition = Page(FROSTFALL_COALITION_CHECK)
# page_coalition.link(button=GOTO_MAIN, destination=page_main)
# page_coalition.link(button=BACK_ARROW, destination=page_campaign_menu)
# page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_EVENT, destination=page_coalition)
# 时尚联动
page_coalition = Page(FASHION_COALITION_CHECK)
page_coalition.link(button=GOTO_MAIN, destination=page_main)
page_coalition.link(button=BACK_ARROW, destination=page_campaign_menu)
page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_EVENT, destination=page_coalition)

# 大世界
page_os = Page(OS_CHECK)
page_os.link(button=GOTO_MAIN, destination=page_main)
page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_OS, destination=page_os)

# 作战档案
# 不要从 page_campaign 进入 page_archives
page_archives = Page(WAR_ARCHIVES_CHECK)
page_archives.link(button=WAR_ARCHIVES_GOTO_CAMPAIGN_MENU, destination=page_campaign_menu)
page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_WAR_ARCHIVES, destination=page_archives)

# 奖励
page_reward = Page(REWARD_CHECK)
page_reward.link(button=REWARD_GOTO_MAIN, destination=page_main)
page_main.link(button=MAIN_GOTO_REWARD, destination=page_reward)
page_main_white.link(button=MAIN_GOTO_REWARD_WHITE, destination=page_reward)

# 任务
page_mission = Page(MISSION_CHECK)
page_mission.link(button=GOTO_MAIN, destination=page_main)
page_main.link(button=MAIN_GOTO_MISSION, destination=page_mission)
page_main_white.link(button=MAIN_GOTO_MISSION_WHITE, destination=page_mission)

# 大舰队
page_guild = Page(GUILD_CHECK)
page_guild.link(button=GOTO_MAIN, destination=page_main)
page_main.link(button=MAIN_GOTO_GUILD, destination=page_guild)
page_main_white.link(button=MAIN_GOTO_GUILD_WHITE, destination=page_guild)

# 委托
# 不要从战役进入委托页面
page_commission = Page(COMMISSION_CHECK)
page_commission.link(button=GOTO_MAIN, destination=page_main)
page_commission.link(button=BACK_ARROW, destination=page_reward)
page_reward.link(button=REWARD_GOTO_COMMISSION, destination=page_commission)

# 战术学院
# 不要从学院进入战术学院
page_tactical = Page(TACTICAL_CHECK)
page_tactical.link(button=GOTO_MAIN, destination=page_main)
page_tactical.link(button=BACK_ARROW, destination=page_reward)
page_reward.link(button=REWARD_GOTO_TACTICAL, destination=page_tactical)

# 通行券
page_battle_pass = Page(BATTLE_PASS_CHECK)
page_battle_pass.link(button=GOTO_MAIN, destination=page_main)
page_reward.link(button=REWARD_GOTO_BATTLE_PASS, destination=page_battle_pass)

# 活动列表
page_event_list = Page(EVENT_LIST_CHECK)
page_event_list.link(button=GOTO_MAIN, destination=page_main)
page_main.link(button=MAIN_GOTO_EVENT_LIST, destination=page_event_list)
page_main_white.link(button=MAIN_GOTO_EVENT_LIST_WHITE, destination=page_event_list)

# 突袭
# 旧版（2026.02.12 前）
# page_raid = Page(RAID_CHECK)
# page_raid.link(button=GOTO_MAIN, destination=page_main)
# page_main.link(button=MAIN_GOTO_RAID, destination=page_raid)
# page_main_white.link(button=MAIN_GOTO_RAID_WHITE, destination=page_raid)
# 新版（2026.02.12 后）
page_raid = Page(RAID_CHECK)
page_raid.link(button=GOTO_MAIN, destination=page_main)
page_raid.link(button=BACK_ARROW, destination=page_campaign_menu)
page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_EVENT, destination=page_raid)

# 船坞
page_dock = Page(DOCK_CHECK)
page_dock.link(button=GOTO_MAIN, destination=page_main)
page_main.link(button=MAIN_GOTO_DOCK, destination=page_dock)
page_main_white.link(button=MAIN_GOTO_DOCK_WHITE, destination=page_dock)

# 科研
# 不要从 page_reward 进入 page_research
page_research = Page(RESEARCH_CHECK)
page_research.link(button=GOTO_MAIN, destination=page_main)

# 船坞（研发）
page_shipyard = Page(SHIPYARD_CHECK)
page_shipyard.link(button=GOTO_MAIN, destination=page_main)

# META
page_meta = Page(META_CHECK)
page_meta.link(button=GOTO_MAIN, destination=page_main)

# 仓库
page_storage = Page(STORAGE_CHECK)
page_storage.link(button=GOTO_MAIN, destination=page_main)
page_main.link(button=MAIN_GOTO_STORAGE, destination=page_storage)
page_main_white.link(button=MAIN_GOTO_STORAGE_WHITE, destination=page_storage)

# 科研菜单
page_reshmenu = Page(RESHMENU_CHECK)
page_reshmenu.link(button=RESHMENU_GOTO_RESEARCH, destination=page_research)
page_reshmenu.link(button=RESHMENU_GOTO_SHIPYARD, destination=page_shipyard)
page_reshmenu.link(button=RESHMENU_GOTO_META, destination=page_meta)
page_reshmenu.link(button=GOTO_MAIN, destination=page_main)
page_main.link(button=MAIN_GOTO_RESHMENU, destination=page_reshmenu)
page_main_white.link(button=MAIN_GOTO_RESHMENU, destination=page_reshmenu)

# 后宅菜单
page_dormmenu = Page(DORMMENU_CHECK)
page_dormmenu.link(button=DORMMENU_GOTO_MAIN, destination=page_main)
page_main.link(button=MAIN_GOTO_DORMMENU, destination=page_dormmenu)
page_main_white.link(button=MAIN_GOTO_DORMMENU_WHITE, destination=page_dormmenu)

# 后宅
# DORM_CHECK 是"管理"按钮（从右数第三个），因为它是最后加载完成的按钮
page_dorm = Page(DORM_CHECK)
page_dormmenu.link(button=DORMMENU_GOTO_DORM, destination=page_dorm)
page_dorm.link(button=DORM_GOTO_MAIN, destination=page_main)

# 指挥喵
page_meowfficer = Page(MEOWFFICER_CHECK)
page_dormmenu.link(button=DORMMENU_GOTO_MEOWFFICER, destination=page_meowfficer)
page_meowfficer.link(button=MEOWFFICER_GOTO_DORMMENU, destination=page_main)

# 学院
page_academy = Page(ACADEMY_CHECK)
page_dormmenu.link(button=DORMMENU_GOTO_ACADEMY, destination=page_academy)
page_academy.link(button=GOTO_MAIN, destination=page_main)

# 私人休息室
page_private_quarters = Page(PRIVATE_QUARTERS_CHECK)
page_dormmenu.link(button=DORMMENU_GOTO_PRIVATE_QUARTERS, destination=page_private_quarters)
page_private_quarters.link(button=PQ_GOTO_MAIN, destination=page_main)

# 游戏室与选择游戏
page_game_room = Page(GAME_ROOM_CHECK)
page_academy.link(button=ACADEMY_GOTO_GAME_ROOM, destination=page_game_room)
page_game_room.link(button=GAME_ROOM_GOTO_MAIN, destination=page_main)

# 商店
page_shop = Page(SHOP_CHECK)
page_shop.link(button=GOTO_MAIN, destination=page_main)
page_main.link(button=MAIN_GOTO_SHOP, destination=page_shop)
page_main_white.link(button=MAIN_GOTO_SHOP_WHITE, destination=page_shop)

# 军火商店
page_munitions = Page(MUNITIONS_CHECK)
# 优先使用后一条路径，因为加载时默认为 shop_general，背景颜色更稳定
# page_shop.link(button=SHOP_GOTO_MUNITIONS, destination=page_munitions)
page_academy.link(button=ACADEMY_GOTO_MUNITIONS, destination=page_munitions)
page_munitions.link(button=GOTO_MAIN, destination=page_main)

# 补给礼包
page_supply_pack = Page(SUPPLY_PACK_CHECK)
page_shop.link(button=SHOP_GOTO_SUPPLY_PACK, destination=page_supply_pack)
page_supply_pack.link(button=GOTO_MAIN, destination=page_main)

# 建造
page_build = Page(BUILD_CHECK)
page_build.link(button=GOTO_MAIN, destination=page_main)
page_main.link(button=MAIN_GOTO_BUILD, destination=page_build)
page_main_white.link(button=MAIN_GOTO_BUILD_WHITE, destination=page_build)

# 邮件
page_mail = Page(MAIL_CHECK)
page_mail.link(button=GOTO_MAIN_WHITE, destination=page_main)
# 邮件入口因不同 UI 而异
page_main_white.link(button=MAIL_ENTER_WHITE, destination=page_mail)
page_main.link(button=MAIL_ENTER, destination=page_mail)

# 世界频道
# 新旧 UI 都有 CHANNEL_CHECK
# 点击左侧空白区域离开
page_channel = Page(CHANNEL_CHECK)
page_channel.link(button=CAMPAIGN_MENU_GOTO_CAMPAIGN, destination=page_main)

# RPG 活动 (raid_20240328)
page_rpg_stage = Page(RPG_GOTO_STORY)
page_rpg_story = Page(RPG_GOTO_STAGE)
page_rpg_stage.link(button=RPG_GOTO_STORY, destination=page_rpg_story)
page_rpg_stage.link(button=RPG_HOME, destination=page_main)
page_rpg_stage.link(button=RPG_BACK, destination=page_campaign_menu)
page_rpg_story.link(button=RPG_GOTO_STAGE, destination=page_rpg_stage)
page_rpg_story.link(button=RPG_HOME, destination=page_main)
page_rpg_story.link(button=RPG_BACK, destination=page_campaign_menu)

page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_EVENT, destination=page_rpg_stage)
# page_main.link(button=MAIN_GOTO_RAID, destination=page_rpg_stage)
# page_main_white.link(button=MAIN_GOTO_RAID_WHITE, destination=page_rpg_stage)

page_rpg_city = Page(RPG_LEAVE_CITY)
page_rpg_city.link(button=RPG_LEAVE_CITY, destination=page_rpg_stage)
page_rpg_city.link(button=RPG_HOME, destination=page_main)

# 保留 page_rpg_stage，以便突袭模块可以导入
# page_rpg_stage = page_raid

# 医院活动 (20250327)
page_hospital = Page(HOSIPITAL_CHECK)
page_hospital.link(button=GOTO_MAIN_WHITE, destination=page_main)
page_campaign_menu.link(button=CAMPAIGN_MENU_GOTO_EVENT, destination=page_hospital)

# ISLAND
page_island = Page(ISLAND_CHECK)
page_island_message = Page(DORMMENU_GOTO_ISLAND_MESSAGE)
page_island_management = Page(ISLAND_MANAGEMENT_CHECK)
page_island_postmanage = Page(ISLAND_POSTMANAGE_CHECK)
page_island_shop = Page(ISLAND_SHOP_CHECK)
page_island_shopping = Page(ISLAND_SHOPPING_CHECK)
page_island_warehouse = Page(ISLAND_WAREHOUSE_CHECK)
page_island_warehouse_filter = Page(ISLAND_WAREHOUSE_FILTER_CHECK)
page_island_map = Page(ISLAND_MAP_CHECK)
page_island_visit = Page(ISLAND_VISIT_CHECK)
page_island_mill = Page(ISLAND_MILL_CHECK)
page_island_season = Page(ISLAND_SEASON_CHECK)
page_island_phone = Page(ISLAND_PHONE_CHECK)

page_dormmenu.link(button=DORMMENU_GOTO_ISLAND, destination=page_island)
page_island_message.link(button=DORMMENU_GOTO_ISLAND_MESSAGE, destination=page_island)
page_island.link(button=ISLAND_GOTO_ISLAND_PHONE, destination=page_island_phone)
page_island.link(button=ISLAND_GOTO_MANAGEMENT, destination=page_island_management)
page_island.link(button=ISLAND_GOTO_SHOP, destination=page_island_shop)
page_island_management.link(button=ISLAND_MANAGEMENT_GOTO_ISLAND, destination=page_island)
page_island_management.link(button=ISLAND_MANAGEMENT_GOTO_POSTMANAGE, destination=page_island_postmanage)
page_island_management.link(button=ISLAND_MANAGEMENT_GOTO_WAREHOUSE, destination=page_island_warehouse)
page_island_management.link(button=ISLAND_MANAGEMENT_GOTO_MAIN,destination=page_main)
page_island_postmanage.link(button=ISLAND_POSTMANAGE_GOTO_MANAGEMENT, destination=page_island_management)
page_island_warehouse.link(button=ISLAND_WAREHOUSE_GOTO_WAREHOUSE_FILTER, destination=page_island_warehouse_filter)
page_island_warehouse.link(button=ISLAND_WAREHOUSE_GOTO_MANAGEMENT, destination=page_island_management)
page_island_warehouse_filter.link(button=ISLAND_WAREHOUSE_FILTER_GOTO_WAREHOUSE, destination=page_island_warehouse)
page_island_shop.link(button=ISLAND_SHOP_GOTO_ISLAND, destination=page_island)
page_island_shopping.link(button=ISLAND_SHOPPING_GOTO_SHOP, destination=page_island_shop)
page_island.link(button=ISLAND_GOTO_MAP, destination=page_island_map)
page_island_map.link(button=ISLAND_MAP_GOTO_ISLAND, destination=page_island)
page_island_management.link(button=ISLAND_MANAGEMENT_GOTO_VISIT, destination=page_island_visit)
page_island_visit.link(button=ISLAND_VISIT_GOTO_MANAGEMENT, destination=page_island_management)
page_island_mill.link(button=ISLAND_MILL_GOTO_ISLAND, destination=page_island)
page_island_season.link(button=ISLAND_SEASON_GOTO_ISLAND, destination=page_island)
page_island_phone.link(button=ISLAND_PHONE_GOTO_MAIN, destination=page_main)
page_island_phone.link(button=ISLAND_PHONE_GOTO_ISLAND, destination=page_island)
page_island_phone.link(button=ISLAND_PHONE_GOTO_ISLAND_MANAGE, destination=page_island_management)