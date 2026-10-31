"""普通智能换船的培养、已确认换船通知，复用全局通知渠道。"""

from threading import Thread

import yaml

from module.logger import logger
from module.notify import handle_notify, notify_webui
from module.runtime.fleet_training import identity, ships, state


def notify_training(config, rules, selected, changes=(), *, status=''):
    if config.cross_get('FleetInfo.FleetTraining.Notify', False) is not True:
        return
    result = config.cross_get('FleetInfo.FleetInfo.Result', {})
    saved = state(config)
    lines = [f'<{config.config_name}> {config.task.command}', '培养舰船（最近核对）']
    for fleet in dict.fromkeys(selected.values()):
        for slot in rules[str(fleet)]['slots']:
            ship = ships(result, fleet).get(slot)
            if ship is None:
                continue
            name = identity(ship, result)
            record = saved['records'].get(name, {}) if name else saved.get('readings', {}).get(f'{fleet}:{slot}', {})
            if not name and (record.get('fleet') != fleet or record.get('slot') != slot
                             or record.get('name') != ship.get('name')):
                record = {}
            level = record.get('level', ship.get('level'))
            affinity, emotion = record.get('affinity'), ship.get('emotion')
            show = lambda value: str(value) if type(value) is int else '未读取'
            lines.append(f'第{fleet}舰队{slot}位 {ship.get("name") or "未确认舰名"}：'
                         f'等级{show(level)} / 好感{show(affinity)} / 心情{show(emotion)}')
    if changes:
        lines.append('已更换舰船')
        for change in changes:
            source = f'第{change["source"]}舰队' if change['source'] else '常用'
            lines.append(f'第{change["fleet"]}舰队{change["slot"]}位：'
                         f'{change["outgoing"]} → {change["incoming"]}（来源：{source}）')
    if status:
        lines.append(status)
    title = f'[AzurPilot <{config.config_name}>] ' + (status or ('智能换船完成' if changes else '培养进度'))
    content = '\n'.join(lines)
    push_config = config.cross_get('General.Error.OnePushConfig', '')
    instance = config.config_name

    def send():
        # 失败仅影响通知，不改变已完成的换船和任务状态，也不输出渠道凭据。
        try:
            notify_webui(instance, title=title, content=content)
        except Exception as exc:
            logger.warning(f'智能换船本地通知失败：{type(exc).__name__}')
        try:
            parsed = yaml.safe_load(push_config) if push_config else None
            if isinstance(parsed, dict) and parsed.get('provider'):
                handle_notify(push_config, title=title, content=content)
        except Exception as exc:
            logger.warning(f'智能换船推送失败：{type(exc).__name__}')

    Thread(target=send, daemon=True).start()
