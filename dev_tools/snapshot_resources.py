"""
强制获取当前所有资源数值并记录快照。

用法 1 - 从配置缓存读取（离线可用，无需模拟器运行）：
    uv run python dev_tools/snapshot_resources.py

用法 2 - 从游戏截图 OCR 读取（需要模拟器运行中）：
    uv run python dev_tools/snapshot_resources.py --ocr
    uv run python dev_tools/snapshot_resources.py --ocr --instance=alas

用法 3 - 查看当前已记录的快照数量：
    uv run python dev_tools/snapshot_resources.py --count

用法 4 - 查看最近的快照数据：
    uv run python dev_tools/snapshot_resources.py --recent
"""
import argparse
import os
import sys

# 切换到项目根目录
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_project_root)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def snapshot_from_config(instance: str = "alas"):
    """从配置 Dashboard 读取缓存值并记录快照"""
    from module.config.config import AzurLaneConfig
    from module.log_res.log_res import LogRes
    from module.config.utils import alas_instance

    all_instances = alas_instance()
    if not all_instances:
        print("❌ 未找到任何实例配置")
        return False

    if instance not in all_instances:
        print(f"⚠️  实例 '{instance}' 不存在，可用实例: {all_instances}")
        print(f"   使用第一个实例: {all_instances[0]}")
        instance = all_instances[0]

    config = AzurLaneConfig(instance)
    log_res = LogRes(config)
    groups = log_res.groups

    print(f"📋 实例: {instance}")
    print(f"📊 Dashboard 资源缓存值:")
    print("-" * 50)

    values = {}
    for group_name in groups:
        group_data = log_res.group(group_name)
        if isinstance(group_data, dict):
            value = group_data.get("Value", "N/A")
            record = group_data.get("Record", "")
            limit = group_data.get("Limit")
            total = group_data.get("Total")
            val_str = f"{value:,}" if isinstance(value, int) else value
            if limit:
                val_str += f" / {limit:,}"
            if total:
                val_str += f" (总额 {total:,})"
            print(f"  {group_name:15s} = {val_str:20s}  上次记录: {record}")
            if isinstance(value, int):
                values[group_name] = value

    # 调用记录快照
    from module.statistics.resource_stats import record_resource_snapshot
    success = record_resource_snapshot(instance, values)
    if success:
        print(f"\n✅ 快照已记录 ({len(values)} 项资源)")
    else:
        print(f"\n❌ 快照记录失败")
    return success


def snapshot_from_ocr(instance: str = "alas"):
    """从游戏截图 OCR 读取实际资源值并记录快照"""
    try:
        from module.config.config import AzurLaneConfig
        from module.config.utils import alas_instance

        all_instances = alas_instance()
        if not all_instances:
            print("❌ 未找到任何实例配置")
            return False
        if instance not in all_instances:
            print(f"⚠️  实例 '{instance}' 不存在，使用: {all_instances[0]}")
            instance = all_instances[0]

        config = AzurLaneConfig(instance)
    except Exception as e:
        print(f"❌ 加载配置失败: {e}")
        return False

    print(f"📋 实例: {instance}")
    print("📷 正在连接模拟器截图...")

    try:
        from module.device.device import Device
        device = Device(config)
        device.screenshot()
        print(f"  截图成功: {device.image.shape}")
    except Exception as e:
        print(f"❌ 截图失败（模拟器未运行或 ADB 未连接）: {e}")
        return False

    image = device.image
    resources = {}

    # --- OCR 读取各资源 ---

    # 石油 & 物资 & 钻石 & 魔方 (主界面/出征界面)
    from module.campaign.campaign_status import OCR_OIL, OCR_COIN
    from module.shop.assets import SHOP_GEMS
    from module.ocr.ocr import Digit
    from module.base.utils import color_similar, get_color
    from module.base.button import Button

    # 石油 - 使用 campaign 现有 OCR
    try:
        from module.campaign.assets import OCR_OIL as OIL_BTN
        oil_ocr = Digit(OIL_BTN, name="OCR_OIL", letter=(247, 247, 247), threshold=128)
        oil_val = oil_ocr.ocr(image)
        if isinstance(oil_val, int) and oil_val > 0:
            resources["Oil"] = oil_val
            print(f"  🛢️  石油 = {oil_val:,}")
    except Exception as e:
        print(f"  ⚠️  石油 OCR 失败: {e}")

    # 物资
    try:
        from module.campaign.assets import OCR_COIN as COIN_BTN
        coin_ocr = Digit(COIN_BTN, name="OCR_COIN", letter=(239, 239, 239), threshold=128)
        coin_val = coin_ocr.ocr(image)
        if isinstance(coin_val, int) and coin_val > 0:
            resources["Coin"] = coin_val
            print(f"  💰 物资 = {coin_val:,}")
        else:
            # 尝试从物资上限格式读取
            coin_full = Digit(COIN_BTN, name="OCR_COIN_FULL", letter=(165, 165, 165), threshold=128)
            coin_val2 = coin_full.ocr(image)
            if isinstance(coin_val2, int) and coin_val2 > 0:
                resources["Coin"] = coin_val2
                print(f"  💰 物资 = {coin_val2:,}")
    except Exception as e:
        print(f"  ⚠️  物资 OCR 失败: {e}")

    # 钻石 (主界面右上角)
    try:
        gem_ocr = Digit(SHOP_GEMS, letter=(255, 243, 82), name="OCR_GEM_MAIN")
        gem_val = gem_ocr.ocr(image)
        if isinstance(gem_val, int) and gem_val > 0:
            resources["Gem"] = gem_val
            print(f"  💎 钻石 = {gem_val:,}")
    except Exception as e:
        print(f"  ⚠️  钻石 OCR 失败: {e}")

    # 魔方
    try:
        from module.gacha.assets import OCR_GACHA_CUBE
        cube_ocr = Digit(OCR_GACHA_CUBE, letter=(145, 215, 255), name="OCR_CUBE_MAIN")
        cube_val = cube_ocr.ocr(image)
        if isinstance(cube_val, int) and cube_val > 0:
            resources["Cube"] = cube_val
            print(f"  🔷 魔方 = {cube_val:,}")
    except Exception as e:
        print(f"  ⚠️  魔方 OCR 失败: {e}")

    # 活动 Pt (如果有活动)
    try:
        from module.campaign.assets import OCR_PT
        from module.campaign.campaign_status import PtOcr
        pt_ocr = PtOcr(OCR_PT, name="OCR_PT")
        pt_str = pt_ocr.ocr(image)
        import re
        pt_match = re.search(r'X?(\d+)', pt_str)
        if pt_match:
            pt_val = int(pt_match.group(1))
            if pt_val > 0:
                resources["Pt"] = pt_val
                print(f"  🎯 活动Pt = {pt_val:,}")
    except Exception as e:
        print(f"  ⚠️  活动Pt OCR 失败: {e}")

    # 记录快照
    if not resources:
        print("\n❌ 未能从截图中读取到任何资源数值")
        print("   提示: 确保模拟器运行中，且游戏在主界面或出征界面")
        return False

    from module.statistics.resource_stats import record_resource_snapshot
    success = record_resource_snapshot(instance, resources)
    print(f"\n✅ 快照已记录 ({len(resources)} 项资源)")
    return success


