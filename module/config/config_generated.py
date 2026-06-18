# 此文件是配置系统的更新器。
# 负责读取配置定义、生成 config_generated.py 以及处理配置的版本迁移、i18n 生成等核心管理任务。
import datetime

# 此文件由 module/config/config_updater.py 自动生成。
# 请勿手动修改。


class GeneratedConfig:
    """
    自动生成的配置类
    """

    # 配置组 `Oil`
    Oil_Value = 0
    Oil_Limit = 0
    Oil_Color = '^000000'
    Oil_Record = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Coin`
    Coin_Value = 0
    Coin_Limit = 0
    Coin_Color = '^FFAA33'
    Coin_Record = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Gem`
    Gem_Value = 0
    Gem_Color = '^FF3333'
    Gem_Record = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Pt`
    Pt_Value = 0
    Pt_Color = '^00BFFF'
    Pt_Record = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `YellowCoin`
    YellowCoin_Value = 0
    YellowCoin_Color = '^FF8800'
    YellowCoin_Record = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `PurpleCoin`
    PurpleCoin_Value = 0
    PurpleCoin_Color = '^7700BB'
    PurpleCoin_Record = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `ActionPoint`
    ActionPoint_Value = 0
    ActionPoint_Total = 0
    ActionPoint_Color = '^0000FF'
    ActionPoint_Record = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Merit`
    Merit_Value = 0
    Merit_Color = '^FFFF00'
    Merit_Record = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Cube`
    Cube_Value = 0
    Cube_Color = '^33FFFF'
    Cube_Record = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Core`
    Core_Value = 0
    Core_Color = '^AAAAAA'
    Core_Record = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Medal`
    Medal_Value = 0
    Medal_Color = '^FFDD00'
    Medal_Record = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `GuildCoin`
    GuildCoin_Value = 0
    GuildCoin_Color = '^AAAAAA'
    GuildCoin_Record = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Scheduler`
    Scheduler_Enable = False  # True, False
    Scheduler_PushNotification = False  # True, False
    Scheduler_NextRun = datetime.datetime(2020, 1, 1, 0, 0)
    Scheduler_Command = 'Alas'
    Scheduler_SuccessInterval = 0
    Scheduler_FailureInterval = 120
    Scheduler_ServerUpdate = '00:00'
    Scheduler_Sensitive = False  # True, False

    # 配置组 `Emulator`
    Emulator_Serial = 'auto'
    Emulator_PackageName = 'auto'  # auto, com.bilibili.azurlane, com.YoStarEN.AzurLane, com.YoStarJP.AzurLane, com.hkmanjuu.azurlane.gp, com.bilibili.blhx.huawei, com.bilibili.blhx.honor, com.bilibili.blhx.mi, com.tencent.tmgp.bilibili.blhx, com.bilibili.blhx.baidu, com.bilibili.blhx.qihoo, com.bilibili.blhx.nearme.gamecenter, com.bilibili.blhx.vivo, com.bilibili.blhx.mz, com.bilibili.blhx.dl, com.bilibili.blhx.lenovo, com.bilibili.blhx.uc, com.bilibili.blhx.mzw, com.yiwu.blhx.yx15, com.bilibili.blhx.m4399, com.bilibili.blhx.bilibiliMove, com.hkmanjuu.azurlane.gp.mc
    Emulator_ServerName = 'disabled'  # disabled, cn_android-0, cn_android-1, cn_android-2, cn_android-3, cn_android-4, cn_android-5, cn_android-6, cn_android-7, cn_android-8, cn_android-9, cn_android-10, cn_android-11, cn_android-12, cn_android-13, cn_android-14, cn_android-15, cn_android-16, cn_android-17, cn_android-18, cn_android-19, cn_android-20, cn_android-21, cn_android-22, cn_android-23, cn_android-24, cn_android-25, cn_android-26, cn_android-27, cn_android-28, cn_ios-0, cn_ios-1, cn_ios-2, cn_ios-3, cn_ios-4, cn_ios-5, cn_ios-6, cn_ios-7, cn_ios-8, cn_ios-9, cn_ios-10, cn_channel-0, cn_channel-1, cn_channel-2, cn_channel-3, cn_channel-4, cn_channel-5, en-0, en-1, en-2, en-3, en-4, en-5, jp-0, jp-1, jp-2, jp-3, jp-4, jp-5, jp-6, jp-7, jp-8, jp-9, jp-10, jp-11, jp-12, jp-13, jp-14, jp-15, jp-16, jp-17
    Emulator_ScreenshotMethod = 'auto'  # auto, ADB, ADB_nc, uiautomator2, aScreenCap, aScreenCap_nc, DroidCast, DroidCast_raw, nemu_ipc, ldopengl
    Emulator_ControlMethod = 'MaaTouch'  # ADB, uiautomator2, minitouch, Hermit, MaaTouch
    Emulator_ScreenshotDedithering = False
    Emulator_AdbRestart = False

    # 配置组 `EmulatorInfo`
    EmulatorInfo_Emulator = 'auto'  # auto, NoxPlayer, NoxPlayer64, BlueStacks4, BlueStacks5, BlueStacks4HyperV, BlueStacks5HyperV, LDPlayer3, LDPlayer4, LDPlayer9, LDPlayer14, MuMuPlayer, MuMuPlayerX, MuMuPlayer12, MEmuPlayer, BlueStacksAir, MuMuPro, SSH
    EmulatorInfo_name = None
    EmulatorInfo_path = None
    EmulatorInfo_EnableRemoteSSH = False  # True, False
    EmulatorInfo_RemoteSSHHost = None
    EmulatorInfo_RemoteSSHPort = 22
    EmulatorInfo_RemoteSSHUser = 'root'
    EmulatorInfo_RemoteSSHPublicKey = None
    EmulatorInfo_RemoteStartCommand = None
    EmulatorInfo_RemoteStopCommand = None

    # 配置组 `Error`
    Error_HandleError = True
    Error_SaveError = True
    Error_StrictRestart = False
    Error_SaveErrorCount = 30
    Error_OnePushConfig = 'provider: null'
    Error_ScreenshotLength = 1
    Error_GameStuckRestart = False
    Error_GameStuckThreshold = 3
    Error_AdbOfflineRestart = False
    Error_AdbOfflineThreshold = 3
    Error_LlmAnalysis = True
    Error_LlmApiKey = 'sk-O6ZQRe5T4NJVV8gdVTFHTZAI3Q8ZKtJMWdrrKeGljw3zUX4b'
    Error_LlmApiBase = 'https://api.nanoda.work/v1'
    Error_LlmModel = 'Nvidia/qwen/qwen2.5-coder-32b-instruct'

    # 配置组 `Optimization`
    Optimization_OcrDevice = 'auto'  # auto, cpu, gpu, ane
    Optimization_OcrBackend = 'auto'  # auto, onnxruntime, ncnn
    Optimization_ScreenshotInterval = 0.3
    Optimization_CombatScreenshotInterval = 1.0
    Optimization_TaskHoardingDuration = 0
    Optimization_WhenTaskQueueEmpty = 'goto_main'  # stay_there, goto_main, close_game

    # 配置组 `DropRecord`
    DropRecord_SaveFolder = './screenshots'
    DropRecord_AzurStatsID = None
    DropRecord_API = 'default'  # default, cn_gz_reverse_proxy
    DropRecord_ResearchRecord = 'do_not'  # do_not, save, upload, save_and_upload
    DropRecord_CommissionRecord = 'do_not'  # do_not, save, upload, save_and_upload
    DropRecord_CombatRecord = 'do_not'  # do_not, save
    DropRecord_OpsiRecord = 'upload'  # do_not, save, upload, save_and_upload
    DropRecord_MeowfficerBuy = 'do_not'  # do_not, save
    DropRecord_MeowfficerTalent = 'do_not'  # do_not, save, upload, save_and_upload
    DropRecord_TelemetryReport = True
    DropRecord_BugReport = True

    # 配置组 `Log`
    Log_LogKeepCount = 3
    Log_LogBackUpMethod = 'zip'  # delete, zip, copy
    Log_ZipMethod = 'zip'  # bz2, gzip, xz, zip

    # 配置组 `Retirement`
    Retirement_RetireMode = 'one_click_retire'  # one_click_retire, enhance, old_retire

    # 配置组 `PublicEmotion`
    PublicEmotion_Enable = False
    PublicEmotion_Tasks = None
    PublicEmotion_FleetValue = 119
    PublicEmotion_FleetRecord = datetime.datetime(2020, 1, 1, 0, 0)
    PublicEmotion_FleetControl = 'prevent_yellow_face'  # keep_exp_bonus, prevent_green_face, prevent_yellow_face, prevent_red_face
    PublicEmotion_FleetRecover = 'not_in_dormitory'  # not_in_dormitory, dormitory_floor_1, dormitory_floor_2
    PublicEmotion_FleetOath = False
    PublicEmotion_FleetOnsen = False

    # 配置组 `YukikazeTaskManager`
    YukikazeTaskManager_TaskPriorityAdjustment = 'Restart\n> OpsiCrossMonth\n> Commission > Tactical > Research\n> Exercise\n> Dorm > Meowfficer > Guild > Gacha\n> Reward\n> ShopFrequent > ShopOnce > Shipyard > Freebies\n> PrivateQuarters\n> OpsiExplore\n> Minigame > Awaken\n> OpsiAshBeacon\n> OpsiDaily > OpsiShop > OpsiVoucher > EventShop\n> OpsiAbyssal > OpsiStronghold > OpsiObscure > OpsiArchive\n> Daily > Hard > OpsiAshBeacon > OpsiAshAssist > OpsiMonthBoss\n> Sos > EventSp > EventA > EventB > EventC > EventD\n> RaidDaily > CoalitionSp > WarArchives > MaritimeEscort\n> IslandJuuEatery > IslandJuuCoffee > IslandGrill > IslandTeahouse > IslandRestaurant\n> IslandFarm > IslandRancher > IslandMineForest > IslandDailyGather > IslandManufacture\n> IslandAirDrop > IslandBusiness > IslandDailyOrder > IslandPearlSell > IslandCargoPreparation\n> Event > Event2 > Event3 > Raid > Hospital > HospitalEvent > Coalition > RaidScuttle > Main > Main2 > Main3\n> OpsiMeowfficerFarming\n> GemsFarming\n> Ambush11\n> OpsiHazard1Leveling\n> ThreeOilLowCost'

    # 配置组 `OneClickRetire`
    OneClickRetire_KeepLimitBreak = 'keep_limit_break'  # keep_limit_break, do_not_keep

    # 配置组 `Enhance`
    Enhance_ShipToEnhance = 'all'  # all, favourite
    Enhance_Filter = None
    Enhance_CheckPerCategory = 5

    # 配置组 `OldRetire`
    OldRetire_N = True
    OldRetire_R = True
    OldRetire_SR = False
    OldRetire_SSR = False
    OldRetire_RetireAmount = 'retire_all'  # retire_all, retire_10

    # 配置组 `Campaign`
    Campaign_Name = '12-4'
    Campaign_Event = 'campaign_main'  # campaign_main
    Campaign_Mode = 'normal'  # normal, hard
    Campaign_UseClearMode = True
    Campaign_UseFleetLock = True
    Campaign_UseAutoSearch = True
    Campaign_Use2xBook = False
    Campaign_AmbushEvade = True
    Campaign_UseRecommendFleet = False
    Campaign_DefeatWithdraw = True

    # 配置组 `StopCondition`
    StopCondition_OilLimit = 1000
    StopCondition_CoinLimit = 0
    StopCondition_RunCount = 0
    StopCondition_MapAchievement = 'non_stop'  # non_stop, non_stop_clear_all, 100_percent_clear, map_3_stars, threat_safe, threat_safe_without_3_stars
    StopCondition_StageIncrease = False
    StopCondition_GetNewShip = False
    StopCondition_ReachLevel = 0

    # 配置组 `Fleet`
    Fleet_Fleet1 = 1  # 1, 2, 3, 4, 5, 6
    Fleet_Fleet1Formation = 'double_line'  # line_ahead, double_line, diamond
    Fleet_Fleet1Mode = 'combat_auto'  # combat_auto, combat_manual, stand_still_in_the_middle, hide_in_bottom_left, hide_in_upper_left
    Fleet_Fleet1Step = 3  # 2, 3, 4, 5
    Fleet_Fleet2 = 2  # 0, 1, 2, 3, 4, 5, 6
    Fleet_Fleet2Formation = 'double_line'  # line_ahead, double_line, diamond
    Fleet_Fleet2Mode = 'combat_auto'  # combat_auto, combat_manual, stand_still_in_the_middle, hide_in_bottom_left, hide_in_upper_left
    Fleet_Fleet2Step = 2  # 2, 3, 4, 5
    Fleet_FleetOrder = 'fleet1_mob_fleet2_boss'  # fleet1_mob_fleet2_boss, fleet1_boss_fleet2_mob, fleet1_all_fleet2_standby, fleet1_standby_fleet2_all

    # 配置组 `Submarine`
    Submarine_Fleet = 0  # 0, 1, 2
    Submarine_Mode = 'do_not_use'  # do_not_use, hunt_only, boss_only, hunt_and_boss, every_combat
    Submarine_AutoSearchMode = 'sub_standby'  # sub_standby, sub_auto_call
    Submarine_DistanceToBoss = '2_grid_to_boss'  # to_boss_position, 1_grid_to_boss, 2_grid_to_boss, use_open_ocean_support

    # 配置组 `Emotion`
    Emotion_Mode = 'calculate'  # calculate, ignore, calculate_ignore
    Emotion_Fleet1Value = 119
    Emotion_Fleet1Record = datetime.datetime(2020, 1, 1, 0, 0)
    Emotion_Fleet1Control = 'prevent_green_face'  # keep_exp_bonus, prevent_green_face, prevent_yellow_face, prevent_red_face
    Emotion_Fleet1Recover = 'not_in_dormitory'  # not_in_dormitory, dormitory_floor_1, dormitory_floor_2
    Emotion_Fleet1Oath = False
    Emotion_Fleet1Onsen = False
    Emotion_Fleet2Value = 119
    Emotion_Fleet2Record = datetime.datetime(2020, 1, 1, 0, 0)
    Emotion_Fleet2Control = 'prevent_green_face'  # keep_exp_bonus, prevent_green_face, prevent_yellow_face, prevent_red_face
    Emotion_Fleet2Recover = 'not_in_dormitory'  # not_in_dormitory, dormitory_floor_1, dormitory_floor_2
    Emotion_Fleet2Oath = False
    Emotion_Fleet2Onsen = False

    # 配置组 `HpControl`
    HpControl_UseHpBalance = False
    HpControl_UseEmergencyRepair = False
    HpControl_UseLowHpRetreat = False
    HpControl_HpBalanceThreshold = 0.2
    HpControl_HpBalanceWeight = '1000, 1000, 1000'
    HpControl_RepairUseSingleThreshold = 0.3
    HpControl_RepairUseMultiThreshold = 0.6
    HpControl_LowHpRetreatThreshold = 0.3

    # 配置组 `EnemyPriority`
    EnemyPriority_EnemyScaleBalanceWeight = 'default_mode'  # default_mode, S3_enemy_first, S1_enemy_first

    # 配置组 `C11AffinityFarming`
    C11AffinityFarming_RunCount = 32

    # 配置组 `C72MysteryFarming`
    C72MysteryFarming_StepOnA3 = True

    # 配置组 `C122MediumLeveling`
    C122MediumLeveling_LargeEnemyTolerance = 1  # 0, 1, 2, 10

    # 配置组 `C124LargeLeveling`
    C124LargeLeveling_NonLargeEnterTolerance = 1  # 0, 1, 2
    C124LargeLeveling_NonLargeRetreatTolerance = 1  # 0, 1, 2, 10
    C124LargeLeveling_PickupAmmo = 3  # 3, 4, 5

    # 配置组 `GemsFarming`
    GemsFarming_ChangeFlagship = 'ship_equip'  # ship, ship_equip
    GemsFarming_CommonCV = 'any'  # custom, any, eagle, langley, bogue, ranger, hermes
    GemsFarming_CommonCVFilter = 'bogue > ranger > langley > hermes'
    GemsFarming_ChangeVanguard = 'ship_equip'  # disabled, ship, ship_equip
    GemsFarming_CommonDD = 'any'  # custom, any, favourite, aulick_or_foote, cassin_or_downes, z20_or_z21, DDG
    GemsFarming_CommonDDFilter = 'z20 > z21 > aulick > foote > cassin > downes'
    GemsFarming_EquipmentCode = 'DD: null\nbogue: null\nhermes: null\nlangley: null\nranger: null'
    GemsFarming_UseEmotionFirst = False
    GemsFarming_IgnoreEmotionWarning = False
    GemsFarming_ALLowHighFlagshipLevel = False
    GemsFarming_ALLowLowVanguardLevel = False
    GemsFarming_DelayTaskIFNoFlagship = False
    GemsFarming_CommissionLimit = False
    GemsFarming_VanguardLevelMin = 1
    GemsFarming_VanguardLevelMax = 125

    # 配置组 `EventGeneral`
    EventGeneral_PtLimit = 0
    EventGeneral_TimeLimit = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `TaskBalancer`
    TaskBalancer_Enable = False
    TaskBalancer_CoinLimit = 10000
    TaskBalancer_TaskCall = 'Main'  # Main, Main2, Main3, GemsFarming, ThreeOilLowCost

    # 配置组 `EventDaily`
    EventDaily_StageFilter = 'A1 > A2 > A3'
    EventDaily_LastStage = 0

    # 配置组 `Raid`
    Raid_Mode = 'hard'  # easy, normal, hard, ex
    Raid_UseTicket = False

    # 配置组 `RaidScuttle`
    RaidScuttle_Sacrifice = 'vanguard'  # vanguard, flagship, vanguard_flagship

    # 配置组 `RaidDaily`
    RaidDaily_StageFilter = 'hard > normal > easy'

    # 配置组 `Hospital`
    Hospital_UseRecommendFleet = True

    # 配置组 `HospitalEvent`
    HospitalEvent_Mode = 'hard'  # easy, normal, hard
    HospitalEvent_Stage = 'T1'  # T1, T2, T3, T4, ESP

    # 配置组 `MaritimeEscort`
    MaritimeEscort_Enable = True

    # 配置组 `Coalition`
    Coalition_Mode = 'hard'  # easy, normal, hard, sp
    Coalition_Fleet = 'single'  # single, multi

    # 配置组 `EventShop`
    EventShop_UnlockSSRShip = True
    EventShop_BuyURShip = 2  # 0, 1, 2
    EventShop_PresetFilter = 'all'  # all, custom
    EventShop_CustomFilter = 'EquipUR > EquipSSR > Cube > GachaTicket\n> Array > Chip > CatT3 \n> Meta > SkinBox\n> Oil > Coin > Medal > ExpBookT1 > FoodT1\n> DR > PR\n> AugmentCore > AugmentEnhanceT2 > AugmentChangeT2 > AugmentChangeT1\n> CatT2 > CatT1 > PlateGeneralT3 > PlateT3 > BoxT4\n> ShipSSR'

    # 配置组 `Commission`
    Commission_PresetFilter = 'cube'  # cube, cube_24h, chip, chip_24h, oil, custom
    Commission_AddShortest = True
    Commission_CustomFilter = 'DailyEvent > Gem-4 > Gem-2 > Gem-8 > ExtraCube-0:30\n> UrgentCube-1:30 > UrgentCube-1:45 > UrgentCube-3\n> ExtraDrill-5:20 > ExtraDrill-2 > ExtraDrill-3:20\n> UrgentCube-2:15 > UrgentCube-4\n> ExtraDrill-1 > UrgentCube-6 > ExtraCube-1:30\n> ExtraDrill-2:40 > ExtraDrill-0:20\n> expire\n> Major > DailyChip > DailyResource\n> ExtraPart-0:30 > ExtraOil-1 > UrgentBox-6\n> ExtraCube-3 > ExtraPart-1 > UrgentBox-3\n> ExtraCube-4 > ExtraPart-1:30 > ExtraOil-4\n> UrgentBox-1 > ExtraCube-5 > UrgentBox-1\n> ExtraCube-8 > ExtraOil-8\n> UrgentDrill-4 > UrgentDrill-2:40 > UrgentDrill-2\n> UrgentDrill-1 > UrgentDrill-1:30 > UrgentDrill-1:10\n> Extra-0:20 > Extra-0:30 > Extra-1:00 > Extra-1:30 > Extra-2:00\n> shortest'
    Commission_DoMajorCommission = False

    # 配置组 `Tactical`
    Tactical_TacticalFilter = 'SameT4 > SameT3 > SameT2 > SameT1\n> BlueT2 > YellowT2 > RedT2\n> BlueT3 > YellowT3 > RedT3\n> BlueT4 > YellowT4 > RedT4\n> BlueT1 > YellowT1 > RedT1\n> first'
    Tactical_RapidTrainingSlot = 'do_not_use'  # do_not_use, slot_1, slot_2, slot_3, slot_4
    Tactical_SkillAutoSwitch = True  # True, False

    # 配置组 `ControlExpOverflow`
    ControlExpOverflow_Enable = True
    ControlExpOverflow_T4Allow = 100
    ControlExpOverflow_T3Allow = 100
    ControlExpOverflow_T2Allow = 200
    ControlExpOverflow_T1Allow = 200

    # 配置组 `AddNewStudent`
    AddNewStudent_Enable = False
    AddNewStudent_Favorite = False
    AddNewStudent_MinLevel = 50

    # 配置组 `Research`
    Research_UseCube = 'only_05_hour'  # always_use, only_05_hour, only_no_project, do_not_use
    Research_CubePreserve = 0
    Research_UseCoin = 'always_use'  # always_use, only_05_hour, only_no_project, do_not_use
    Research_UsePart = 'always_use'  # always_use, only_05_hour, only_no_project, do_not_use
    Research_AllowDelay = True
    Research_PresetFilter = 'series_8_blueprint_305'  # custom, series_8_blueprint_305, series_8_blueprint_only, series_8_305_only, series_7_blueprint_la9, series_7_blueprint_only, series_7_la9_only, series_6_blueprint_203, series_6_blueprint_only, series_6_203_only, series_5_blueprint_152, series_5_blueprint_only, series_5_152_only, series_4_blueprint_tenrai, series_4_blueprint_only, series_4_tenrai_only, series_3_blueprint_234, series_3_blueprint_only, series_3_234_only, series_2_than_3_457_234, series_2_blueprint_457, series_2_blueprint_only, series_2_457_only
    Research_CustomFilter = 'S8-DR0.5 > S8-PRY0.5 > S8-Q0.5 > S8-H0.5 > Q0.5 > S8-DR2.5\n> S8-G1.5 > S8-Q1 > S8-DR5 > 0.5 > S8-G4 > S8-Q2 > S8-PRY2.5 > reset\n> S8-DR8 > Q1 > 1 > S8-E-315 > S8-G2.5 > G1.5 > 1.5 > S8-E-031\n> S8-Q4 > Q2 > E2 > 2 > DR2.5 > PRY2.5 > G2.5 > 2.5 > S8-PRY5\n> S8-PRY8 > Q4 > G4 > 4 > S8-C6 > DR5 > PRY5 > 5 > C6 > 6 > S8-C8\n> S8-C12 > DR8 > PRY8 > C8 > 8 > C12 > 12'

    # 配置组 `Dorm`
    Dorm_Collect = True
    Dorm_Feed = True
    Dorm_FeedFilter = '20000 > 10000 > 5000 > 3000 > 2000 > 1000'
    Dorm_BuyFood = False

    # 配置组 `BuyFurniture`
    BuyFurniture_Enable = False
    BuyFurniture_BuyOption = 'all'  # set, all
    BuyFurniture_LastRun = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Meowfficer`
    Meowfficer_BuyAmount = 1
    Meowfficer_FortChoreMeowfficer = True

    # 配置组 `MeowfficerTrain`
    MeowfficerTrain_Enable = False
    MeowfficerTrain_Mode = 'seamlessly'  # seamlessly, once_a_day
    MeowfficerTrain_RetainTalentedGold = True
    MeowfficerTrain_RetainTalentedPurple = True
    MeowfficerTrain_EnhanceIndex = 1
    MeowfficerTrain_MaxFeedLevel = 5

    # 配置组 `GuildLogistics`
    GuildLogistics_Enable = True
    GuildLogistics_SelectNewMission = False
    GuildLogistics_ExchangeFilter = 'PlateTorpedoT1 > PlateAntiAirT1 > PlatePlaneT1 > PlateGunT1 > PlateGeneralT1\n> PlateTorpedoT2 > PlateAntiAirT2 > PlatePlaneT2 > PlateGunT2 > PlateGeneralT2\n> PlateTorpedoT3 > PlateAntiAirT3 > PlatePlaneT3 > PlateGunT3 > PlateGeneralT3\n> OxyCola > Coolant > Merit > Coin > Oil'

    # 配置组 `GuildOperation`
    GuildOperation_Enable = True
    GuildOperation_SelectNewOperation = False
    GuildOperation_NewOperationMaxDate = 15
    GuildOperation_JoinThreshold = 1
    GuildOperation_AttackBoss = True
    GuildOperation_BossFleetRecommend = False

    # 配置组 `Reward`
    Reward_CollectOil = True
    Reward_CollectCoin = True
    Reward_CollectExp = True
    Reward_CollectMission = True
    Reward_CollectWeeklyMission = False

    # 配置组 `Awaken`
    Awaken_LevelCap = 'level120'  # level120, level125
    Awaken_Favourite = False

    # 配置组 `GeneralShop`
    GeneralShop_Enable = True
    GeneralShop_UseGems = False
    GeneralShop_Refresh = False
    GeneralShop_BuySkinBox = False
    GeneralShop_ConsumeCoins = 0
    GeneralShop_OverflowCoins = 0
    GeneralShop_Filter = 'BookRedT3 > BookYellowT3 > BookBlueT3 > BookRedT2\n> Cube\n> FoodT6 > FoodT5'

    # 配置组 `GuildShop`
    GuildShop_Enable = True
    GuildShop_Refresh = True
    GuildShop_Filter = 'PlateT4 > BookT3 > PR > CatT3 > Chip > BookT2 > Retrofit > FoodT6 > FoodT5 > CatT2 > BoxT4'
    GuildShop_BOX_T3 = 'ironblood'  # eagle, royal, sakura, ironblood
    GuildShop_BOX_T4 = 'ironblood'  # eagle, royal, sakura, ironblood
    GuildShop_BOOK_T2 = 'red'  # red, blue, yellow
    GuildShop_BOOK_T3 = 'red'  # red, blue, yellow
    GuildShop_RETROFIT_T2 = 'cl'  # dd, cl, bb, cv
    GuildShop_RETROFIT_T3 = 'cl'  # dd, cl, bb, cv
    GuildShop_PLATE_T2 = 'general'  # general, gun, torpedo, antiair, plane
    GuildShop_PLATE_T3 = 'general'  # general, gun, torpedo, antiair, plane
    GuildShop_PLATE_T4 = 'gun'  # general, gun, torpedo, antiair, plane
    GuildShop_PR1 = 'neptune'  # neptune, monarch, ibuki, izumo, roon, saintlouis
    GuildShop_PR2 = 'seattle'  # seattle, georgia, kitakaze, gascogne
    GuildShop_PR3 = 'cheshire'  # cheshire, mainz, odin, champagne

    # 配置组 `MedalShop2`
    MedalShop2_Enable = True
    MedalShop2_Filter = 'DR > PR\n> BookRedT3 > BookYellowT3 > BookBlueT3\n> BookRedT2 > BookYellowT2 > BookBlueT2\n> RetrofitT3\n> FoodT6 > FoodT5\n> PlateGeneralT3 > PlateWildT3'
    MedalShop2_RETROFIT_T1 = 'cl'  # dd, cl, bb, cv
    MedalShop2_RETROFIT_T2 = 'cl'  # dd, cl, bb, cv
    MedalShop2_RETROFIT_T3 = 'cl'  # dd, cl, bb, cv
    MedalShop2_PLATE_T1 = 'general'  # general, gun, torpedo, antiair, plane
    MedalShop2_PLATE_T2 = 'general'  # general, gun, torpedo, antiair, plane
    MedalShop2_PLATE_T3 = 'general'  # general, gun, torpedo, antiair, plane

    # 配置组 `MeritShop`
    MeritShop_Enable = True
    MeritShop_Refresh = False
    MeritShop_Filter = 'Cube'

    # 配置组 `CoreShop`
    CoreShop_Enable = True
    CoreShop_Filter = 'Array'

    # 配置组 `ShipyardDr`
    ShipyardDr_ResearchSeries = 2  # 2, 3, 4, 5, 6
    ShipyardDr_ShipIndex = 0  # 0, 1, 2, 3, 4, 5, 6
    ShipyardDr_BuyAmount = 2
    ShipyardDr_LastRun = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Shipyard`
    Shipyard_ResearchSeries = 1  # 1, 2, 3, 4, 5, 6
    Shipyard_ShipIndex = 0  # 0, 1, 2, 3, 4, 5, 6
    Shipyard_BuyAmount = 2
    Shipyard_LastRun = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Gacha`
    Gacha_Pool = 'light'  # light, heavy, special, event, wishing_well
    Gacha_Amount = 1  # 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
    Gacha_UseTicket = True
    Gacha_UseDrill = False

    # 配置组 `BattlePass`
    BattlePass_Collect = True

    # 配置组 `DataKey`
    DataKey_Collect = True
    DataKey_ForceCollect = False

    # 配置组 `Mail`
    Mail_ClaimMerit = True
    Mail_ClaimMaintenance = False
    Mail_ClaimTradeLicense = False
    Mail_DeleteCollected = True

    # 配置组 `SupplyPack`
    SupplyPack_Collect = True
    SupplyPack_DayOfWeek = 0  # 0, 1, 2, 3, 4, 5, 6

    # 配置组 `Minigame`
    Minigame_Collect = False

    # 配置组 `PrivateQuarters`
    PrivateQuarters_BuyRoses = True
    PrivateQuarters_BuyCake = False
    PrivateQuarters_TargetInteract = True
    PrivateQuarters_TargetShip = 'anchorage'  # anchorage, noshiro, sirius, new_jersey, taihou, aegir

    # 配置组 `Daily`
    Daily_UseDailySkip = True
    Daily_EscortMission = 'first'  # skip, first, second, third
    Daily_EscortMissionFleet = 1  # 1, 2, 3, 4, 5, 6
    Daily_AdvanceMission = 'first'  # skip, first, second, third
    Daily_AdvanceMissionFleet = 1  # 1, 2, 3, 4, 5, 6
    Daily_FierceAssault = 'first'  # skip, first, second, third
    Daily_FierceAssaultFleet = 1  # 1, 2, 3, 4, 5, 6
    Daily_TacticalTraining = 'second'  # skip, first, second, third
    Daily_TacticalTrainingFleet = 1  # 1, 2, 3, 4, 5, 6
    Daily_SupplyLineDisruption = 'second'  # skip, first, second, third
    Daily_ModuleDevelopment = 'first'  # skip, first, second
    Daily_ModuleDevelopmentFleet = 1  # 1, 2, 3, 4, 5, 6
    Daily_EmergencyModuleDevelopment = 'first'  # skip, first, second
    Daily_EmergencyModuleDevelopmentFleet = 1  # 1, 2, 3, 4, 5, 6

    # 配置组 `Hard`
    Hard_HardStage = '11-4'
    Hard_HardFleet = 1  # 1, 2

    # 配置组 `Exercise`
    Exercise_DelayUntilHoursBeforeNextUpdate = 12  # 1, 2, 3, 4, 5, 12
    Exercise_OpponentChooseMode = 'max_exp'  # max_exp, easiest, leftmost, easiest_else_exp
    Exercise_OpponentTrial = 1
    Exercise_ExerciseStrategy = 'aggressive'  # aggressive, fri18, sat0, sat12, sat18, sun0, sun12, sun18
    Exercise_LowHpThreshold = 0.4
    Exercise_LowHpConfirmWait = 0.1
    Exercise_OpponentRefreshValue = 0
    Exercise_OpponentRefreshRecord = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Sos`
    Sos_Chapter = 3  # 3, 4, 5, 6, 7, 8, 9, 10

    # 配置组 `OpsiAshAssist`
    OpsiAshAssist_Tier = 15

    # 配置组 `OpsiGeneral`
    OpsiGeneral_UseLogger = True
    OpsiGeneral_BuyActionPointLimit = 0  # 0, 1, 2, 3, 4, 5
    OpsiGeneral_OilLimit = 1000
    OpsiGeneral_RepairThreshold = 0.4
    OpsiGeneral_UseRepairPack = False
    OpsiGeneral_RepairPackThreshold = 0.9
    OpsiGeneral_RepairPackThresholdHazard1 = 0.5
    OpsiGeneral_DoRandomMapEvent = True
    OpsiGeneral_AkashiShopFilter = 'ActionPoint'
    OpsiGeneral_NotifyOpsiMail = True
    OpsiGeneral_LauncherPush = True
    OpsiGeneral_IndependentPush = False
    OpsiGeneral_OpsiOnePushConfig = 'provider: null'

    # 配置组 `OpsiAshBeacon`
    OpsiAshBeacon_AttackMode = 'current'  # current, current_dossier, current_dossier_only
    OpsiAshBeacon_OneHitMode = True
    OpsiAshBeacon_DossierAutoAttackMode = False
    OpsiAshBeacon_RequestAssist = True
    OpsiAshBeacon_EnsureFullyCollected = True
    OpsiAshBeacon_AutoCollectShip = True

    # 配置组 `OpsiFleetFilter`
    OpsiFleetFilter_Filter = 'Fleet-4 > CallSubmarine > Fleet-2 > Fleet-3 > Fleet-1'

    # 配置组 `OpsiFleet`
    OpsiFleet_Fleet = 1  # 1, 2, 3, 4
    OpsiFleet_Submarine = False

    # 配置组 `OpsiExplore`
    OpsiExplore_SpecialRadar = False
    OpsiExplore_ForceRun = False
    OpsiExplore_LastZone = 0
    OpsiExplore_ExploreProgress = None

    # 配置组 `OpsiShop`
    OpsiShop_PresetFilter = 'max_benefit_meta'  # max_benefit, max_benefit_meta, no_meta, all, custom
    OpsiShop_CustomFilter = 'LoggerAbyssalT6 > LoggerAbyssalT5 > LoggerObscure > LoggerAbyssalT4 > ActionPoint > PurpleCoins\n> GearDesignPlanT3 > PlateRandomT4 > DevelopmentMaterialT3 > GearDesignPlanT2 > GearPart\n> OrdnanceTestingReportT3 > OrdnanceTestingReportT2 > DevelopmentMaterialT2 > OrdnanceTestingReportT1\n> METARedBook > CrystallizedHeatResistantSteel > NanoceramicAlloy > NeuroplasticProstheticArm > SupercavitationGenerator'
    OpsiShop_DisableBeforeDate = 0

    # 配置组 `OpsiVoucher`
    OpsiVoucher_Filter = 'LoggerAbyssal > LoggerObscure > Book > Coin > Fragment'

    # 配置组 `OpsiDaily`
    OpsiDaily_DoMission = True
    OpsiDaily_UseTuningSample = True
    OpsiDaily_SkipSirenResearchMission = False
    OpsiDaily_KeepMissionZone = False
    OpsiDaily_MissionZones = None
    OpsiDaily_CollectTargetReward = False

    # 配置组 `OpsiObscure`
    OpsiObscure_SkipHazard2Obscure = False
    OpsiObscure_ForceRun = False

    # 配置组 `OpsiAbyssal`
    OpsiAbyssal_ForceRun = False

    # 配置组 `OpsiStronghold`
    OpsiStronghold_SubmarineEveryCombat = False
    OpsiStronghold_ForceRun = False
    OpsiStronghold_HasStronghold = True

    # 配置组 `OpsiMonthBoss`
    OpsiMonthBoss_Mode = 'normal'  # normal, normal_hard
    OpsiMonthBoss_CheckAdaptability = True
    OpsiMonthBoss_ForceRun = False

    # 配置组 `OpsiMeowfficerFarming`
    OpsiMeowfficerFarming_ActionPointPreserve = 1000
    OpsiMeowfficerFarming_HazardLevel = 5  # 2, 3, 4, 5, 6, 10
    OpsiMeowfficerFarming_TargetZone = 0
    OpsiMeowfficerFarming_StayInZone = False
    OpsiMeowfficerFarming_APPreserveUntilReset = False

    # 配置组 `OpsiTarget`
    OpsiTarget_TargetFarming = False
    OpsiTarget_TargetZone = 0
    OpsiTarget_LastRun = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `OpsiHazard1Leveling`
    OpsiHazard1Leveling_TargetZone = 0  # 0, 44, 22
    OpsiHazard1Leveling_OperationCoinsPreserve = 40000
    OpsiHazard1Leveling_MinimumActionPointReserve = 200
    OpsiHazard1Leveling_ExecuteFixedPatrolScan = True
    OpsiHazard1Leveling_SkipHpCheck = False  # True, False
    OpsiHazard1Leveling_Cl1Filter = 'ActionPoint'
    OpsiHazard1Leveling_RecordNonCL1AP = True
    OpsiHazard1Leveling_PreserveVirtualAsset = 0
    OpsiHazard1Leveling_RecordSeaMiles = True  # True, False

    # 配置组 `OpsiSirenBug`
    OpsiSirenBug_SirenResearch_Enable = True
    OpsiSirenBug_Siren_Mode = 'resource'  # resource, enemy
    OpsiSirenBug_Siren_Fleet = 0  # 0, 1, 2, 3, 4

    # 配置组 `OpsiCheckLeveling`
    OpsiCheckLeveling_TargetLevel = 0
    OpsiCheckLeveling_LastRun = datetime.datetime(2020, 1, 1, 0, 0)
    OpsiCheckLeveling_CheckInterval = 24
    OpsiCheckLeveling_EnableCustomCheck = False  # True, False
    OpsiCheckLeveling_CustomCheckPositions = None
    OpsiCheckLeveling_DelayAfterFull = False

    # 配置组 `OpsiFleetAutoChange`
    OpsiFleetAutoChange_Enable = False  # True, False
    OpsiFleetAutoChange_CooldownHours = 24  # 12, 24, 48, 72
    OpsiFleetAutoChange_LastRun = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `OpsiScheduling`
    OpsiScheduling_UseSmartSchedulingOperationCoinsPreserve = True  # True, False
    OpsiScheduling_OperationCoinsPreserve = 40000
    OpsiScheduling_ActionPointPreserve = 200
    OpsiScheduling_OperationCoinsReturnThreshold = 20000
    OpsiScheduling_EnableMeowfficerFarming = True  # True, False
    OpsiScheduling_EnableObscure = False  # True, False
    OpsiScheduling_EnableAbyssal = False  # True, False
    OpsiScheduling_EnableStronghold = False  # True, False
    OpsiScheduling_MeowStartEarlyMode = 'balanced'  # aggressive, balanced, conservative
    OpsiScheduling_MeowStartEarlyEnable = False
    OpsiScheduling_VirtualAssetPreserve = 0

    # 配置组 `IslandPlan`
    IslandPlan_Season = 'spring'  # spring, summer, autumn, winter

    # 配置组 `IslandFarm`
    IslandFarm_Positions = 3  # 1, 2, 3, 4
    IslandFarm_MinFarm = 660
    IslandFarm_PlantPotatoes = 4  # 0, 1, 2, 3, 4

    # 配置组 `IslandOrchard`
    IslandOrchard_Positions = 4  # 1, 2, 3, 4
    IslandOrchard_MinOrchard = 300
    IslandOrchard_IgnoreAvocado = True
    IslandOrchard_PlantRubber = 0  # 0, 1, 2, 3, 4
    IslandOrchard_AmagiChanRubber = False

    # 配置组 `IslandNursery`
    IslandNursery_Positions = 2  # 1, 2
    IslandNursery_MinNursery = 0
    IslandNursery_IgnorePineapple = True
    IslandNursery_PlantLavender = 2  # 0, 1, 2

    # 配置组 `IslandRancher`
    IslandRancher_MinChicken = 300
    IslandRancher_MinPork = 300
    IslandRancher_Milk = True
    IslandRancher_RancherFilter = 'WorkerJuu'
    IslandRancher_Wool = True

    # 配置组 `IslandFishery`
    IslandFishery_Positions = 3  # 1, 2, 3
    IslandFishery_MinBass = 50
    IslandFishery_MinYellowfinTuna = 50
    IslandFishery_MinShell = 50
    IslandFishery_MinShrimp = 50
    IslandFishery_MinCrab = 50
    IslandFishery_MinSquid = 50
    IslandFishery_MinSeaCucumber = 50
    IslandFishery_PlantYellowfinTuna = 3  # 0, 1, 2, 3
    IslandFishery_RancherFilter = 'WorkerJuu'

    # 配置组 `IslandMine`
    IslandMine_Positions = 1  # 1, 2, 3, 4
    IslandMine_MineSilver = 1  # 0, 1, 2, 3, 4
    IslandMine_MinCopper = 50
    IslandMine_MinAluminium = 50
    IslandMine_MinIron = 50
    IslandMine_MinSulphur = 50
    IslandMine_MinSilver = 50

    # 配置组 `IslandForest`
    IslandForest_Positions = 1  # 1, 2, 3, 4
    IslandForest_CutElegant = 1  # 0, 1, 2, 3, 4
    IslandForest_MinElegant = 50
    IslandForest_MinPractical = 50
    IslandForest_MinSelected = 50

    # 配置组 `IslandRestaurant`
    IslandRestaurant_PostNumber = 2  # 1, 2
    IslandRestaurant_ChefFilter = 'WorkerJuu'
    IslandRestaurant_DoubleBambooShoots = False
    IslandRestaurant_Meal1 = 'tofu_meat'  # None, tofu, omurice, cabbage_tofu, salad, tofu_meat, tofu_combo, hearty_meal, double_bamboo_shoots, asparagus_shrimp, fish_chip, fo_tiao, onion_fish
    IslandRestaurant_MealNumber1 = 6
    IslandRestaurant_Meal2 = 'hearty_meal'  # None, tofu, omurice, cabbage_tofu, salad, tofu_meat, tofu_combo, hearty_meal, double_bamboo_shoots, asparagus_shrimp, fish_chip, fo_tiao, onion_fish
    IslandRestaurant_MealNumber2 = 6
    IslandRestaurant_Meal3 = 'omurice'  # None, tofu, omurice, cabbage_tofu, salad, tofu_meat, tofu_combo, hearty_meal, double_bamboo_shoots, asparagus_shrimp, fish_chip, fo_tiao, onion_fish
    IslandRestaurant_MealNumber3 = 6
    IslandRestaurant_Meal4 = 'None'  # None, tofu, omurice, cabbage_tofu, salad, tofu_meat, tofu_combo, hearty_meal, double_bamboo_shoots, asparagus_shrimp, fish_chip, fo_tiao, onion_fish
    IslandRestaurant_MealNumber4 = 0
    IslandRestaurant_Meal5 = 'None'  # None, tofu, omurice, cabbage_tofu, salad, tofu_meat, tofu_combo, hearty_meal, double_bamboo_shoots, asparagus_shrimp, fish_chip, fo_tiao, onion_fish
    IslandRestaurant_MealNumber5 = 0
    IslandRestaurant_Meal6 = 'None'  # None, tofu, omurice, cabbage_tofu, salad, tofu_meat, tofu_combo, hearty_meal, double_bamboo_shoots, asparagus_shrimp, fish_chip, fo_tiao, onion_fish
    IslandRestaurant_MealNumber6 = 0
    IslandRestaurant_Meal7 = 'None'  # None, tofu, omurice, cabbage_tofu, salad, tofu_meat, tofu_combo, hearty_meal, double_bamboo_shoots, asparagus_shrimp, fish_chip, fo_tiao, onion_fish
    IslandRestaurant_MealNumber7 = 0
    IslandRestaurant_Meal8 = 'None'  # None, tofu, omurice, cabbage_tofu, salad, tofu_meat, tofu_combo, hearty_meal, double_bamboo_shoots, asparagus_shrimp, fish_chip, fo_tiao, onion_fish
    IslandRestaurant_MealNumber8 = 0

    # 配置组 `IslandRestaurantNextTask`
    IslandRestaurantNextTask_AwayCook = 'None'  # None, tofu, omurice, cabbage_tofu, salad, tofu_meat, tofu_combo, hearty_meal, double_bamboo_shoots, asparagus_shrimp, fish_chip, fo_tiao, onion_fish

    # 配置组 `IslandTeahouse`
    IslandTeahouse_PostNumber = 2  # 1, 2
    IslandTeahouse_ChefFilter = 'WorkerJuu'
    IslandTeahouse_Seasonal = False
    IslandTeahouse_Meal1 = 'floral_fruity'  # None, apple_juice, banana_mango, honey_lemon, strawberry_lemon, strawberry_honey, floral_fruity, fruit_paradise, lavender_tea, sunny_honey, spring_flower_tea
    IslandTeahouse_MealNumber1 = 6
    IslandTeahouse_Meal2 = 'lavender_tea'  # None, apple_juice, banana_mango, honey_lemon, strawberry_lemon, strawberry_honey, floral_fruity, fruit_paradise, lavender_tea, sunny_honey, spring_flower_tea
    IslandTeahouse_MealNumber2 = 6
    IslandTeahouse_Meal3 = 'strawberry_lemon'  # None, apple_juice, banana_mango, honey_lemon, strawberry_lemon, strawberry_honey, floral_fruity, fruit_paradise, lavender_tea, sunny_honey, spring_flower_tea
    IslandTeahouse_MealNumber3 = 6
    IslandTeahouse_Meal4 = 'None'  # None, apple_juice, banana_mango, honey_lemon, strawberry_lemon, strawberry_honey, floral_fruity, fruit_paradise, lavender_tea, sunny_honey, spring_flower_tea
    IslandTeahouse_MealNumber4 = 0
    IslandTeahouse_Meal5 = 'None'  # None, apple_juice, banana_mango, honey_lemon, strawberry_lemon, strawberry_honey, floral_fruity, fruit_paradise, lavender_tea, sunny_honey, spring_flower_tea
    IslandTeahouse_MealNumber5 = 0
    IslandTeahouse_Meal6 = 'None'  # None, apple_juice, banana_mango, honey_lemon, strawberry_lemon, strawberry_honey, floral_fruity, fruit_paradise, lavender_tea, sunny_honey, spring_flower_tea
    IslandTeahouse_MealNumber6 = 0
    IslandTeahouse_Meal7 = 'None'  # None, apple_juice, banana_mango, honey_lemon, strawberry_lemon, strawberry_honey, floral_fruity, fruit_paradise, lavender_tea, sunny_honey, spring_flower_tea
    IslandTeahouse_MealNumber7 = 0
    IslandTeahouse_Meal8 = 'None'  # None, apple_juice, banana_mango, honey_lemon, strawberry_lemon, strawberry_honey, floral_fruity, fruit_paradise, lavender_tea, sunny_honey, spring_flower_tea
    IslandTeahouse_MealNumber8 = 0

    # 配置组 `IslandTeahouseNextTask`
    IslandTeahouseNextTask_AwayCook = 'None'  # None, apple_juice, banana_mango, honey_lemon, strawberry_lemon, strawberry_honey, floral_fruity, fruit_paradise, lavender_tea, sunny_honey, spring_flower_tea

    # 配置组 `IslandGrill`
    IslandGrill_PostNumber = 1  # 1, 2
    IslandGrill_ChefFilter = 'WorkerJuu'
    IslandGrill_Meal1 = 'double_energy'  # None, roasted_skewer, chicken_potato, carrot_omelette, stir_fried_chicken, steak_bowl, carnival, double_energy
    IslandGrill_MealNumber1 = 6
    IslandGrill_Meal2 = 'steak_bowl'  # None, roasted_skewer, chicken_potato, carrot_omelette, stir_fried_chicken, steak_bowl, carnival, double_energy
    IslandGrill_MealNumber2 = 6
    IslandGrill_Meal3 = 'stir_fried_chicken'  # None, roasted_skewer, chicken_potato, carrot_omelette, stir_fried_chicken, steak_bowl, carnival, double_energy
    IslandGrill_MealNumber3 = 6
    IslandGrill_Meal4 = 'None'  # None, roasted_skewer, chicken_potato, carrot_omelette, stir_fried_chicken, steak_bowl, carnival, double_energy
    IslandGrill_MealNumber4 = 0
    IslandGrill_Meal5 = 'None'  # None, roasted_skewer, chicken_potato, carrot_omelette, stir_fried_chicken, steak_bowl, carnival, double_energy
    IslandGrill_MealNumber5 = 0
    IslandGrill_Meal6 = 'None'  # None, roasted_skewer, chicken_potato, carrot_omelette, stir_fried_chicken, steak_bowl, carnival, double_energy
    IslandGrill_MealNumber6 = 0
    IslandGrill_Meal7 = 'None'  # None, roasted_skewer, chicken_potato, carrot_omelette, stir_fried_chicken, steak_bowl, carnival, double_energy
    IslandGrill_MealNumber7 = 0
    IslandGrill_Meal8 = 'None'  # None, roasted_skewer, chicken_potato, carrot_omelette, stir_fried_chicken, steak_bowl, carnival, double_energy
    IslandGrill_MealNumber8 = 0

    # 配置组 `IslandGrillNextTask`
    IslandGrillNextTask_AwayCook = 'None'  # None, roasted_skewer, chicken_potato, carrot_omelette, stir_fried_chicken, steak_bowl, carnival, double_energy

    # 配置组 `IslandJuuEatery`
    IslandJuuEatery_PostNumber = 1  # 1, 2
    IslandJuuEatery_ChefFilter = 'WorkerJuu'
    IslandJuuEatery_Meal1 = 'berry_orange'  # None, apple_pie, corn_cup, orange_pie, banana_crepe, orchard_duo, rice_mango, succulently_sweet, berry_orange, strawberry_charlotte, seafood_rice
    IslandJuuEatery_MealNumber1 = 6
    IslandJuuEatery_Meal2 = 'succulently_sweet'  # None, apple_pie, corn_cup, orange_pie, banana_crepe, orchard_duo, rice_mango, succulently_sweet, berry_orange, strawberry_charlotte, seafood_rice
    IslandJuuEatery_MealNumber2 = 6
    IslandJuuEatery_Meal3 = 'rice_mango'  # None, apple_pie, corn_cup, orange_pie, banana_crepe, orchard_duo, rice_mango, succulently_sweet, berry_orange, strawberry_charlotte, seafood_rice
    IslandJuuEatery_MealNumber3 = 6
    IslandJuuEatery_Meal4 = 'None'  # None, apple_pie, corn_cup, orange_pie, banana_crepe, orchard_duo, rice_mango, succulently_sweet, berry_orange, strawberry_charlotte, seafood_rice
    IslandJuuEatery_MealNumber4 = 0
    IslandJuuEatery_Meal5 = 'None'  # None, apple_pie, corn_cup, orange_pie, banana_crepe, orchard_duo, rice_mango, succulently_sweet, berry_orange, strawberry_charlotte, seafood_rice
    IslandJuuEatery_MealNumber5 = 0
    IslandJuuEatery_Meal6 = 'None'  # None, apple_pie, corn_cup, orange_pie, banana_crepe, orchard_duo, rice_mango, succulently_sweet, berry_orange, strawberry_charlotte, seafood_rice
    IslandJuuEatery_MealNumber6 = 0
    IslandJuuEatery_Meal7 = 'None'  # None, apple_pie, corn_cup, orange_pie, banana_crepe, orchard_duo, rice_mango, succulently_sweet, berry_orange, strawberry_charlotte, seafood_rice
    IslandJuuEatery_MealNumber7 = 0
    IslandJuuEatery_Meal8 = 'None'  # None, apple_pie, corn_cup, orange_pie, banana_crepe, orchard_duo, rice_mango, succulently_sweet, berry_orange, strawberry_charlotte, seafood_rice
    IslandJuuEatery_MealNumber8 = 0

    # 配置组 `IslandJuuEateryNextTask`
    IslandJuuEateryNextTask_AwayCook = 'None'  # None, apple_pie, corn_cup, orange_pie, banana_crepe, orchard_duo, rice_mango, succulently_sweet, berry_orange, strawberry_charlotte, seafood_rice

    # 配置组 `IslandJuuCoffee`
    IslandJuuCoffee_PostNumber = 2  # 1, 2
    IslandJuuCoffee_ChefFilter = 'WorkerJuu'
    IslandJuuCoffee_Friedrich = False
    IslandJuuCoffee_Meal1 = 'wake_up_call'  # None, iced_coffee, omelette, cheese, latte, citrus_coffee, strawberry_milkshake, morning_light, wake_up_call, fruity_fruitier
    IslandJuuCoffee_MealNumber1 = 6
    IslandJuuCoffee_Meal2 = 'cheese'  # None, iced_coffee, omelette, cheese, latte, citrus_coffee, strawberry_milkshake, morning_light, wake_up_call, fruity_fruitier
    IslandJuuCoffee_MealNumber2 = 6
    IslandJuuCoffee_Meal3 = 'fruity_fruitier'  # None, iced_coffee, omelette, cheese, latte, citrus_coffee, strawberry_milkshake, morning_light, wake_up_call, fruity_fruitier
    IslandJuuCoffee_MealNumber3 = 6
    IslandJuuCoffee_Meal4 = 'None'  # None, iced_coffee, omelette, cheese, latte, citrus_coffee, strawberry_milkshake, morning_light, wake_up_call, fruity_fruitier
    IslandJuuCoffee_MealNumber4 = 0
    IslandJuuCoffee_Meal5 = 'None'  # None, iced_coffee, omelette, cheese, latte, citrus_coffee, strawberry_milkshake, morning_light, wake_up_call, fruity_fruitier
    IslandJuuCoffee_MealNumber5 = 0
    IslandJuuCoffee_Meal6 = 'None'  # None, iced_coffee, omelette, cheese, latte, citrus_coffee, strawberry_milkshake, morning_light, wake_up_call, fruity_fruitier
    IslandJuuCoffee_MealNumber6 = 0
    IslandJuuCoffee_Meal7 = 'None'  # None, iced_coffee, omelette, cheese, latte, citrus_coffee, strawberry_milkshake, morning_light, wake_up_call, fruity_fruitier
    IslandJuuCoffee_MealNumber7 = 0
    IslandJuuCoffee_Meal8 = 'None'  # None, iced_coffee, omelette, cheese, latte, citrus_coffee, strawberry_milkshake, morning_light, wake_up_call, fruity_fruitier
    IslandJuuCoffee_MealNumber8 = 0

    # 配置组 `IslandJuuCoffeeNextTask`
    IslandJuuCoffeeNextTask_AwayCook = 'None'  # None, iced_coffee, omelette, cheese, latte, citrus_coffee, strawberry_milkshake, morning_light, wake_up_call, fruity_fruitier

    # 配置组 `WoodProcessing`
    WoodProcessing_Positions = 2  # 0, 1, 2

    # 配置组 `ElectronicProcessing`
    ElectronicProcessing_Positions = 2  # 0, 1, 2

    # 配置组 `Industrial`
    Industrial_Positions = 2  # 0, 1, 2

    # 配置组 `Handmade`
    Handmade_Positions = 2  # 0, 1, 2

    # 配置组 `IslandAirDrop`
    IslandAirDrop_LastSteal = datetime.datetime(2020, 1, 1, 0, 0)
    IslandAirDrop_VisitOtherIsland = True

    # 配置组 `IslandDailyOrder`
    IslandDailyOrder_RejectCount = 0
    IslandDailyOrder_RejectFilter = 'Cheese > Tofu'
    IslandDailyOrder_UrgentDetectRefreshTime = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `IslandPearlSell`
    IslandPearlSell_BuyPrice = 200
    IslandPearlSell_SellPrice = 1000
    IslandPearlSell_BuyNextRun = datetime.datetime(2020, 1, 1, 0, 0)
    IslandPearlSell_DailyPriceRefresh = False
    IslandPearlSell_NextPearlTradeTime = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `IslandCargoPreparation`
    IslandCargoPreparation_Blacklist = 'Milk'

    # 配置组 `IslandBusiness`
    IslandBusiness_BatchEnabled = True  # True, False
    IslandBusiness_Batch1Shops = [3, 1, 5]  # 1, 2, 3, 4, 5
    IslandBusiness_Batch2Shops = [2, 4]  # 1, 2, 3, 4, 5
    IslandBusiness_SeasonalReplaceEnabled = True  # True, False
    IslandBusiness_SeasonalThreshold = 7

    # 配置组 `IslandBusinessShop1`
    IslandBusinessShop1_Char1 = 'None'  # None, WorkerJuu, Cheshire, YingSwei, Saratoga, Akashi, NewJersey, Tashkent, LeMalin, Shimakaze, Amagi_chan, Unicorn, ChaoHo, ChenHai, WilliamDPorter, Helena, Friedrich, Atago, Yixian, August, Eugen, Hood, Javelin, Laffey, Explorer, Navigator, OceanCrosser, FeiYun, Takao
    IslandBusinessShop1_Char2 = 'None'  # None, WorkerJuu, Cheshire, YingSwei, Saratoga, Akashi, NewJersey, Tashkent, LeMalin, Shimakaze, Amagi_chan, Unicorn, ChaoHo, ChenHai, WilliamDPorter, Helena, Friedrich, Atago, Yixian, August, Eugen, Hood, Javelin, Laffey, Explorer, Navigator, OceanCrosser, FeiYun, Takao
    IslandBusinessShop1_Product1 = 'None'  # None, double_bamboo_shoots, tofu_meat, tofu_combo, hearty_meal, fo_tiao, amaranth_rice_ball
    IslandBusinessShop1_Product2 = 'None'  # None, double_bamboo_shoots, tofu_meat, tofu_combo, hearty_meal, fo_tiao, amaranth_rice_ball
    IslandBusinessShop1_Product3 = 'None'  # None, double_bamboo_shoots, tofu_meat, tofu_combo, hearty_meal, fo_tiao, amaranth_rice_ball
    IslandBusinessShop1_Product4 = 'None'  # None, double_bamboo_shoots, tofu_meat, tofu_combo, hearty_meal, fo_tiao, amaranth_rice_ball
    IslandBusinessShop1_Product5 = 'None'  # None, double_bamboo_shoots, tofu_meat, tofu_combo, hearty_meal, fo_tiao, amaranth_rice_ball
    IslandBusinessShop1_SeasonalFallback = 'hearty_meal'  # None, double_bamboo_shoots, tofu_meat, tofu_combo, hearty_meal, fo_tiao, amaranth_rice_ball
    IslandBusinessShop1_BoostReplaceFilter = '30 > 20 > 10'

    # 配置组 `IslandBusinessShop2`
    IslandBusinessShop2_Char1 = 'None'  # None, WorkerJuu, Cheshire, YingSwei, Saratoga, Akashi, NewJersey, Tashkent, LeMalin, Shimakaze, Amagi_chan, Unicorn, ChaoHo, ChenHai, WilliamDPorter, Helena, Friedrich, Atago, Yixian, August, Eugen, Hood, Javelin, Laffey, Explorer, Navigator, OceanCrosser, FeiYun, Takao
    IslandBusinessShop2_Char2 = 'None'  # None, WorkerJuu, Cheshire, YingSwei, Saratoga, Akashi, NewJersey, Tashkent, LeMalin, Shimakaze, Amagi_chan, Unicorn, ChaoHo, ChenHai, WilliamDPorter, Helena, Friedrich, Atago, Yixian, August, Eugen, Hood, Javelin, Laffey, Explorer, Navigator, OceanCrosser, FeiYun, Takao
    IslandBusinessShop2_Product1 = 'None'  # None, spring_flower_tea, strawberry_lemon, strawberry_honey, floral_fruity, fruit_paradise, lavender_tea, sunny_honey, watermelon_juice
    IslandBusinessShop2_Product2 = 'None'  # None, spring_flower_tea, strawberry_lemon, strawberry_honey, floral_fruity, fruit_paradise, lavender_tea, sunny_honey, watermelon_juice
    IslandBusinessShop2_Product3 = 'None'  # None, spring_flower_tea, strawberry_lemon, strawberry_honey, floral_fruity, fruit_paradise, lavender_tea, sunny_honey, watermelon_juice
    IslandBusinessShop2_Product4 = 'None'  # None, spring_flower_tea, strawberry_lemon, strawberry_honey, floral_fruity, fruit_paradise, lavender_tea, sunny_honey, watermelon_juice
    IslandBusinessShop2_Product5 = 'None'  # None, spring_flower_tea, strawberry_lemon, strawberry_honey, floral_fruity, fruit_paradise, lavender_tea, sunny_honey, watermelon_juice
    IslandBusinessShop2_BoostReplaceFilter = '30 > 20 > strawberry_honey > fruit_paradise > 10'

    # 配置组 `IslandBusinessShop3`
    IslandBusinessShop3_Char1 = 'None'  # None, WorkerJuu, Cheshire, YingSwei, Saratoga, Akashi, NewJersey, Tashkent, LeMalin, Shimakaze, Amagi_chan, Unicorn, ChaoHo, ChenHai, WilliamDPorter, Helena, Friedrich, Atago, Yixian, August, Eugen, Hood, Javelin, Laffey, Explorer, Navigator, OceanCrosser, FeiYun, Takao
    IslandBusinessShop3_Char2 = 'None'  # None, WorkerJuu, Cheshire, YingSwei, Saratoga, Akashi, NewJersey, Tashkent, LeMalin, Shimakaze, Amagi_chan, Unicorn, ChaoHo, ChenHai, WilliamDPorter, Helena, Friedrich, Atago, Yixian, August, Eugen, Hood, Javelin, Laffey, Explorer, Navigator, OceanCrosser, FeiYun, Takao
    IslandBusinessShop3_Product1 = 'None'  # None, orchard_duo, succulently_sweet, berry_orange, strawberry_charlotte, seafood_rice
    IslandBusinessShop3_Product2 = 'None'  # None, orchard_duo, succulently_sweet, berry_orange, strawberry_charlotte, seafood_rice
    IslandBusinessShop3_Product3 = 'None'  # None, orchard_duo, succulently_sweet, berry_orange, strawberry_charlotte, seafood_rice
    IslandBusinessShop3_Product4 = 'None'  # None, orchard_duo, succulently_sweet, berry_orange, strawberry_charlotte, seafood_rice
    IslandBusinessShop3_Product5 = 'None'  # None, orchard_duo, succulently_sweet, berry_orange, strawberry_charlotte, seafood_rice
    IslandBusinessShop3_BoostReplaceFilter = '30 > 20 > succulently_sweet > 10'

    # 配置组 `IslandBusinessShop4`
    IslandBusinessShop4_Char1 = 'None'  # None, WorkerJuu, Cheshire, YingSwei, Saratoga, Akashi, NewJersey, Tashkent, LeMalin, Shimakaze, Amagi_chan, Unicorn, ChaoHo, ChenHai, WilliamDPorter, Helena, Friedrich, Atago, Yixian, August, Eugen, Hood, Javelin, Laffey, Explorer, Navigator, OceanCrosser, FeiYun, Takao
    IslandBusinessShop4_Char2 = 'None'  # None, WorkerJuu, Cheshire, YingSwei, Saratoga, Akashi, NewJersey, Tashkent, LeMalin, Shimakaze, Amagi_chan, Unicorn, ChaoHo, ChenHai, WilliamDPorter, Helena, Friedrich, Atago, Yixian, August, Eugen, Hood, Javelin, Laffey, Explorer, Navigator, OceanCrosser, FeiYun, Takao
    IslandBusinessShop4_Product1 = 'None'  # None, roasted_skewer, stir_fried_chicken, steak_bowl, carnival, double_energy
    IslandBusinessShop4_Product2 = 'None'  # None, roasted_skewer, stir_fried_chicken, steak_bowl, carnival, double_energy
    IslandBusinessShop4_Product3 = 'None'  # None, roasted_skewer, stir_fried_chicken, steak_bowl, carnival, double_energy
    IslandBusinessShop4_Product4 = 'None'  # None, roasted_skewer, stir_fried_chicken, steak_bowl, carnival, double_energy
    IslandBusinessShop4_Product5 = 'None'  # None, roasted_skewer, stir_fried_chicken, steak_bowl, carnival, double_energy
    IslandBusinessShop4_BoostReplaceFilter = '30 > 20 > 10'

    # 配置组 `IslandBusinessShop5`
    IslandBusinessShop5_Char1 = 'None'  # None, WorkerJuu, Cheshire, YingSwei, Saratoga, Akashi, NewJersey, Tashkent, LeMalin, Shimakaze, Amagi_chan, Unicorn, ChaoHo, ChenHai, WilliamDPorter, Helena, Friedrich, Atago, Yixian, August, Eugen, Hood, Javelin, Laffey, Explorer, Navigator, OceanCrosser, FeiYun, Takao
    IslandBusinessShop5_Char2 = 'None'  # None, WorkerJuu, Cheshire, YingSwei, Saratoga, Akashi, NewJersey, Tashkent, LeMalin, Shimakaze, Amagi_chan, Unicorn, ChaoHo, ChenHai, WilliamDPorter, Helena, Friedrich, Atago, Yixian, August, Eugen, Hood, Javelin, Laffey, Explorer, Navigator, OceanCrosser, FeiYun, Takao
    IslandBusinessShop5_Product1 = 'None'  # None, cheese, strawberry_milkshake, morning_light, wake_up_call, fruity_fruitier
    IslandBusinessShop5_Product2 = 'None'  # None, cheese, strawberry_milkshake, morning_light, wake_up_call, fruity_fruitier
    IslandBusinessShop5_Product3 = 'None'  # None, cheese, strawberry_milkshake, morning_light, wake_up_call, fruity_fruitier
    IslandBusinessShop5_Product4 = 'None'  # None, cheese, strawberry_milkshake, morning_light, wake_up_call, fruity_fruitier
    IslandBusinessShop5_Product5 = 'None'  # None, cheese, strawberry_milkshake, morning_light, wake_up_call, fruity_fruitier
    IslandBusinessShop5_BoostReplaceFilter = '30 > 20 > cheese > 10'

    # 配置组 `Daemon`
    Daemon_EnterMap = True

    # 配置组 `OpsiDaemon`
    OpsiDaemon_RepairShip = True
    OpsiDaemon_SelectEnemy = True

    # 配置组 `EventStory`
    EventStory_SkipBattle = False  # True, False

    # 配置组 `BoxDisassemble`
    BoxDisassemble_UsePurpleBox = False
    BoxDisassemble_PurpleBoxLimit = 100
    BoxDisassemble_UseBlueBox = False
    BoxDisassemble_BlueBoxLimit = 1000
    BoxDisassemble_UseWhiteBox = True
    BoxDisassemble_WhiteBoxLimit = 2000

    # 配置组 `Benchmark`
    Benchmark_DeviceType = 'emulator'  # emulator, plone_cloud_with_adb, phone_cloud_without_adb, android_phone, android_phone_vmos
    Benchmark_TestScene = 'screenshot_click'  # screenshot_click, screenshot, click

    # 配置组 `AzurLaneUncensored`
    AzurLaneUncensored_Repository = 'https://gitee.com/LmeSzinc/AzurLaneUncensored'

    # 配置组 `GameManager`
    GameManager_AutoRestart = True

    # 配置组 `EmulatorManagement`
    EmulatorManagement_ScheduledEmulatorRestart = False
    EmulatorManagement_RestartIntervalHours = 4

    # 配置组 `EmulatorManager`
    EmulatorManager_EnableRemoteSSH = False  # True, False
    EmulatorManager_RemoteSSHHost = None
    EmulatorManager_RemoteSSHPort = 22
    EmulatorManager_RemoteSSHUser = None
    EmulatorManager_RemoteSSHPublicKey = None
    EmulatorManager_RemoteStartCommand = None
    EmulatorManager_RemoteStopCommand = None

    # 配置组 `OpsiSimulatorParameters`
    OpsiSimulatorParameters_Samples = 100000
    OpsiSimulatorParameters_Draw = 'do_not'  # do_not, single_sample, multi_sample
    OpsiSimulatorParameters_TotalTime = 0
    OpsiSimulatorParameters_TimeUseRatio = 0.8
    OpsiSimulatorParameters_InitialAp = 0
    OpsiSimulatorParameters_InitialCoin = 0
    OpsiSimulatorParameters_MeowHazardLevel = 'level5'  # level3, level5
    OpsiSimulatorParameters_CrossWeek = True
    OpsiSimulatorParameters_BuyAp = True
    OpsiSimulatorParameters_Cl1Coin = 170
    OpsiSimulatorParameters_Meow3Coin = 750
    OpsiSimulatorParameters_Meow5Coin = 1700
    OpsiSimulatorParameters_AkashiProbability = 0.05
    OpsiSimulatorParameters_Cl1Time = 0
    OpsiSimulatorParameters_Meow3Time = 0
    OpsiSimulatorParameters_Meow5Time = 0
    OpsiSimulatorParameters_Deterministic = False

    # 配置组 `Storage`
    Storage_Storage = {}
