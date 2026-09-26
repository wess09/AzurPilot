"""显式方法注册表；所有阻塞业务操作在工作线程执行。"""
import os
from dataclasses import dataclass
from typing import Callable

from module.api import protocol as p
from module.runtime.process_manager import ProcessManager


@dataclass(frozen=True)
class Method:
    params: type[p.Params]
    handler: Callable
    mutates: bool = False


class Router:
    def __init__(self, configs, runtime):
        self.configs, self.runtime = configs, runtime
        self._accounts = None
        self.access_password = ''
        self.methods = {
            'system.ping': Method(p.Params, lambda _: {'pong': True}),
            'schema.get': Method(p.SchemaParams, lambda x: configs.schema(x.language)),
            'instances.list': Method(p.Params, lambda _: runtime.instances()),
            'instances.create': Method(p.CreateParams, lambda x: configs.create(x.name, x.source, x.import_file), True),
            'instances.importable': Method(p.Params, lambda _: configs.importable()),
            'instances.importConfig': Method(p.ImportParams, lambda x: configs.save_import(x.name, x.content), True),
            'instances.delete': Method(p.RevisionParams, self.delete, True),
            'config.get': Method(p.InstanceParams, lambda x: configs.get(x.instance)),
            'config.patch': Method(p.PatchParams, lambda x: configs.patch(x.instance, x.revision, x.changes), True),
            'shop_strategy.validate': Method(p.ShopStrategyValidateParams, self.validate_shop_strategy),
            'overview.get': Method(p.InstanceParams, lambda x: runtime.overview(x.instance)),
            'scheduler.start': Method(p.InstanceParams, lambda x: runtime.start(x.instance), True),
            'scheduler.stop': Method(p.InstanceParams, lambda x: runtime.stop(x.instance), True),
            'tasks.run': Method(p.TaskParams, lambda x: runtime.start(x.instance, x.task), True),
            'logs.get': Method(p.LogsParams, lambda x: runtime.logs(x.instance, x.after)),
            'preview.capture': Method(p.InstanceParams, lambda x: runtime.capture(x.instance)),
            'statistics.refreshLoot': Method(p.InstanceParams, self.refresh_loot, True),
            'statistics.report': Method(p.StatisticsReportParams, self.statistics_report),
            'meowfficer.scoreReport': Method(p.MeowfficerScoreReportParams, self.meowfficer_score_report),
            'meowfficer.clearReport': Method(p.MeowfficerClearReportParams,
                                             self.meowfficer_clear_report, True),
            'statistics.resources': Method(p.StatisticsParams, lambda x: runtime.statistics(x.instance, x.days, x.resource)),
            'settings.get': Method(p.Params, self.settings),
            'settings.patch': Method(p.DeployParams, self.save_settings, True),
            'startup.get': Method(p.InstanceParams, self.get_startup),
            'startup.set': Method(p.StartupParams, self.set_startup, True),
            'accounts.status': Method(p.InstanceParams, lambda x: self.accounts.status(x)),
            'accounts.manage': Method(p.AccountParams, lambda x: self.accounts.manage(x, self.access_password), True),
            'updater.status': Method(p.Params, lambda _: self.updates.status()),
            'updater.commits': Method(p.CommitsParams, lambda x: self.updates.commits(x.offset, x.limit)),
            'updater.fetch': Method(p.Params, lambda _: self.updates.start('fetch'), True),
            'updater.apply': Method(p.Params, lambda _: self.updates.start('apply'), True),
            'updater.cancel': Method(p.Params, lambda _: self.updates.cancel(), True),
            'announcement.get': Method(p.AnnouncementParams, lambda x: self.announcements.get(force=x.force)),
        }

    @property
    def accounts(self):
        if self._accounts is None:
            from module.api.account_service import AccountService
            self._accounts = AccountService(self.configs)
        return self._accounts

    @property
    def announcements(self):
        from module.api.announcement_service import announcement_service
        return announcement_service

    @property
    def updates(self):
        from module.api.update_service import update_service
        return update_service

    def refresh_loot(self, params):
        from module.api.statistics_service import refresh_loot
        return refresh_loot(self.configs, params.instance)

    def validate_shop_strategy(self, params):
        """校验高级商店策略，禁止客户端指定任意执行上下文。"""
        self.configs.path(params.instance)
        if 'ShopAdvanced' not in self.configs.args.get(params.task, {}):
            raise p.ApiError('INVALID_PARAMS', '不支持的商店任务')
        from module.shop_strategy import validate_strategy

        # 显式检查返回诊断而不是抛出参数错误，编辑器才能标出行列位置。
        return validate_strategy(params.script)

    def statistics_report(self, params):
        from module.api.statistics_service import report
        return report(self.configs, params.instance, params.category, params.month,
                      params.days, params.period, research_series=params.series,
                      research_scope=params.scope, loot_task=params.task)

    def meowfficer_score_report(self, params):
        from module.api.meowfficer_service import report
        return report(self.configs, params.instance, params.limit)

    def meowfficer_clear_report(self, params):
        from module.api.meowfficer_service import clear
        return clear(self.configs, params.instance)

    def dispatch(self, method, params):
        entry = self.methods.get(method)
        if entry is None:
            raise p.ApiError('METHOD_NOT_FOUND', '未知 API 方法')
        validated = entry.params.model_validate(params)
        if entry.mutates and os.environ.get('DEMO') == '1':
            raise p.ApiError('READ_ONLY', '演示模式下禁止修改配置或运行任务')
        return entry.handler(validated)

    def delete(self, params):
        with ProcessManager._get_lifecycle_lock(params.instance):
            manager = self.runtime.manager(params.instance)
            if manager.alive:
                raise p.ApiError('INSTANCE_RUNNING', '请先停止实例再删除')
            result = self.configs.delete(params.instance, params.revision)
            from module.runtime.account_vault import OPERATIONS
            with OPERATIONS:
                account_vault = self.accounts.vault
                account_vault.destroy(params.instance)
                path = account_vault.path(params.instance)
                for suffix in ('', '-journal', '-wal', '-shm'):
                    path.with_name(path.name + suffix).unlink(missing_ok=True)
                account_vault.marker(params.instance).unlink(missing_ok=True)
                account_vault.revoked.discard(params.instance)
                if path.parent.is_dir() and not any(path.parent.iterdir()):
                    path.parent.rmdir()
            manager.run_id = None
            ProcessManager.remove_manager(params.instance)
            self.runtime.logs_cache.pop(params.instance, None)
            from module.runtime.preview import hub
            hub.discard(params.instance)
            return result

    def settings(self, _):
        from module.runtime.deploy_settings import deploy_settings_schema
        from module.runtime.remote_access import remote_access_status
        result = deploy_settings_schema(self.configs.translate)
        # 密码只写不读，前端留空表示保持原密码。
        for group in result['groups']:
            for field in group['fields']:
                if field['key'] == 'Password':
                    field['value'] = ''
                    field['type'] = 'password'
        # 远程访问地址不属于设置，但设置页要展示，一并带回。
        result['remote'] = remote_access_status()
        return result

    def save_settings(self, params):
        from module.runtime.deploy_settings import save_deploy_settings
        values = dict(params.values)
        if values.get('Password') == '':
            values.pop('Password')
        with self.configs.lock:
            return save_deploy_settings({'values': values})

    def get_startup(self, params):
        from module.runtime.deploy_settings import get_startup_run
        from module.runtime.startup_memory import get_startup_remember
        self.configs.path(params.instance)
        return {**get_startup_run(params.instance),
                'remember': get_startup_remember(params.instance)}

    def set_startup(self, params):
        from module.runtime.deploy_settings import get_startup_run, set_startup_run
        from module.runtime.startup_memory import get_startup_remember, set_startup_remember
        self.configs.path(params.instance)
        with self.configs.lock:
            if params.enabled is not None:
                set_startup_run(params.instance, params.enabled)
            if params.remember is not None:
                set_startup_remember(params.instance, params.remember)
            return {**get_startup_run(params.instance),
                    'remember': get_startup_remember(params.instance)}
