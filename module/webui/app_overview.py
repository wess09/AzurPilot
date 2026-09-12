"""WebUI实例概览和守护模式"""

from module.webui.app_dependencies import (
    BinarySwitchButton,
    RichLog,
    deep_iter,
    get_device_id,
    json,
    put_button,
    put_html,
    put_none,
    put_scope,
    put_text,
    run_js,
    t,
    updater,
    use_scope,
)

from module.webui.app_helpers import (
    DEMO_DEVICE_ID_TEXT,
    is_demo_mode,
)


from module.webui.app_types import WebUIMixinBase


class OverviewMixin(WebUIMixinBase):
    """WebUI实例概览和守护模式"""

    @use_scope("content", clear=True)
    def alas_overview(self) -> None:
        self.init_menu(name="Overview")
        self.set_title(t(f"Gui.MenuAlas.Overview"))
        self._overview_snapshot = None

        put_scope("overview", [put_scope("schedulers"), put_scope("stat_panels")])

        with use_scope("schedulers"):
            put_scope(
                "scheduler-bar",
                [
                    put_text(t("Gui.Overview.Scheduler")).style(
                        "font-size: 1.25rem; margin: auto .5rem auto;"
                    ),
                    put_scope("scheduler_btn"),
                ],
            )
            put_scope(
                "stat-bar",
                [
                    put_text(t("Gui.Overview.Log")).style(
                        "font-size: 1.25rem; margin: auto .5rem auto;"
                    ),
                    put_button(
                        label=t("Gui.Button.Open"),
                        onclick=self.alas_set_log,
                        color="on",
                    ),
                ],
            )
            put_scope(
                "running",
                [
                    put_text(t("Gui.Overview.Running")),
                    put_html('<hr class="hr-group">'),
                    put_scope("running_tasks"),
                ],
            )
            put_scope(
                "pending",
                [
                    put_text(t("Gui.Overview.Pending")),
                    put_html('<hr class="hr-group">'),
                    put_scope("pending_tasks"),
                ],
            )
            put_scope(
                "waiting",
                [
                    put_text(t("Gui.Overview.Waiting")),
                    put_html('<hr class="hr-group">'),
                    put_scope("waiting_tasks"),
                ],
            )

        switch_scheduler = BinarySwitchButton(
            label_on=t("Gui.Button.Stop"),
            label_off=t("Gui.Button.Start"),
            onclick_on=lambda: self.alas.stop_by_user(
                self.alas_config.Optimization_WhenSchedulerStopped
            ),
            onclick_off=self._alas_start,
            get_state=lambda: self.alas.alive,
            color_on="off",
            color_off="on",
            scope="scheduler_btn",
        )

        # April Fools: runaway start button
        if getattr(self, "af_flag", False):
            run_js("""
(function(){
    var surrendered = false;
    var bar = document.getElementById('pywebio-scope-scheduler-bar');
    if (!bar) return;
    bar.style.position = 'relative';
    bar.style.overflow = 'hidden';

    var flag = document.createElement('button');
    flag.textContent = '🏳️';
    flag.title = 'I give up...';
    flag.style.cssText = 'border:none;background:transparent;font-size:1.1rem;cursor:pointer;padding:0 4px;margin:auto 2px;opacity:0.45;transition:opacity .2s;flex-shrink:0;';
    flag.onmouseenter = function(){ flag.style.opacity='1'; };
    flag.onmouseleave = function(){ flag.style.opacity='0.45'; };
    flag.onclick = function(){
        surrendered = true;
        flag.style.display = 'none';
        var b = bar.querySelector('.btn-on');
        if(b){ b.style.transition='transform .35s cubic-bezier(.34,1.56,.64,1)'; b.style.transform=''; }
    };
    bar.appendChild(flag);

    bar.addEventListener('mousemove', function(e){
        if (surrendered) return;
        var btn = bar.querySelector('.btn-on');
        if (!btn) return;
        var r = btn.getBoundingClientRect();
        var bx = r.left + r.width/2, by = r.top + r.height/2;
        var dx = bx - e.clientX, dy = by - e.clientY;
        var dist = Math.sqrt(dx*dx + dy*dy);
        if (dist < 100 && dist > 1) {
            var pr = bar.getBoundingClientRect();
            var push = 100 - dist;
            var nx = dx/dist * push, ny = dy/dist * push * 0.3;
            var cur = btn.style.transform.match(/translate\\(([^,]+)px,\\s*([^)]+)px\\)/);
            var ox = cur ? parseFloat(cur[1]) : 0, oy = cur ? parseFloat(cur[2]) : 0;
            var tx = ox + nx, ty = oy + ny;
            var maxX = (pr.width - r.width) / 2 - 4;
            var maxY = (pr.height - r.height) / 2;
            tx = Math.max(-maxX, Math.min(maxX, tx));
            ty = Math.max(-maxY, Math.min(maxY, ty));
            btn.style.transition = 'transform .13s ease-out';
            btn.style.transform = 'translate('+tx+'px,'+ty+'px)';
        }
    });
})();
""")

        # 右侧统计图表面板
        with use_scope("stat_panels"):
            self._mount_stat_panels()

        self.task_handler.add(switch_scheduler.g(), 1, True)
        self.task_handler.add(self.alas_update_overview_task, 10, True)

    def _mount_log_panel(self) -> None:
        """创建并渲染日志面板（log-bar、仪表盘、日志内容）及周期刷新任务。"""
        if (
            self._overview_log is None
            or self._overview_log_config_name != self.alas_name
        ):
            self._overview_log = RichLog("log")
            self._overview_log_config_name = self.alas_name
        else:
            self._overview_log.scope = "log"
        log = self._overview_log
        log.first_display = True
        log.last_display_time = {}
        self._log = log

        with use_scope("logs"):
            if "Maa" in self.ALAS_ARGS:
                (
                    put_scope(
                        "log-bar",
                        [
                            put_text(t("Gui.Overview.Log")).style(
                                "font-size: 1.25rem; margin: auto .5rem auto;"
                            ),
                            put_scope(
                                "log-bar-btns",
                                [
                                    put_scope("log_scroll_btn"),
                                ],
                            ),
                        ],
                    ),
                )
            else:
                (
                    put_scope(
                        "log-bar",
                        [
                            put_text(t("Gui.Overview.Log")).style(
                                "font-size: 1.25rem; margin: auto .5rem auto;"
                            ),
                            put_scope(
                                "log-bar-btns",
                                [
                                    put_scope("log_scroll_btn"),
                                    put_button(
                                        label="截图预览",
                                        onclick=lambda: run_js(
                                            f"window.alasToggleLivePreview({json.dumps(self.alas_name)});"
                                        ),
                                        color="off",
                                    ),
                                ],
                            ),
                        ],
                    ),
                )
            # version
            local_commit = updater.get_commit(short_sha1=True)
            version = local_commit[0] if local_commit and local_commit[0] else "Unknown"
            device_id = DEMO_DEVICE_ID_TEXT if is_demo_mode() else get_device_id()
            put_scope("log-container", [put_scope("log", [put_html("")])]).style(
                f"--device-id: '{device_id}'; --version: 'Ver.{version}';"
            )

        log.console.width = log.get_width()

        switch_log_scroll = BinarySwitchButton(
            label_on=t("Gui.Button.ScrollON"),
            label_off=t("Gui.Button.ScrollOFF"),
            onclick_on=lambda: log.set_scroll(False),
            onclick_off=lambda: log.set_scroll(True),
            get_state=lambda: log.keep_bottom,
            color_on="on",
            color_off="off",
            scope="log_scroll_btn",
        )
        self.task_handler.add(switch_log_scroll.g(), 1, True)
        if hasattr(self, "alas") and self.alas is not None:
            self.task_handler.add(log.put_log(self.alas), 0.25, True)

    @use_scope("content", clear=True)
    def alas_set_log(self) -> None:
        """显示日志页（原统计图表页位置）。"""
        self.init_menu(name="Log")
        self.set_title(t("Gui.Overview.Log"))
        self._mount_log_panel()

    @use_scope("content", clear=True)
    def alas_daemon_overview(self, task: str) -> None:
        self.init_menu(name=task)
        self.set_title(t(f"Task.{task}.name"))

        log = RichLog("log")

        if self.is_mobile:
            put_scope(
                "daemon-overview",
                [
                    put_scope("scheduler-bar"),
                    put_scope("stat-bar"),
                    put_scope("groups"),
                    put_scope("log-bar"),
                    put_scope("log", [put_html("")]),
                ],
            )
        else:
            put_scope(
                "daemon-overview",
                [
                    put_none(),
                    put_scope(
                        "_daemon",
                        [
                            put_scope(
                                "_daemon_upper",
                                [put_scope("scheduler-bar"), put_scope("log-bar")],
                            ),
                            put_scope("groups"),
                            put_scope("log", [put_html("")]),
                        ],
                    ),
                    put_none(),
                ],
            )

        log.console.width = log.get_width()

        with use_scope("scheduler-bar"):
            put_text(t("Gui.Overview.Scheduler")).style(
                "font-size: 1.25rem; margin: auto .5rem auto;"
            )
            put_scope("scheduler_btn")

        with use_scope("stat-bar"):
            put_text(t("Gui.Overview.Log")).style(
                "font-size: 1.25rem; margin: auto .5rem auto;"
            )
            put_button(
                label=t("Gui.Button.Open"),
                onclick=self.alas_set_log,
                color="on",
            )

        switch_scheduler = BinarySwitchButton(
            label_on=t("Gui.Button.Stop"),
            label_off=t("Gui.Button.Start"),
            onclick_on=lambda: self.alas.stop_by_user(
                self.alas_config.Optimization_WhenSchedulerStopped
            ),
            onclick_off=lambda: self.alas.start(task),
            get_state=lambda: self.alas.alive,
            color_on="off",
            color_off="on",
            scope="scheduler_btn",
        )

        with use_scope("log-bar"):
            put_text(t("Gui.Overview.Log")).style(
                "font-size: 1.25rem; margin: auto .5rem auto;"
            )
            put_scope(
                "log-bar-btns",
                [
                    put_scope("log_scroll_btn"),
                    put_button(
                        label="截图预览",
                        onclick=lambda: run_js(
                            f"window.alasToggleLivePreview({json.dumps(self.alas_name)});"
                        ),
                        color="off",
                    ),
                ],
            )

        switch_log_scroll = BinarySwitchButton(
            label_on=t("Gui.Button.ScrollON"),
            label_off=t("Gui.Button.ScrollOFF"),
            onclick_on=lambda: log.set_scroll(False),
            onclick_off=lambda: log.set_scroll(True),
            get_state=lambda: log.keep_bottom,
            color_on="on",
            color_off="off",
            scope="log_scroll_btn",
        )

        config = self.alas_config.read_file(self.alas_name)
        for group, arg_dict in deep_iter(self.ALAS_ARGS[task], depth=1):
            if group[0] == "Storage":
                continue
            self.set_group(group, arg_dict, config, task)

        run_js(
            """
            $("#pywebio-scope-log").css(
                "grid-row-start",
                -2 - $("#pywebio-scope-_daemon").children().filter(
                    function(){
                        return $(this).css("display") === "none";
                    }
                ).length
            );
            $("#pywebio-scope-log").css(
                "grid-row-end",
                -1
            );
        """
        )

        self.task_handler.add(switch_scheduler.g(), 1, True)
        self.task_handler.add(switch_log_scroll.g(), 1, True)
        if hasattr(self, "alas") and self.alas is not None:
            self.task_handler.add(log.put_log(self.alas), 0.25, True)
