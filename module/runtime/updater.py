"""
Web界面更新管理器。

继承 DeployConfig 和 RuntimeGitManager，提供 Alas 的自动更新、Git 操作、
依赖同步和版本检查功能。通过后台线程执行更新任务。
"""

import datetime
import os
import subprocess
import threading
import time
from typing import Generator, List, Tuple

import requests
from deploy.atomic import atomic_write
from deploy.config import ExecutionError
from deploy.utils import DEPLOY_CONFIG
from module.base.retry import retry
from module.logger import logger
from module.runtime.config import DeployConfig
from module.runtime.process_manager import ProcessManager
from module.runtime.setting import State, mark_dependency_sync_pending
from module.runtime.startup_memory import mark_update_restart
from module.runtime.task_handler import TaskHandler, get_next_time
from module.runtime.update_network import RuntimeGitManager


class Updater(DeployConfig, RuntimeGitManager):
    """Web 界面更新与版本管理控制器。

    继承 DeployConfig 和 RuntimeGitManager，负责检查云端/本地更新、
    协调进程停止、拉取代码与触发 WebUI 热重载及依赖同步。

    Attributes:
        state: 当前更新器状态（如 0, 1, "checking", "start", "wait", "run update", "reload", "failed", "cancel"）。
        event: 更新过程中的同步线程事件。
        _update_lock: 防止并发执行更新的互斥线程锁。
        force_update: 是否强制执行更新。
        _force_update_checking: 是否正在后台检查强制更新标记。
    """

    def __init__(self, file=DEPLOY_CONFIG):
        """初始化更新管理器实例。

        Args:
            file: 部署配置文件路径，默认为 DEPLOY_CONFIG。
        """
        super().__init__(file=file)
        self.state = 0
        self.event: threading.Event = None
        self._update_lock = threading.Lock()
        self.force_update = False
        self._force_update_checking = False

    def alas_kill(self):
        """强制终止当前进程。"""
        import os
        os._exit(1)

    @property
    def delay(self):
        """读取配置获取更新检查时间间隔（秒）。

        Returns:
            更新检查的秒数间隔。
        """
        self.read()
        return int(self.CheckUpdateInterval) * 60

    @property
    def schedule_time(self):
        """读取配置获取每日自动重启时间。

        Returns:
            若配置了 AutoRestartTime 则返回 datetime.time 对象，否则返回 None。
        """
        self.read()
        t = self.AutoRestartTime
        if t is not None:
            return datetime.time.fromisoformat(t)
        else:
            return None

    def execute_output(self, command) -> str:
        """执行 Shell 命令并返回标准输出。

        Args:
            command: 要执行的命令行字符串。

        Returns:
            命令执行的标准输出字符串。
        """
        command = command.replace(r"\\", "/").replace("\\", "/").replace('"', '"')
        log = subprocess.run(
            command, capture_output=True, text=True, encoding="utf8", shell=True
        ).stdout
        return log

    def get_commit(self, revision="", n=1, short_sha1=False) -> Tuple:
        """获取指定 Git 修订版本的提交信息元组。

        Args:
            revision: Git 修订版本表达式（如 "..origin/master"）。
            n: 获取的提交条数。
            short_sha1: 是否使用短 SHA1 哈希。

        Returns:
            当 n=1 时返回 (sha1, author, isotime, message) 元组；
            当 n>1 时返回包含上述元组的列表；若无提交则返回包含 None 的元组。
        """
        ph = "h" if short_sha1 else "H"

        log = self.execute_output(
            f'"{self.git}" log {revision} --pretty=format:"%{ph}---%an---%ad---%s" --date=iso -{n}'
        )

        if not log:
            return None, None, None, None

        logs = log.split("\n")
        logs = list(map(lambda log: tuple(log.split("---")), logs))

        if n == 1:
            return logs[0]
        else:
            return logs

    def _check_cloud_force_update(self) -> bool:
        """检查云端强制更新开关。

        Returns:
            若允许强制更新返回 True，否则返回 False 或 None。
        """
        return self.cloud_force_update_enabled()

    def _check_update(self) -> bool:
        """执行核心更新检测逻辑，比较远程分支与本地提交。

        Returns:
            若有可用更新返回 True (或 1)，否则返回 False (或 0)。
        """
        self.state = "checking"

        force_update = self._check_cloud_force_update()
        self.force_update = force_update is True
        if force_update is None:
            logger.warning("强制更新开关不可访问，按关闭处理")

        if State.deploy_config.GitOverCdn:
            client = self.goc_client
            try:
                status = client.get_status()
            finally:
                client.close()
            if status == "uptodate":
                logger.info("无更新")
                return False
            elif status == "behind":
                logger.info("有新更新可用")
                return True
            else:
                # 失败时回退到 git pull
                pass

        source = "origin"
        # gitcode 等镜像会对固定 git UA 返回 418，改用随机 UA 重试
        try:
            self._fetch_with_retry(source, self.Branch, max_retry=3, delay=1)
        except ExecutionError:
            logger.warning("Git获取失败")
            return False

        log = self.execute_output(
            f'"{self.git}" log --not --remotes={source}/* -1 --oneline'
        )
        if log:
            logger.info(
                f"[WebUI-更新] 无法在上游找到本地提交 {log.split()[0]}，跳过更新"
            )
            return False

        sha1, _, _, message = self.get_commit(f"..{source}/{self.Branch}")

        if sha1:
            logger.info("有新更新可用")
            logger.info(f"{sha1[:8]} - {message}")
            return True
        else:
            logger.info("无更新")
            return False

    def _check_update_(self) -> bool:
        """通过 Git API 检查更新（已弃用）。

        Returns:
            有更新返回 1，无更新返回 0。
        """
        self.state = "checking"
        r = self.Repository.split("/")
        owner = r[3]
        repo = r[4]
        if "gitee" in r[2]:
            base = "https://gitee.com/api/v5/repos/"
            headers = {}
            token = self.config["ApiToken"]
            if token:
                para = {"access_token": token}
        else:
            base = "https://api.github.com/repos/"
            headers = {"Accept": "application/vnd.github.v3.sha"}
            para = {}
            token = self.config["ApiToken"]
            if token:
                headers["Authorization"] = "token " + token

        try:
            list_commit = requests.get(
                base + f"{owner}/{repo}/branches/{self.Branch}",
                headers=headers,
                params=para,
                timeout=15,
            )
        except Exception as e:
            logger.exception(e)
            logger.warning("检查更新失败")
            return 0

        if list_commit.status_code != 200:
            logger.warning(f"检查更新失败，状态码 {list_commit.status_code}")
            return 0
        try:
            sha = list_commit.json()["commit"]["sha"]
        except Exception as e:
            logger.exception(e)
            logger.warning("解析返回JSON时检查更新失败")
            return 0

        local_sha, _, _, _ = self._get_local_commit()

        if sha == local_sha:
            logger.info("无更新")
            return 0

        try:
            get_commit = requests.get(
                base + f"{owner}/{repo}/commits/" + local_sha,
                headers=headers,
                params=para,
                timeout=15,
            )
        except Exception as e:
            logger.exception(e)
            logger.warning("检查更新失败")
            return 0

        if get_commit.status_code != 200:
            # 开发者本地未推送的提交
            logger.info(
                f"[WebUI-更新] 无法在上游找到本地提交 {local_sha[:8]}，跳过更新"
            )
            return 0

        logger.info(f"更新 {sha[:8]} 可用")
        return 1

    def _check_update_thread(self):
        """在后台线程中执行更新检查。"""
        try:
            result = self._check_update()
            self.state = result
            if result and self.force_update:
                logger.info("强制更新开关已开启，立即执行更新")
                self.run_update()
        except Exception as e:
            logger.exception(e)
            self.state = 0

    def _check_force_update_thread(self):
        """已有更新时，在后台线程仅检查强制更新开关以保留前端状态。"""
        try:
            force_update = self._check_cloud_force_update()
            self.force_update = force_update is True
            if self.force_update:
                logger.info("强制更新开关已开启，立即执行已检测到的更新")
                self.run_update()
        except Exception as e:
            logger.exception(e)
        finally:
            self._force_update_checking = False

    def check_update(self):
        """触发更新检查线程。"""
        # Android 运行时没有 .git，源码、前端和兼容清单由宿主整包切换。
        if os.environ.get('AZURPILOT_ANDROID') == '1':
            self.state = 0
            return
        if self.state in (0, "failed", "finish"):
            self.state = "checking"
            threading.Thread(
                target=self._check_update_thread,
                daemon=True
            ).start()
        elif self.state == 1 and not self._force_update_checking:
            self._force_update_checking = True
            threading.Thread(
                target=self._check_force_update_thread,
                daemon=True,
            ).start()

    def check_update_loop(self) -> Generator:
        """按配置周期调度更新检查，强制更新仅影响发现更新后的执行。

        Yields:
            生成器状态对象供调度器流转。
        """
        th: TaskHandler
        th = yield
        next_check = 0.0
        while True:
            now = time.monotonic()
            if now >= next_check:
                self.check_update()
                next_check = now + self.delay
            th._task.delay = 1
            yield

    @retry(ExecutionError, tries=3, delay=5, logger=None)
    def git_install(self):
        """执行 Git 源码拉取与安装，失败自动重试。"""
        return super().git_install()

    def update(self):
        """执行实际的代码拉取与更新。

        Returns:
            若更新成功返回 True，否则返回 False。
        """
        logger.hr("[WebUI-更新] 执行更新")
        try:
            self.git_install()
        except ExecutionError:
            return False
        except Exception as exc:
            logger.exception_context(
                title='更新执行异常',
                exc=exc,
                impact='更新已中止，已暂停的 AzurPilot 实例将恢复运行。',
                action='检查 Git 更新日志和网络连接后重试。',
                level=50,
            )
            return False
        return True

    def run_update(self) -> bool:
        """获取更新锁并启动安全的完整更新流程。

        Returns:
            更新成功或跳过返回 True，执行失败返回 False。
        """
        if not hasattr(self, "_update_lock"):
            self._update_lock = threading.Lock()
        with self._update_lock:
            if self.state not in ("failed", 0, 1):
                return False
            # 从停止 worker 到通知父进程重启必须是一个事务，手动重启不能插入其中。
            with State.restart_lock:
                if State._restart_requested:
                    logger.info("WebUI 已请求重启，跳过本次自动更新")
                    return True
                if State.restart_event is None:
                    self.state = "failed"
                    logger.critical("已关闭 WebUI 热重载，拒绝执行无法安全恢复的更新")
                    return False
                if State.dependency_sync_event is None:
                    self.state = "failed"
                    logger.critical("依赖同步服务不可用，拒绝执行无法安全恢复的更新")
                    return False
                return self._start_update()

    def _start_update(self) -> bool:
        """准备需要暂停的实例列表并开始等待停止。

        Returns:
            后续更新流程执行结果。
        """
        self.state = "start"
        instances = ProcessManager.running_instances()
        names = []
        for alas in instances:
            names.append(alas.config_name + "\n")

        logger.info("[WebUI-更新] 等待所有运行中的 AzurPilot 完成")
        return self._wait_update(instances, names)

    def _wait_update(self, instances: List[ProcessManager], names) -> bool:
        """等待所有正在运行的实例退出，超时后强制终止。

        Args:
            instances: 运行中的 ProcessManager 列表。
            names: 实例名称字符串列表。

        Returns:
            更新执行结果布尔值。
        """
        if self.state == "cancel":
            self.state = 1
            return True
        self.state = "wait"
        self.event.set()
        _instances = instances.copy()
        start_time = time.time()
        while _instances:
            for alas in _instances:
                if not alas.alive:
                    _instances.remove(alas)
                    logger.info(f"[WebUI-更新] AzurPilot [{alas.config_name}] 已停止")
                    logger.info(f"[WebUI-更新] 剩余: {[alas.config_name for alas in _instances]}")
            if self.state == "cancel":
                self.state = 1
                self.event.clear()
                ProcessManager.restart_processes(instances, self.event)
                return True
            time.sleep(0.25)
            if time.time() - start_time > 60 * 10:
                logger.warning("[WebUI-更新] 等待 AzurPilot 关闭超时，强制终止")
                failed = []
                for alas in _instances:
                    stopped = alas.stop()
                    if stopped is False or alas.alive:
                        failed.append(alas.config_name)
                if failed:
                    self.state = "failed"
                    logger.critical(
                        f"无法停止实例 {failed}，取消更新以避免并发运行旧版本 worker"
                    )
                    self.event.clear()
                    ProcessManager.restart_processes(instances, self.event)
                    return False
                break
        return self._run_update(instances, names)

    def _run_update(self, instances, names) -> bool:
        """执行源码更新、持久化恢复标记并触发 WebUI 热重载。

        Args:
            instances: 原先处于运行状态的实例列表。
            names: 实例名称列表。

        Returns:
            更新成功返回 True，失败返回 False。
        """
        # 该方法也会被定向测试和维护代码直接调用，故在内部重复取得可重入事务锁。
        with State.restart_lock:
            if State._restart_requested:
                logger.info("WebUI 已请求重启，跳过本次自动更新")
                return True
            if State.restart_event is None:
                self.state = "failed"
                logger.critical("已关闭 WebUI 热重载，拒绝执行无法安全恢复的更新")
                return False
            if State.dependency_sync_event is None:
                self.state = "failed"
                logger.critical("依赖同步服务不可用，拒绝执行无法安全恢复的更新")
                return False

            self.state = "run update"
            logger.info("[WebUI-更新] 所有 AzurPilot 已停止，开始更新")

            # 更新前先持久化恢复计划。Git 的 reset/pull 即使报错也可能已修改源码，
            # 因而一旦开始更新，worker 只能由父进程完成依赖同步后恢复。
            try:
                mark_dependency_sync_pending()
                atomic_write("./config/reloadalas", "".join(names))
            except Exception as exc:
                self.state = "failed"
                logger.exception_context(
                    title='无法持久化更新恢复计划',
                    exc=exc,
                    impact='Git 更新尚未开始，已停止的 AzurPilot 实例将恢复运行。',
                    action='检查 config 目录写入权限后重试更新。',
                    level=50,
                )
                if self.event is not None:
                    self.event.clear()
                ProcessManager.restart_processes(instances, self.event)
                return False

            updated = self.update()
            if updated:
                self.state = "reload"
            else:
                # Git 更新失败时不能假定工作树保持旧版本：git reset/pull 可能已部分完成。
                # 保留已写入的同步和恢复计划，交由父进程以一致环境重启。
                self.state = "failed"
                logger.warning("[WebUI-更新] 更新失败，将由父进程完成依赖同步后重启")

            try:
                State._restart_requested = True
                State.dependency_sync_event.set()
            except Exception as exc:
                logger.exception_context(
                    title='无法通知依赖同步服务',
                    exc=exc,
                    impact='父进程将依据持久化同步标记在重启前执行依赖同步。',
                    action='检查进程间事件状态和父监督器日志。',
                    level=50,
                )
            try:
                # 更新代码后导入 WebUI 模块也可能失败，但父进程仍需接管重启。
                from module.api.lifecycle import clearup

                cleaned = clearup()
                if cleaned is False:
                    logger.warning("[WebUI-更新] WebUI 清理未完成，将由父进程终止完整进程树后再重启")
            except Exception as exc:
                logger.exception_context(
                    title='WebUI 清理失败，继续重启',
                    exc=exc,
                    impact='父进程将终止当前 WebUI 子进程并重新创建服务。',
                    action='检查 WebUI 清理日志，确认是否有残留的任务进程或资源。',
                    level=50,
                )
            try:
                # 只有清理结束后父进程才能终止当前 WebUI，避免中途强杀。
                mark_update_restart()
                self._trigger_reload()
            except Exception as exc:
                State._restart_requested = False
                self.state = "failed"
                logger.exception_context(
                    title='无法通知父进程重启 WebUI',
                    exc=exc,
                    impact='已更新代码尚未完成环境同步，已停止的实例不会恢复运行。',
                    action='检查父子进程事件状态后重新启动 WebUI。',
                    level=50,
                )
                if self.event is not None:
                    self.event.clear()
                return False
            return updated

    @staticmethod
    def _trigger_reload():
        """触发父进程的 WebUI 重载事件。"""
        State.restart_event.set()

    def schedule_update(self) -> Generator:
        """按定时计划调度自动更新与检查任务。

        Yields:
            生成器状态对象供调度器流转。
        """
        th: TaskHandler
        th = yield
        if self.schedule_time is None:
            th.remove_current_task()
            yield
        th._task.delay = get_next_time(self.schedule_time)
        yield
        while True:
            self.check_update()
            if self.state != 1:
                th._task.delay = get_next_time(self.schedule_time)
                yield
                continue
            if State.restart_event is None:
                yield
                continue
            if not self.run_update():
                self.state = "failed"
            th._task.delay = get_next_time(self.schedule_time)
            yield

    def cancel(self):
        """取消当前正在等待的更新流程。"""
        self.state = "cancel"


updater = Updater()

if __name__ == "__main__":
    pass
    # if updater.check_update():
    updater.update()