def show_count(instance: str = "alas"):
    """查看当前已记录的快照数量"""
    from module.statistics.resource_stats import get_resource_timeline
    from module.config.utils import alas_instance

    all_instances = alas_instance()
    if not all_instances:
        print("❌ 未找到任何实例配置")
        return

    if instance not in all_instances:
        instance = all_instances[0]

    data = get_resource_timeline(instance=instance, limit=10000)
    print(f"📊 实例 '{instance}' 共 {len(data)} 条快照记录")
    if data:
        print(f"   最早: {data[0]['ts']}")
        print(f"   最近: {data[-1]['ts']}")


def show_recent(instance: str = "alas", n: int = 3):
    """显示最近 n 条快照"""
    from module.statistics.resource_stats import get_resource_timeline
    from module.config.utils import alas_instance

    all_instances = alas_instance()
    if not all_instances:
        print("❌ 未找到任何实例配置")
        return

    if instance not in all_instances:
        instance = all_instances[0]

    data = get_resource_timeline(instance=instance, limit=10000)
    if not data:
        print(f"📭 实例 '{instance}' 暂无快照记录")
        return

    print(f"📊 实例 '{instance}' 最近 {min(n, len(data))} 条快照:")
    print("-" * 100)

    resource_names = {
        "oil": "石油", "coin": "物资", "gem": "钻石", "pt": "活动Pt",
        "cube": "魔方", "core": "核心数据", "medal": "勋章",
        "merit": "功勋", "guild_coin": "舰队币",
        "action_point": "行动力", "yellow_coin": "黄币", "purple_coin": "紫币",
    }
    cols = [c for c in resource_names if any(d.get(c) is not None for d in data[-n:])]

    header = f"{'时间':20s}" + "".join(f"{name:>10s}" for name in [resource_names[c] for c in cols])
    print(header)
    print("-" * len(header))
    for d in data[-n:]:
        ts = d["ts"][:19]
        vals = "".join(f"{str(d.get(c, '-')):>10s}" for c in cols)
        print(f"{ts:20s}{vals}")


def main():
    parser = argparse.ArgumentParser(description="强制获取资源数据并记录快照")
    parser.add_argument("--instance", default="alas", help="实例名称 (默认: alas)")
    parser.add_argument("--ocr", action="store_true", help="从游戏截图 OCR 读取（需模拟器运行中）")
    parser.add_argument("--count", action="store_true", help="查看已记录的快照数量")
    parser.add_argument("--recent", action="store_true", help="查看最近的快照数据")
    args = parser.parse_args()

    if args.count:
        show_count(args.instance)
    elif args.recent:
        show_recent(args.instance)
    elif args.ocr:
        snapshot_from_ocr(args.instance)
    else:
        snapshot_from_config(args.instance)


if __name__ == "__main__":
    main()
