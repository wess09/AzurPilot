"""资源刷新只导航和观察，不购买、兑换或使用补给。"""
from module.scheduler.catalog import REFRESHABLE


def stable_read(ui, visible, read):
    """连续两帧读数一致且页面得到正向确认后才接受。"""
    from module.base.timer import Timer
    timeout = Timer(5, count=10).start()
    previous = None
    for _ in ui.loop():
        if visible():
            value = read()
            if value is not None and value == previous:
                return value
            previous = value
        else:
            previous = None
        if timeout.reached():
            return None
    return None


def observe_oil(config, device, publish=True):
    """在战役页可靠观察绝对石油数量，不使用自然恢复上限作清油阈值。"""
    from module.campaign.campaign_status import CampaignStatus
    from module.campaign.assets import OCR_OIL
    from module.log_res import LogRes
    from module.ui.page import page_campaign
    ui = CampaignStatus(config, device)
    ui.ui_ensure(page_campaign)
    def read():
        value = ui._get_num(OCR_OIL, 'OIL_CONTROL', (247, 247, 247), require_valid=True)
        return value if type(value) is int and 0 <= value <= 25000 else None
    value = stable_read(ui, lambda: ui.ui_page_appear(page_campaign), read)
    if value is not None and publish:
        LogRes(config).record('Oil', value, source='oil_control')
        config.save()
    return value


def refresh_resources(config, device, names):
    from module.log_res import LogRes
    from module.ui.page import page_campaign, page_os
    wanted = set(names)
    if not wanted or not wanted <= REFRESHABLE:
        return False
    log = LogRes(config)
    acquired = set()
    if wanted & {'Oil', 'Coin'}:
        from module.campaign.campaign_status import CampaignStatus
        from module.campaign.assets import OCR_COIN, OCR_COIN_LIMIT, OCR_OIL, OCR_OIL_LIMIT
        ui = CampaignStatus(config, device)
        ui.ui_ensure(page_campaign)
        for name, value_button, limit_button, color in (
            ('Oil', OCR_OIL, OCR_OIL_LIMIT, (247, 247, 247)),
            ('Coin', OCR_COIN, OCR_COIN_LIMIT, (239, 239, 239)),
        ):
            if name not in wanted:
                continue
            def read_currency():
                value = ui._get_num(value_button, f'SCHEDULER_{name}', color, require_valid=True)
                limit = ui._get_num(limit_button, f'SCHEDULER_{name}_LIMIT', color, require_valid=True)
                return {'Value': value, 'Limit': limit} if value is not None and limit is not None else None
            row = stable_read(ui, lambda: ui.ui_page_appear(page_campaign), read_currency)
            if row is not None and log.record(name, row, source='scheduler_refresh'):
                acquired.add(name)
    if wanted & {'ActionPoint', 'YellowCoin', 'PurpleCoin'}:
        from module.os.operation_siren import OperationSiren
        ui = OperationSiren(config, device)
        ui.ui_ensure(page_os)
        if 'ActionPoint' in wanted:
            from module.os_handler.action_point import OCR_ACTION_POINT_REMAIN, ACTION_POINT_ITEMS, ACTION_POINT_BOX, OIL_ITEM
            from module.os_handler.assets import ACTION_POINT_USE
            ui.action_point_enter()
            def read_ap():
                current = OCR_ACTION_POINT_REMAIN.ocr(device.image)
                boxes = OIL_ITEM.predict(device.image, name=False, amount=True)
                items = ACTION_POINT_ITEMS.predict(device.image, name=False, amount=True)
                quantities = [item.amount for item in boxes] + [item.amount for item in items]
                if not getattr(OCR_ACTION_POINT_REMAIN, 'last_valid', False) or not 0 <= current <= 600 or len(quantities) != len(ACTION_POINT_BOX):
                    return None
                total = current + sum(n * cost for n, cost in zip(quantities, ACTION_POINT_BOX.values()))
                return {'Value': int(current), 'Total': int(total)}
            row = stable_read(ui, lambda: ui.appear(ACTION_POINT_USE, offset=(20, 20)), read_ap)
            if row is not None and log.record('ActionPoint', row, source='scheduler_refresh'):
                acquired.add('ActionPoint')
            ui.action_point_quit()
        from module.os_handler.os_status import OCR_SHOP_YELLOW_COINS, OCR_SHOP_PURPLE_COINS
        for name, ocr in (('YellowCoin', OCR_SHOP_YELLOW_COINS), ('PurpleCoin', OCR_SHOP_PURPLE_COINS)):
            if name not in wanted:
                continue
            def read_coins():
                value = ocr.ocr(device.image)
                return value if getattr(ocr, 'last_valid', False) else None
            value = stable_read(ui, lambda: ui.ui_page_appear(page_os), read_coins)
            if value is not None and log.record(name, int(value), source='scheduler_refresh'):
                acquired.add(name)
    config.save()
    return acquired == wanted
