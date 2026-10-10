"""显式方法注册表；所有阻塞业务操作在工作线程执行。"""
import os
import secrets
import threading
from dataclasses import dataclass
from typing import Callable

from module.persistence.database import configured_database
from module.api import background_service as background
from module.api import protocol as p
from module.api import search_service as search
from module.runtime.process_manager import ProcessManager


@dataclass(frozen=True)
class Method:
    """路由方法注册项。

    Attributes:
        params: 参数校验模型类型。
        handler: 请求处理函数或方法。
        mutates: 是否会修改系统状态或运行任务。
    """
    params: type[p.Params]
    handler: Callable
    mutates: bool = False


class Router:
    """API 路由分发器。

    管理所有 WebSocket RPC 方法的注册、参数校验与调用分发。
    """

    def __init__(self, configs, runtime):
        """初始化路由分发器。

        Args:
            configs: 配置服务实例。
            runtime: 运行时管理服务实例。
        """
        self.configs, self.runtime = configs, runtime
        self._accounts = None
        self._scheduler_programs = None
        self._opsi_simulator = None
        self._opsi_simulator_lock = threading.Lock()
        self._stock_exchange = None
        self._stock_exchange_lock = threading.Lock()
        self.access_password = ''
        self.background_token = secrets.token_urlsafe(32)
        self.methods = {
            'system.ping': Method(p.Params, lambda _: {'pong': True}),
            'schema.get': Method(p.SchemaParams, lambda x: configs.schema(x.language)),
            'search.content': Method(p.SearchContentParams, lambda x: search.search_content(x.query)),
            'instances.list': Method(p.Params, lambda _: runtime.instances()),
            'instances.create': Method(p.CreateParams, lambda x: configs.create(x.name, x.source, x.import_file), True),
            'instances.importable': Method(p.Params, lambda _: configs.importable()),
            'instances.importConfig': Method(p.ImportParams, lambda x: configs.save_import(x.name, x.content), True),
            'instances.delete': Method(p.RevisionParams, self.delete, True),
            'config.get': Method(p.InstanceParams, lambda x: configs.get(x.instance)),
            'config.export': Method(p.InstanceParams, lambda x: configs.export(x.instance)),
            'config.patch': Method(p.PatchParams, lambda x: configs.patch(x.instance, x.revision, x.changes), True),
            'overview.get': Method(p.InstanceParams, lambda x: runtime.overview(x.instance)),
            'mind.catalog': Method(p.InstanceParams, lambda x: self.mind.catalog(x.instance)),
            'mind.report': Method(p.InstanceParams, lambda x: self.mind.report(x.instance)),
            'mind.calculate': Method(p.MindCalculateParams, lambda x: self.mind.calculate(x.instance, [ship.model_dump() for ship in x.ships])),
            'mind.save': Method(p.MindSaveParams, lambda x: self.mind.save(x.instance, x.revision, [ship.model_dump() for ship in x.ships]), True),
            'mind.import': Method(p.MindFileParams, lambda x: self.mind.import_file(x.instance, x.filename, x.content)),
            'mind.recognize': Method(p.MindFileParams, lambda x: self.mind.recognize(x.instance, x.filename, x.content)),
            'mind.export': Method(p.MindExportParams, lambda x: self.mind.export(x.instance, x.format)),
            'stock.status': Method(p.InstanceParams, lambda x: self.stock_exchange.status(x.instance)),
            'stock.rebuild': Method(p.StockRebuildParams, lambda x: self.stock_exchange.rebuild(x.instance, x.confirm, x.scope), True),
            'stock.request': Method(p.StockRequestParams, lambda x: self.stock_exchange.request(x.instance, x.path, x.method, x.body, x.etag), True),
            'scheduler.start': Method(p.InstanceParams, lambda x: runtime.start(x.instance), True),
            'scheduler.stop': Method(p.InstanceParams, lambda x: runtime.stop(x.instance), True),
            'scheduler.program.catalog': Method(p.InstanceParams, lambda x: self.programs.catalog(x.instance)),
            'scheduler.program.get': Method(p.InstanceParams, lambda x: self.programs.get(x.instance)),
            'scheduler.program.save': Method(p.ProgramSaveParams, lambda x: self.programs.save(x.instance, x.revision, x.document), True),
            'scheduler.program.validate': Method(p.ProgramValidateParams, lambda x: self.programs.validation(x.instance, x.document, x.mode)),
            'scheduler.program.simulate': Method(p.ProgramSimulateParams, lambda x: self.programs.simulate(x.instance, x.document, x.context, x.outcomes, x.steps, x.mode)),
            'scheduler.program.apply': Method(p.ProgramApplyParams, lambda x: self.programs.apply(x.instance, x.revision, x.mode), True),
            'scheduler.program.state': Method(p.InstanceParams, lambda x: self.programs.state(x.instance)),
            'tasks.run': Method(p.TaskParams, lambda x: runtime.start(x.instance, x.task), True),
            'logs.get': Method(p.LogsParams, lambda x: runtime.logs(x.instance, x.after)),
            'opsi.simulator.status': Method(p.LogsParams, lambda x: self.opsi_simulator.status(x.instance, x.after)),
            'opsi.simulator.start': Method(p.InstanceParams, lambda x: self.opsi_simulator.start(x.instance), True),
            'opsi.simulator.stop': Method(p.InstanceParams, lambda x: self.opsi_simulator.stop(x.instance), True),
            'opsi.simulator.figure': Method(p.InstanceParams, lambda x: self.opsi_simulator.figure(x.instance)),
            'preview.capture': Method(p.InstanceParams, lambda x: runtime.capture(x.instance)),
            'statistics.refreshLoot': Method(p.InstanceParams, self.refresh_loot, True),
            'statistics.report': Method(p.StatisticsReportParams, self.statistics_report),
            'statistics.resourceFlows': Method(p.ResourceFlowsParams, self.resource_flows),
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
            'background.access': Method(p.Params, lambda _: {'token': self.background_token}),
            'background.resolve': Method(p.BackgroundUrlParams, lambda x: background.resolve(x.url)),
            'background.gallery.list': Method(p.Params, lambda _: background.gallery_list()),
            'background.gallery.add': Method(p.BackgroundGalleryAddParams,
                                                 lambda x: background.gallery_add(x.url, x.name), True),
            'background.gallery.remove': Method(p.BackgroundGalleryRemoveParams,
                                                    lambda x: {'removed': background.gallery_remove(x.id)}, True),
            'background.gallery.open': Method(p.Params, lambda _: background.gallery_open(), True),
        }

    @property
    def mind(self):
        from module.api.mind_calculator_service import MindCalculatorService
        return MindCalculatorService(self.configs)

    @property
    def opsi_simulator(self):
        """获取独立于游戏调度器的大世界模拟服务。"""
        with self._opsi_simulator_lock:
            if self._opsi_simulator is None:
                from module.api.opsi_simulator_service import OpsiSimulatorService
                self._opsi_simulator = OpsiSimulatorService(self.configs)
            return self._opsi_simulator

    def close(self):
        """回收离线模拟线程，不触发游戏任务。"""
        if self._opsi_simulator is not None:
            self._opsi_simulator.manager.close()
        if self._stock_exchange is not None:
            self._stock_exchange.close()

    @property
    def stock_exchange(self):
        """按需加载行动力同步服务，普通页面不会发起远端请求。"""
        with self._stock_exchange_lock:
            if self._stock_exchange is None:
                from module.api.stock_exchange_service import StockExchangeService
                self._stock_exchange = StockExchangeService(self.configs)
                self._stock_exchange.start()
            return self._stock_exchange

    @property
    def accounts(self):
        """获取账号管理服务单例。

        Returns:
            AccountService: 账号管理服务实例。
        """
        if self._accounts is None:
            from module.api.account_service import AccountService
            self._accounts = AccountService(self.configs)
        return self._accounts

    @property
    def programs(self):
        """获取调度程序服务单例。

        Returns:
            SchedulerService: 调度程序草稿、校验与模拟服务实例。
        """
        if self._scheduler_programs is None:
            from module.api.scheduler_service import SchedulerService
            self._scheduler_programs = SchedulerService(self.configs, self.runtime)
        return self._scheduler_programs

    @property
    def announcements(self):
        """获取公告服务单例。

        Returns:
            AnnouncementService: 公告服务实例。
        """
        from module.api.announcement_service import announcement_service
        return announcement_service

    @property
    def updates(self):
        """获取更新管理服务单例。

        Returns:
            UpdateService: 更新服务实例。
        """
        from module.api.update_service import update_service
        return update_service

    def refresh_loot(self, params: p.InstanceParams):
        """刷新指定实例的掉落统计数据。

        Args:
            params: 包含实例名称的参数对象。

        Returns:
            Any: 刷新操作的执行结果。
        """
        from module.api.statistics_service import refresh_loot
        return refresh_loot(self.configs, params.instance)


    def statistics_report(self, params: p.StatisticsReportParams):
        """生成并获取指定维度的统计报表。

        Args:
            params: 统计报表请求参数。

        Returns:
            dict: 统计报表数据。
        """
        from module.api.statistics_service import compact_axis, report
        result = report(self.configs, params.instance, params.category, params.month,
                        params.days, params.period, research_series=params.series,
                        research_scope=params.scope, loot_task=params.task,
                        include_series=params.include_series)
        return {**result, **compact_axis(result.get('series') or [])}

    def resource_flows(self, params: p.ResourceFlowsParams):
        """查询库存与资源流向；沿用现有实例访问边界。"""
        from module.api.resource_service import resource_flows
        return resource_flows(self.configs, params)

    def meowfficer_score_report(self, params: p.MeowfficerScoreReportParams):
        """获取指挥喵评分报告。

        Args:
            params: 指挥喵报告请求参数。

        Returns:
            dict: 指挥喵评分报告数据。
        """
        from module.api.meowfficer_service import report
        return report(self.configs, params.instance, params.limit)

    def meowfficer_clear_report(self, params: p.MeowfficerClearReportParams):
        """清空指挥喵评分报告。

        Args:
            params: 指挥喵清空报告请求参数。

        Returns:
            dict: 清空操作结果。
        """
        from module.api.meowfficer_service import clear
        return clear(self.configs, params.instance)

    @configured_database
    def dispatch(self, method: str, params: dict):
        """分发并执行指定的 API 方法。

        Args:
            method: 方法名称。
            params: 原始请求参数字典。

        Returns:
            Any: 处理函数执行结果。

        Raises:
            p.ApiError: 方法未注册 (METHOD_NOT_FOUND)、参数不合法 (INVALID_PARAMS)
                或演示模式下尝试修改 (READ_ONLY)。
        """
        entry = self.methods.get(method)
        if entry is None:
            raise p.ApiError('METHOD_NOT_FOUND', '未知 API 方法')
        validated = entry.params.model_validate(params)
        if entry.mutates and os.environ.get('DEMO') == '1':
            raise p.ApiError('READ_ONLY', '演示模式下禁止修改配置或运行任务')
        return entry.handler(validated)

    def delete(self, params: p.RevisionParams):
        """删除指定实例及其关联的数据和进程。

        Args:
            params: 包含实例名称和版本号的参数对象。

        Returns:
            dict: 删除操作结果。

        Raises:
            p.ApiError: 实例仍在运行无法删除时抛出 INSTANCE_RUNNING。
        """
        with ProcessManager._get_lifecycle_lock(params.instance):
            manager = self.runtime.manager(params.instance)
            if manager.alive:
                raise p.ApiError('INSTANCE_RUNNING', '请先停止实例再删除')
            if self._opsi_simulator is not None and self._opsi_simulator.manager.status(params.instance)['running']:
                raise p.ApiError('SIMULATOR_RUNNING', '请先中断大世界模拟器再删除实例')
            result = self.configs.delete(params.instance, params.revision)
            if self._stock_exchange is not None:
                # 配置删除只撤销内存会话；交易文件检查留给茗交所自身。
                with self._stock_exchange.lock:
                    self._stock_exchange.sessions.pop(params.instance, None)
                    self._stock_exchange.monitors.discard(params.instance)
            if self._opsi_simulator is not None:
                self._opsi_simulator.manager.discard(params.instance)
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

    def settings(self, _: p.Params):
        """获取部署设置表单结构及远程访问状态。

        Args:
            _: 空通用参数。

        Returns:
            dict: 部署设置表单元数据与字段值。
        """
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

    def save_settings(self, params: p.DeployParams):
        """保存部署设置。

        Args:
            params: 部署配置参数。

        Returns:
            dict: 保存结果及最新配置。
        """
        from module.runtime.deploy_settings import save_deploy_settings
        values = dict(params.values)
        if values.get('Password') == '':
            values.pop('Password')
        with self.configs.lock:
            return save_deploy_settings({'values': values})

    def get_startup(self, params: p.InstanceParams):
        """获取实例的开机自启与状态保持配置。

        Args:
            params: 包含实例名称的参数对象。

        Returns:
            dict: 包含开机自启和记忆状态的配置信息。
        """
        from module.runtime.deploy_settings import get_startup_run
        from module.runtime.startup_memory import get_startup_remember
        self.configs.path(params.instance)
        return {**get_startup_run(params.instance),
                'remember': get_startup_remember(params.instance)}

    def set_startup(self, params: p.StartupParams):
        """设置实例的开机自启与状态保持配置。

        Args:
            params: 启动设置参数对象。

        Returns:
            dict: 更新后的开机自启和记忆状态。
        """
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
