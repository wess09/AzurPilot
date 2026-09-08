"""
Web界面更新管理器。

继承 DeployConfig 和 GitManager，提供 Alas 的自动更新、Git 操作、
依赖同步和版本检查功能。通过后台线程执行更新任务。
"""

import datetime
import subprocess
import threading
import time
from typing import Generator, List, Tuple

import requests
from deploy.atomic import atomic_write
from deploy.config import ExecutionError
from deploy.git import GitManager
from deploy.utils import DEPLOY_CONFIG
from module.base.retry import retry
from module.logger import logger
from module.webui.config import DeployConfig
from module.webui.process_manager import ProcessManager
from module.webui.setting import State, mark_dependency_sync_pending
from module.webui.utils import TaskHandler, get_next_time


class Updater(DeployConfig, GitManager):
    def __init__(self, file=DEPLOY_CONFIG):
        super().__init__(file=file)
        self.state = 0
        self.event: threading.Event = None
        self._update_lock = threading.Lock()
        self.force_update = False
        self._force_update_checking = False

    def alas_kill(self):
        import os
        os._exit(1)

    @property
    def delay(self):
        self.read()
        return int(self.CheckUpdateInterval) * 60

    @property
    def schedule_time(self):
        self.read()
        t = self.AutoRestartTime
        if t is not None:
            return datetime.time.fromisoformat(t)
        else:
            return None

    def execute_output(self, command) -> str:
        command = command.replace(r"\\", "/").replace("\\", "/").replace('"', '"')
        log = subprocess.run(
            command, capture_output=True, text=True, encoding="utf8", shell=True
        ).stdout
        return log

    def get_commit(self, revision="", n=1, short_sha1=False) -> Tuple:
        """
        Return:
            (sha1, author, isotime, message,)
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

    def _check_cloud_update(self) -> bool:
        """检查云端更新开关"""
        return self.cloud_auto_update_enabled()

    def _check_cloud_force_update(self) -> bool:
        """检查云端强制更新开关。"""
        return self.cloud_force_update_enabled()

    def _check_update(self) -> bool:
        self.state = "checking"

        cloud_update = self._check_cloud_update()
        if cloud_update is None:
            self.cloud_update_access_failed(fatal=False)
            return False
        if not cloud_update:
            self.force_update = False
            logger.info("云更新标志为false，跳过更新检查")
            return False

        force_update = self._check_cloud_force_update()
        self.force_update = force_update is True
        if force_update is None:
            logger.warning("强制更新开关不可访问，按关闭处理")

        if State.deploy_config.GitOverCdn:
            status = self.goc_client.get_status()
            if status == "uptodate":
                logger.info(f"无更新")
                return False
            elif status == "behind":
                logger.info(f"有新更新可用")
                return True
            else:
                # failed, should fallback to `git pull`
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
            logger.info(f"有新更新可用")
            logger.info(f"{sha1[:8]} - {message}")
            return True
        else:
            logger.info(f"无更新")
            return False

    def _check_update_(self) -> bool:
        """
        Deprecated
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
            # for develops
            logger.info(
                f"[WebUI-更新] 无法在上游找到本地提交 {local_sha[:8]}，跳过更新"
            )
            return 0

        logger.info(f"更新 {sha[:8]} 可用")
        return 1

    def _check_update_thread(self):
        """在后台线程中执行更新检查"""
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
        """已有更新时，仅检查强制更新开关以保留前端状态。"""
        try:
            cloud_update = self._check_cloud_update()
            if cloud_update is not True:
                self.force_update = False
                return

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
        """按普通或强制模式调度更新检查。"""
        th: TaskHandler
        th = yield
        next_check = 0.0
        while True:
            now = time.monotonic()
            if self.force_update or now >= next_check:
                self.check_update()
                next_check = now + (1 if self.force_update else self.delay)
            th._task.delay = 1
            yield

    @retry(ExecutionError, tries=3, delay=5, logger=None)
    def git_install(self):
        return super().git_install()

    def update(self):
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
        self.state = "start"
        instances = ProcessManager.running_instances()
        names = []
        for alas in instances:
            names.append(alas.config_name + "\n")

        logger.info("[WebUI-更新] 等待所有运行中的 Alas 完成")
        return self._wait_update(instances, names)

    def _wait_update(self, instances: List[ProcessManager], names) -> bool:
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
                    logger.info(f"[WebUI-更新] Alas [{alas.config_name}] 已停止")
                    logger.info(f"[WebUI-更新] 剩余: {[alas.config_name for alas in _instances]}")
            if self.state == "cancel":
                self.state = 1
                self.event.clear()
                ProcessManager.restart_processes(instances, self.event)
                return True
            time.sleep(0.25)
            if time.time() - start_time > 60 * 10:
                logger.warning("[WebUI-更新] 等待 Alas 关闭超时，强制终止")
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
            logger.info("[WebUI-更新] 所有 Alas 已停止，开始更新")

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
                from module.webui.app import clearup

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
        State.restart_event.set()

    def schedule_update(self) -> Generator:
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
        self.state = "cancel"


updater = Updater()

if __name__ == "__main__":
    pass
    # if updater.check_update():
    updater.update()
