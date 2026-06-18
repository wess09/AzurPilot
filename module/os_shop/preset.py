"""大世界商店预设配置。

定义不同购买策略下的物品优先级排序。
行分类：
    1: 记录仪、行动力、紫币
    2: T0 和 T1 物品
    3: 其他物品
    4: META 物品
    5: 低价值物品
"""

OS_SHOP = {
    'max_benefit': """
        LoggerAbyssalT6 > LoggerAbyssalT5 > LoggerObscure > LoggerAbyssalT4 > ActionPoint > PurpleCoins >
        GearDesignPlanT3 > PlateRandomT4 > DevelopmentMaterialT3 > GearDesignPlanT2 > GearPart >
        OrdnanceTestingReportT3 > OrdnanceTestingReportT2 > DevelopmentMaterialT2 > OrdnanceTestingReportT1
    """,
    'max_benefit_meta': """
        LoggerAbyssalT6 > LoggerAbyssalT5 > LoggerObscure > LoggerAbyssalT4 > ActionPoint > PurpleCoins >
        GearDesignPlanT3 > PlateRandomT4 > DevelopmentMaterialT3 > GearDesignPlanT2 > GearPart >
        OrdnanceTestingReportT3 > OrdnanceTestingReportT2 > DevelopmentMaterialT2 > OrdnanceTestingReportT1 >
        METARedBook > CrystallizedHeatResistantSteel > NanoceramicAlloy > NeuroplasticProstheticArm > SupercavitationGenerator
    """,
    'no_meta': """
        LoggerAbyssalT6 > LoggerAbyssalT5 > LoggerObscure > LoggerAbyssalT4 > ActionPoint > PurpleCoins >
        GearDesignPlanT3 > PlateRandomT4 > DevelopmentMaterialT3 > GearDesignPlanT2 > GearPart >
        OrdnanceTestingReportT3 > OrdnanceTestingReportT2 > DevelopmentMaterialT2 > OrdnanceTestingReportT1 >
        LoggerAbyssalT3 > DevelopmentMaterialT1 > TuningT2 > TuningSample > EnergyStorageDevice > RepairPack
    """,
    'all': """
        LoggerAbyssalT6 > LoggerAbyssalT5 > LoggerObscure > LoggerAbyssalT4 > ActionPoint > PurpleCoins >
        GearDesignPlanT3 > PlateRandomT4 > DevelopmentMaterialT3 > GearDesignPlanT2 > GearPart >
        OrdnanceTestingReportT3 > OrdnanceTestingReportT2 > DevelopmentMaterialT2 > OrdnanceTestingReportT1 >
        METARedBook > CrystallizedHeatResistantSteel > NanoceramicAlloy > NeuroplasticProstheticArm > SupercavitationGenerator >
        LoggerAbyssalT3 > DevelopmentMaterialT1 > TuningT2 > TuningSample > EnergyStorageDevice > RepairPack
    """
}
