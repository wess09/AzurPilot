"""大世界运行期统计入口。

这里集中处理侵蚀1与短猫任务的运行事件，把任务代码里的战斗、地图、
塞壬研究装置等事件统一落到统计库，避免各个任务到处直接写数据库。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from module.logger import logger


# 任务代码只上报领域事件，具体落库细节集中在本模块里维护。
CL1_TASK = "OpsiHazard1Leveling"
MEOW_TASK = "OpsiMeowfficerFarming"
MEOW_HAZARD_LEVELS = {2, 3, 4, 5, 6}


def instance_name_from_config(config: Any, default: str = "default") -> str:
    return getattr(config, "config_name", None) or default


def battle_source_from_config(config: Any) -> str | None:
    """返回当前任务对应的统计来源。"""
    command = getattr(getattr(config, "task", None), "command", None)
    if command == CL1_TASK:
        return "cl1"
    if command == MEOW_TASK:
        return "meow"
    return None


def start_battle_timer(config: Any) -> str | None:
    """开始记录单场战斗耗时，并返回结束计时需要的来源。"""
    source = battle_source_from_config(config)
    if source is None:
        return None

    try:
        from module.statistics.ship_exp_stats import get_ship_exp_stats

        get_ship_exp_stats(instance_name=instance_name_from_config(config)).on_battle_start()
        return source
    except Exception:
        logger.debug(f"Failed to start {source} battle timer", exc_info=True)
        return None


def finish_battle_timer(config: Any, source: str | None) -> float | None:
    """结束已经开始的单场战斗计时。"""
    if source not in {"cl1", "meow"}:
        return None

    try:
        from module.statistics.ship_exp_stats import get_ship_exp_stats

        return get_ship_exp_stats(
            instance_name=instance_name_from_config(config)
        ).on_battle_end(source=source)
    except Exception:
        logger.debug(f"Failed to finish {source} battle timer", exc_info=True)
        return None


def record_ap_snapshot(config: Any, ap_current: int, source: str, distance: int = None) -> None:
    """按来源记录行动力快照。"""
    try:
        from module.statistics.cl1_database import db as cl1_db

        cl1_db.async_add_ap_snapshot(
            instance_name_from_config(config),
            ap_current,
            source=source,
            distance=distance,
        )
    except Exception:
        logger.exception("Failed to save AP snapshot")


def record_cl1_auto_search_battle(
    config: Any,
    cl1_battle_count: int,
    round_started_at: float | int | None,
) -> float | int | None:
    """记录一次侵蚀1自律战斗，并维护两战一轮的计时。"""
    instance_name = instance_name_from_config(config)
    try:
        from module.statistics.cl1_database import db as cl1_db

        cl1_db.async_increment_battle_count(instance_name)
    except Exception:
        logger.debug("Failed to persist monthly CL1 battle increment", exc_info=True)

    # 侵蚀1两场战斗消耗一次出击，奇数场代表新一轮开始。
    # 下一次奇数场到来时，上一轮的完整耗时就能闭合。
    if cl1_battle_count % 2 != 1:
        return round_started_at

    now = time.time()
    if round_started_at:
        cost = round(now - float(round_started_at), 2)
        logger.attr("CL1 time cost", f"{cost}s/round")
        try:
            from module.statistics.ship_exp_stats import get_ship_exp_stats

            get_ship_exp_stats(instance_name=instance_name).record_round_time(cost)
        except Exception:
            logger.exception("Failed to record cl1 round time")
    return now


def meow_hazard_level_from_runtime(main: Any) -> int | None:
    """读取短猫当前侵蚀等级，地图对象缺失时回退到配置值。"""
    hazard_level = None
    try:
        hazard_level = getattr(getattr(main, "zone", None), "hazard_level", None)
    except Exception:
        logger.debug("Failed to get hazard level from current zone")

    if hazard_level not in MEOW_HAZARD_LEVELS:
        try:
            hazard_level = main.config.cross_get(
                keys="OpsiMeowfficerFarming.OpsiMeowfficerFarming.HazardLevel"
            )
        except Exception:
            hazard_level = None

    try:
        hazard_level = int(hazard_level)
    except (TypeError, ValueError):
        return None

    return hazard_level if hazard_level in MEOW_HAZARD_LEVELS else None


def meow_battles_per_round(hazard_level: int | None) -> int:
    """返回短猫一个有效轮次包含的战斗场数。"""
    if hazard_level in {4, 5, 6}:
        return 3
    return 2


def record_meow_auto_search_battle(
    main: Any,
    battle_started_at: float | int | None,
) -> float:
    """记录一次短猫战斗，并返回下一场战斗的计时起点。"""
    hazard_level = meow_hazard_level_from_runtime(main)
    instance_name = instance_name_from_config(main.config)

    try:
        from module.statistics.cl1_database import db as cl1_db

        cl1_db.async_increment_meow_battle_count(instance_name, hazard_level)
    except Exception:
        logger.debug("Failed to persist monthly meow battle increment", exc_info=True)

    now = time.time()
    if battle_started_at:
        battle_duration = round(now - float(battle_started_at), 2)
        if 5 < battle_duration < 600:
            logger.attr("Meow battle duration", f"{battle_duration:.1f}s")
            try:
                from module.statistics.cl1_database import db as cl1_db

                cl1_db.async_add_meow_battle_time(instance_name, battle_duration, hazard_level)
            except Exception:
                logger.debug("Failed to record meow battle time", exc_info=True)
        else:
            logger.debug(
                f"Meow battle duration {battle_duration:.1f}s out of range, not recorded"
            )
    return now


def start_meow_search_timer(main: Any) -> tuple[float, int | None]:
    """记录短猫开始搜索当前海域时的时间与行动力。"""
    try:
        main.get_current_ap()
        start_ap = main._action_point_total
        logger.debug(f"Meow search started, AP: {start_ap}")
    except Exception:
        start_ap = None
        logger.debug("Failed to get start action point")

    logger.debug("Meow search started, timer reset")
    return time.time(), start_ap


def finish_meow_search_timer(
    main: Any,
    search_started_at: float,
    battle_count: int,
) -> float | None:
    """按完成的海域搜索记录短猫单轮耗时。"""
    try:
        main.get_current_ap()
    except Exception:
        logger.debug("Failed to get end action point")

    duration = time.time() - search_started_at
    hazard_level = meow_hazard_level_from_runtime(main)
    battles_per_round = meow_battles_per_round(hazard_level)
    logger.debug(f"Hazard level: {hazard_level}, battles per round: {battles_per_round}")

    # 一次海域搜索可能包含多场战斗，需要折算回单轮耗时。
    # WebUI 与调度逻辑都使用这个统一后的轮次单位。
    if battle_count > 0:
        rounds = battle_count / battles_per_round
        duration = duration / rounds
        logger.debug(
            f"Meow search total duration: {time.time() - search_started_at:.1f}s, "
            f"battles: {battle_count}, rounds: {rounds}, per round: {duration:.1f}s"
        )

    if duration < 1 or duration > 1800:
        logger.debug(f"Meow search duration {duration:.1f}s out of range, not recorded")
        return None

    logger.attr("Meow search duration", f"{duration:.1f}s")
    try:
        from module.statistics.cl1_database import db as cl1_db

        cl1_db.async_add_meow_round_time(
            instance_name_from_config(main.config),
            duration,
            hazard_level,
        )
    except Exception:
        logger.debug("Failed to record meow search duration", exc_info=True)

    return duration


def record_cl1_akashi_encounter(config: Any) -> int | None:
    """记录侵蚀1明石事件，并返回当月累计次数。"""
    try:
        from module.statistics.cl1_database import db as cl1_db

        instance_name = instance_name_from_config(config)
        cl1_db.async_increment_akashi_encounter(instance_name)
        month_key = datetime.now().strftime("%Y-%m")
        future = cl1_db.async_get_stats(instance_name, month_key)
        data = future.result(timeout=5.0)
        encounters = int(data.get("akashi_encounters", 0))
        logger.attr("cl1_akashi_monthly", encounters)
        return encounters
    except Exception:
        logger.exception("Failed to persist CL1 akashi monthly count")
        return None


def record_siren_research_device(main: Any) -> None:
    """记录一次塞壬研究装置（吊机）出现，按侵蚀1或短猫侵蚀等级拆分。"""
    source = battle_source_from_config(main.config)
    if source not in {"cl1", "meow"}:
        return

    hazard_level = meow_hazard_level_from_runtime(main) if source == "meow" else 1
    try:
        from module.statistics.cl1_database import db as cl1_db

        cl1_db.async_add_siren_research_device(
            instance_name_from_config(main.config),
            source=source,
            hazard_level=hazard_level,
        )
        label = "cl1" if source == "cl1" else f"meow-{hazard_level}"
        logger.attr("siren_research_device", label)
    except Exception:
        logger.debug("Failed to record siren research device", exc_info=True)
