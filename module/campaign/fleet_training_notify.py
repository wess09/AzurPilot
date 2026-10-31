"""普通智能换船的培养、已确认换船通知，复用全局通知渠道。"""

from functools import wraps

import yaml

from module.logger import logger
from module.base.async_executor import async_executor
from module.notify import handle_notify, notify_webui
from module.runtime.fleet_training import goals, identity, ships, state


def notification_enabled(config):
    return config.cross_get('FleetInfo.FleetTraining.Notify', False) is True


def notify_event(config, title, content):
    """捕获本次文案和正确的全局渠道，串行发送，失败不改变游戏流程。"""
    try:
        if not notification_enabled(config):
            return False
        instance = config.config_name
        title = f'[AzurPilot <{instance}>] {title}'
        content = f'<{instance}> {config.task.command}\n{content}'
        push_config = config.cross_get('Alas.Error.OnePushConfig', '')
    except Exception as exc:
        logger.warning(f'智能换船通知配置读取失败：{type(exc).__name__}')
        return False

    def send():
        try:
            parsed = {}
            for item in yaml.safe_load_all(push_config or ''):
                if not isinstance(item, dict):
                    raise ValueError('OnePush配置必须为对象')
                parsed.update(item)
            if parsed.get('provider'):
                if handle_notify(push_config, title=title, content=content):
                    logger.info(f'智能换船 OnePush 已发送：{title}')
                else:
                    logger.warning(f'智能换船 OnePush 发送失败：{title}')
            else:
                logger.warning('智能换船未配置有效 OnePush 渠道，请检查全局错误处理中的 OnePush 配置')
        except Exception as exc:
            # 异常可能包含 URL 或令牌，只记录类型，不能把渠道凭据写入日志。
            logger.warning(f'智能换船 OnePush 推送异常：{type(exc).__name__}')
        try:
            if not notify_webui(instance, title=title, content=content):
                logger.warning(f'智能换船启动器通知未送达：{title}')
        except Exception as exc:
            logger.warning(f'智能换船启动器通知异常：{type(exc).__name__}')

    try:
        # 使用既有串行队列，三阶段不会因不同线程而倒序，任务结束也可沿用原有 flush。
        async_executor.submit(send)
        logger.info(f'智能换船通知已入队：{title}')
        return True
    except Exception as exc:
        logger.warning(f'智能换船通知入队失败：{type(exc).__name__}')
        return False


def notify_failure(title, detail):
    """仅补充失败通知，保留原异常对象及上层恢复；同一异常只通知一次。"""
    def decorate(method):
        @wraps(method)
        def wrapped(owner, *args, **kwargs):
            try:
                return method(owner, *args, **kwargs)
            except Exception as exc:
                from module.config.config import TaskEnd
                from module.exception import ScriptEnd
                if isinstance(exc, (TaskEnd, ScriptEnd)):
                    raise
                cause, seen, notified = exc, set(), False
                while cause is not None and id(cause) not in seen:
                    seen.add(id(cause))
                    notified |= getattr(cause, '_fleet_notice_sent', False) is True
                    cause = cause.__cause__ or cause.__context__
                config = getattr(owner, 'config', None)
                if config is None and args:
                    config = getattr(args[0], 'config', None)
                if config is not None and not notified:
                    reason = str(exc) if type(exc).__module__ == 'module.exception' else type(exc).__name__
                    if notify_event(config, title, f'{detail}\n原因：{reason}'):
                        exc._fleet_notice_sent = True
                raise
        return wrapped
    return decorate


def notify_training(config, rules, selected, changes=(), *, status='', event=None):
    if not notification_enabled(config):
        return False
    try:
        return _training_report(config, rules, selected, changes, status=status, event=event)
    except Exception as exc:
        logger.warning(f'智能换船通知内容生成失败：{type(exc).__name__}')
        return False


def _training_report(config, rules, selected, changes, *, status, event):
    result = config.cross_get('FleetInfo.FleetInfo.Result', {})
    saved = state(config)
    event = event or ('replaced' if changes else 'check')
    title = {'check': '培养检查结果', 'graduated': '培养目标达成', 'replaced': '换船完成'}[event]
    lines = ['培养舰船（最近记录）']
    targets = goals(config)
    if targets:
        lines.append('目标：' + '、'.join(f'{"实际等级" if metric == "level" else "好感"}≥{target}'
                                          for metric, target in targets.items()))
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
            if record.get('checked_at'):
                lines.append(f'核对时间：{record["checked_at"]}')
    if changes:
        lines.append('已更换舰船')
        for change in changes:
            source = f'第{change["source"]}舰队' if change['source'] else '常用'
            lines.append(f'第{change["fleet"]}舰队{change["slot"]}位：'
                         f'{change["outgoing"]} → {change["incoming"]}（来源：{source}）')
    if status:
        lines.append(status)
    return notify_event(config, status or title, '\n'.join(lines))
