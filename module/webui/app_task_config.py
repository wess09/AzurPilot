"""WebUI任务菜单和配置表单"""

from html import escape
from typing import cast

import module.webui.lang as lang
from module.webui.app_dependencies import (
    Any,
    clear,
    Dict,
    List,
    Optional,
    Output,
    State,
    T_Output_Kwargs,
    current_time,
    datetime,
    deep_get,
    deep_iter,
    deep_set,
    dict_to_kv,
    filepath_config,
    get_device_id,
    logger,
    os,
    parse_pin_value,
    pin,
    pin_on_change,
    popup,
    put_button,
    put_buttons,
    put_collapse,
    put_html,
    put_input,
    put_none,
    put_output,
    put_row,
    put_scope,
    put_text,
    queue,
    re_fullmatch,
    run_js,
    t,
    to_pin_value,
    to_server,
    toast,
    updater,
    use_scope,
)

from module.webui.app_helpers import (
    DEMO_DEVICE_ID_TEXT,
    build_copyable_device_id,
    is_demo_mode,
)
from module.webui.config_search import (
    ConfigSearchEntry,
    build_config_search_result_click_script,
    build_config_search_focus_script,
    config_search_config_signature,
    config_search_field_scope,
    search_config_entries,
    should_render_config_argument,
)


from module.webui.app_types import WebUIMixinBase


class TaskConfigMixin(WebUIMixinBase):
    """WebUI任务菜单和配置表单"""

    CONFIG_SEARCH_PIN = "config_search_keyword"
    CONFIG_SEARCH_SELECTION_PIN = "config_search_selection"
    CONFIG_SEARCH_RESULT_LIMIT = 20

    @use_scope("menu", clear=True)
    def alas_set_menu(self) -> None:
        """渲染任务菜单及配置搜索入口。"""
        put_scope("task_config_search")
        put_scope("task_config_search_results")
        put_scope("task_config_menu_items")
        self._render_config_search_control()
        self._render_task_menu_items()
        self.alas_overview()

    @use_scope("task_config_menu_items", clear=True)
    def _render_task_menu_items(self) -> None:
        """渲染未搜索时的完整任务菜单。"""
        put_buttons(
            [
                {
                    "label": t("Gui.MenuAlas.Overview"),
                    "value": "Overview",
                    "color": "menu",
                }
            ],
            onclick=[self.alas_overview],
        ).style(f"--menu-Overview--")

        for menu, task_data in self.ALAS_MENU.items():
            if task_data.get("page") == "tool":
                _onclick = self.alas_daemon_overview
            else:
                _onclick = self.alas_set_group

            if task_data.get("menu") == "collapse":
                task_btn_list = []
                for task in task_data.get("tasks", []):
                    onclick = _onclick
                    if menu == "FleetManagement":
                        onclick = {
                            "FleetScan": self.fleet_scan_page,
                            "FleetInfo": self.fleet_info_page,
                        }.get(task, _onclick)
                    task_btn_list.append(
                        put_buttons(
                            [
                                {
                                    "label": t(f"Task.{task}.name"),
                                    "value": task,
                                    "color": "menu",
                                }
                            ],
                            onclick=onclick,
                        ).style(f"--menu-{task}--")
                    )
                put_collapse(title=t(f"Menu.{menu}.name"), content=task_btn_list)
            else:
                title = t(f"Menu.{menu}.name")
                put_html(
                    '<div class="hr-task-group-box">'
                    '<span class="hr-task-group-line"></span>'
                    f'<span class="hr-task-group-text">{title}</span>'
                    '<span class="hr-task-group-line"></span>'
                    "</div>"
                )
                for task in task_data.get("tasks", []):
                    onclick = _onclick
                    if menu == "FleetManagement":
                        onclick = {
                            "FleetScan": self.fleet_scan_page,
                            "FleetInfo": self.fleet_info_page,
                        }.get(task, _onclick)
                    put_buttons(
                        [
                            {
                                "label": t(f"Task.{task}.name"),
                                "value": task,
                                "color": "menu",
                            }
                        ],
                        onclick=onclick,
                    ).style(f"--menu-{task}--").style(f"padding-left: 0.75rem")

    @use_scope("task_config_search", clear=True)
    def _render_config_search_control(self) -> None:
        """渲染搜索输入框，并注册不参与配置保存的实时回调。"""
        put_input(
            name=self.CONFIG_SEARCH_PIN,
            value="",
            placeholder=t("Gui.TaskConfig.SearchPlaceholder"),
        ).style("--task-config-search-input--")
        put_input(name=self.CONFIG_SEARCH_SELECTION_PIN, value="")
        if not getattr(self, "_config_search_callbacks_bound", False):
            pin_on_change(
                name=self.CONFIG_SEARCH_PIN,
                onchange=self._on_config_search_change,
                clear=True,
                serial_mode=True,
            )
            pin_on_change(
                name=self.CONFIG_SEARCH_SELECTION_PIN,
                onchange=self._on_config_search_result,
                clear=True,
                serial_mode=True,
            )
            self._config_search_callbacks_bound = True
        run_js(build_config_search_result_click_script(self.CONFIG_SEARCH_SELECTION_PIN))
        self._get_config_search_entries()

    def _on_config_search_change(self, value: Any) -> None:
        """根据输入值重绘搜索结果，不触碰实例配置。"""
        self._render_config_search_results(str(value or ""))

    def _on_config_search_result(self, key: Any) -> None:
        """仅允许打开当前仍可见的搜索结果。"""
        for entry in self._get_config_search_entries():
            if entry.key == str(key):
                self._open_config_search_result(entry)
                return

    @use_scope("task_config_search_results", clear=True)
    def _render_config_search_results(self, query: str) -> None:
        """显示匹配项，或在清空查询后恢复任务菜单。"""
        if not query.strip():
            self._render_task_menu_items()
            return

        clear("task_config_menu_items")
        results, total = search_config_entries(
            self._get_config_search_entries(),
            query,
            limit=self.CONFIG_SEARCH_RESULT_LIMIT,
        )
        if not results:
            put_text(t("Gui.TaskConfig.SearchNoResult")).style(
                "--task-config-search-empty--"
            )
            return

        put_text(t("Gui.TaskConfig.SearchResultCount", count=total)).style(
            "--task-config-search-count--"
        )
        for entry in results:
            self._put_config_search_result(entry)

    def _put_config_search_result(self, entry: ConfigSearchEntry) -> None:
        """渲染一个可点击的配置搜索结果。"""
        help_text = " ".join(entry.help_text.split())
        if len(help_text) > 88:
            help_text = help_text[:87].rstrip() + "..."
        help_html = (
            f'<span class="config-search-result-help">{escape(help_text)}</span>'
            if help_text
            else ""
        )
        put_html(
            '<button class="config-search-result" type="button" '
            f'data-config-search-key="{escape(entry.key)}">'
            f'<span class="config-search-result-name">{escape(entry.argument_name)}</span>'
            f'<span class="config-search-result-path">{escape(entry.task_name)} &gt; '
            f"{escape(entry.group_name)}</span>"
            f'<span class="config-search-result-key">{escape(entry.key)}</span>'
            f"{help_html}"
            "</button>"
        )

    def _open_config_search_result(self, entry: ConfigSearchEntry) -> None:
        """打开结果所在任务，并定位到对应的参数容器。"""
        self.alas_set_group(entry.task)
        run_js(
            build_config_search_focus_script(
                config_search_field_scope(entry.task, entry.group, entry.argument)
            )
        )

    def _get_config_search_entries(self) -> List[ConfigSearchEntry]:
        """按当前实例和服务器返回可见参数的内存索引。"""
        config = self.alas_config.read_file(self.alas_name)
        package_name = deep_get(config, "Alas.Emulator.PackageName", "cn")
        signature = (
            self.alas_name,
            self.alas_mod,
            lang.LANG,
            package_name,
            id(self.ALAS_ARGS),
            config_search_config_signature(config),
        )
        if getattr(self, "_config_search_signature", None) != signature:
            self._config_search_entries = self._build_config_search_entries(config)
            self._config_search_signature = signature
        return self._config_search_entries

    def _invalidate_config_search_cache(self) -> None:
        """在配置写入后丢弃可能已经过期的可见参数索引。"""
        self._config_search_entries = []
        self._config_search_signature = None

    def _build_config_search_entries(
        self, config: Dict[str, Any]
    ) -> List[ConfigSearchEntry]:
        """从当前菜单中实际可显示的参数构建搜索索引。"""
        entries: List[ConfigSearchEntry] = []
        seen_tasks = set()
        for task_data in self.ALAS_MENU.values():
            if task_data.get("page") != "setting":
                continue
            for task in task_data.get("tasks", []):
                if task in seen_tasks or task not in self.ALAS_ARGS:
                    continue
                seen_tasks.add(task)
                task_name = self._translated_text(f"Task.{task}.name", task)
                for group, group_args in deep_iter(self.ALAS_ARGS[task], depth=1):
                    group_name = group[0]
                    display_group_name = self._translated_text(
                        f"{group_name}._info.name", group_name
                    )
                    for arg_name, _, _, output_kwargs in self._iter_group_arguments(
                        task, group_name, group_args, config
                    ):
                        entries.append(
                            ConfigSearchEntry(
                                task=task,
                                group=group_name,
                                argument=arg_name,
                                task_name=task_name,
                                group_name=display_group_name,
                                argument_name=str(output_kwargs["title"]),
                                help_text=str(output_kwargs.get("help") or ""),
                            )
                        )
        return entries

    @staticmethod
    def _translated_text(key: str, fallback: str) -> str:
        """读取翻译，并在翻译缺失时保留技术名称作为可搜索回退。"""
        translated = t(key)
        return fallback if translated == key else translated

    def _iter_group_arguments(
        self,
        task: str,
        group_name: str,
        group_args: Dict[str, Any],
        config: Dict[str, Any],
    ):
        """解析当前服务器下会渲染的参数，并供表单与搜索索引共享。"""
        package_name = deep_get(config, "Alas.Emulator.PackageName", "cn")
        server = to_server(package_name if isinstance(package_name, str) else "cn")
        for arg, arg_definition in deep_iter(group_args, depth=1):
            if not isinstance(arg_definition, dict):
                continue

            arg_name = arg[0]
            output_kwargs: T_Output_Kwargs = arg_definition.copy()
            display: Optional[str] = output_kwargs.pop("display", None)
            widget_type = output_kwargs.pop("type")
            output_kwargs["widget_type"] = widget_type
            if display == "disabled":
                output_kwargs["disabled"] = True

            value = deep_get(
                config, [task, group_name, arg_name], output_kwargs["value"]
            )
            # datetime 控件只能接收文本，避免 Pin 在重绘时丢失原始时间值。
            value = str(value) if isinstance(value, datetime) else value
            output_kwargs["value"] = value

            options = output_kwargs.pop("option", [])
            available_events = deep_get(
                self.ALAS_ARGS, keys=f"{task}.{group_name}.{arg_name}.option_{server}"
            )
            if available_events is not None:
                options = [opt for opt in options if opt in available_events]
            server_options = output_kwargs.get(f"option_{server}")
            if (
                widget_type == "select"
                and isinstance(server_options, list)
                and server_options
            ):
                options = server_options
            output_kwargs["options"] = options

            if not should_render_config_argument(
                task,
                group_name,
                arg_name,
                display,
                widget_type,
                options,
                value,
            ):
                continue

            if widget_type == "select" and len(options) == 1:
                only_option = options[0]
                if only_option in output_kwargs.get("option_bold", []):
                    output_kwargs["widget_type"] = "state"
            output_kwargs["name"] = f"{task}_{group_name}_{arg_name}"
            output_kwargs["title"] = self._translated_text(
                f"{group_name}.{arg_name}.name", arg_name
            )
            output_kwargs["options_label"] = [
                t(f"{group_name}.{arg_name}.{opt}") for opt in options
            ]
            arg_help = t(f"{group_name}.{arg_name}.help")
            output_kwargs["help"] = arg_help or None
            yield arg_name, display, widget_type, output_kwargs

    @use_scope("content", clear=True)
    def alas_set_group(self, task: str) -> None:
        """
        Set arg groups from dict
        """
        config = self.alas_config.read_file(self.alas_name)
        self.init_menu(name=task)
        self.set_title(t(f"Task.{task}.name"))

        group_outputs: List[Output] = []
        navigator_outputs: List[Output] = []
        watcher_paths: List[List[str]] = []
        render_event_calculator = False

        task_help: str = t(f"Task.{task}.help")
        if task_help:
            group_outputs.append(
                put_scope(
                    "group__info",
                    content=[put_text(task_help).style("font-size: 1rem")],
                )
            )

        if task == "Alas":
            group_outputs.append(put_scope("group_StartupRun"))

        if task == "OpsiSimulator":
            group_outputs.append(put_scope("group_OpsiSimulatorRuntime"))

        for group, arg_dict in deep_iter(self.ALAS_ARGS[task], depth=1):
            group_output, group_watcher_paths, _ = self._build_config_group(
                group, arg_dict, config, task
            )
            if group_output is not None:
                group_outputs.append(group_output)
                navigator_outputs.append(self._build_navigator(group))
                watcher_paths.extend(group_watcher_paths)
                if task == "EventGeneral" and group[0] == "EventGeneral":
                    group_outputs.append(put_scope("group_EventCalculator"))
                    render_event_calculator = True

        # PyWebIO 的每个独立 output 都会形成一条 WebSocket 指令。将整个配置页
        # 作为嵌套 Output 一次发送，避免数十个控件触发数百次网络往返和重复布局。
        put_scope(
            "_groups",
            [
                put_none(),
                put_scope("groups", group_outputs),
                put_scope("navigator", navigator_outputs),
            ],
        )

        for path in watcher_paths:
            self._bind_config_watcher(path)

        # 依赖已有 DOM scope 或需要执行脚本的特殊区域，在基础配置页落地后再初始化。
        if task == "Alas":
            with use_scope("group_StartupRun"):
                self._render_startup_run_setting()
        elif task == "OpsiSimulator":
            with use_scope("group_OpsiSimulatorRuntime"):
                self._os_simulator()
        elif render_event_calculator:
            self._render_event_calculator(config)

    def _build_config_group(
        self,
        group,
        arg_dict,
        config: Dict[str, Any],
        task: str,
    ) -> tuple[Optional[Output], List[List[str]], int]:
        """构建一个配置分组，延迟到外层页面统一发送。"""
        group_name = group[0]

        output_list: List[tuple[str, Output]] = []
        watcher_paths: List[List[str]] = []
        for (
            arg_name,
            display,
            widget_type,
            resolved_kwargs,
        ) in self._iter_group_arguments(task, group_name, arg_dict, config):
            output_kwargs = resolved_kwargs.copy()
            if group_name == "Scheduler" and arg_name == "NextRun":
                # 立即运行按钮：清空 NextRun 触发调度器立即执行该任务
                run_now_path = f"{task}.Scheduler.NextRun"

                def _run_now(_path=run_now_path):
                    self.modified_config_queue.put({"name": _path, "value": ""})
                    toast(t("Gui.Text.RunNow"))

                run_now_btn = put_html(
                    f'<a href="javascript:void(0)" '
                    f'style="font-size: .75rem; cursor: pointer;">'
                    f'{t("Gui.Text.RunNow")}</a>'
                ).onclick(_run_now)
                output_kwargs["after"] = put_row(
                    [
                        run_now_btn,
                        put_text(self._time_status_text()).style(
                            "font-size: .75rem; opacity: .68;"
                        ),
                    ],
                    size="auto 1fr",
                ).style("margin: .2rem .25rem 0; gap: .5rem;")
            output_kwargs["invalid_feedback"] = t(
                "Gui.Text.InvalidFeedBack", output_kwargs["value"]
            )

            o = put_output(output_kwargs)
            if o is not None:
                output_list.append((arg_name, o))
                if display != "readonly" and widget_type != "stored":
                    watcher_paths.append([task, group_name, arg_name])

        if not output_list:
            return None, [], 0

        content: List[Output] = [put_text(t(f"{group_name}._info.name"))]
        group_help = t(f"{group_name}._info.help")
        if group_help != "":
            content.append(put_text(group_help))
        content.append(put_html('<hr class="hr-group">'))

        for arg_name, output in output_list:
            field_scope = config_search_field_scope(task, group_name, arg_name)
            content.append(put_scope(field_scope, content=[output]))

        # 在掉落记录组中显示可复制的设备ID
        if group_name == "DropRecord":
            device_id = DEMO_DEVICE_ID_TEXT if is_demo_mode() else get_device_id()
            content.append(put_html(build_copyable_device_id(device_id)))

        return (
            put_scope(f"group_{group_name}", content=content),
            watcher_paths,
            len(output_list),
        )

    @use_scope("groups")
    def set_group(self, group, arg_dict, config: Dict[str, Any], task: str) -> int:
        """兼容总览页：单独构建并发送一个配置分组。"""
        group_output, watcher_paths, output_count = self._build_config_group(
            group, arg_dict, config, task
        )
        if group_output is None:
            return 0

        group_output.show()
        for path in watcher_paths:
            self._bind_config_watcher(path)
        return output_count

    def _build_navigator(self, group) -> Output:
        """构建分组导航按钮，供配置页统一批量输出。"""
        js = f"""
            $("#pywebio-scope-groups").scrollTop(
                $("#pywebio-scope-group_{group[0]}").position().top
                + $("#pywebio-scope-groups").scrollTop() - 59
            )
        """
        return put_button(
            label=t(f"{group[0]}._info.name"),
            onclick=lambda: run_js(js),
            color="navigator",
        )

    @use_scope("navigator")
    def set_navigator(self, group):
        self._build_navigator(group).show()

    def _alas_start(self):
        self.alas.start(None, updater.event)

    def _simulator_start(self):
        if is_demo_mode():
            logger.info("[WebUI] DEMO=1，跳过大世界模拟器启动。")
            return
        self.simulator.start()

    def _bind_config_watcher(self, path: List[str]) -> None:
        """为已渲染的配置控件注册一次变更监听。"""
        pin_name = "_".join(path)
        watcher_pins = getattr(self, "_config_watcher_pins", None)
        if watcher_pins is None:
            watcher_pins = set()
            self._config_watcher_pins = watcher_pins
        if pin_name in watcher_pins:
            return

        path_text = ".".join(path)

        def put_queue(value: Any) -> None:
            self.modified_config_queue.put({"name": path_text, "value": value})

        pin_on_change(name=pin_name, onchange=put_queue)
        watcher_pins.add(pin_name)

    def _alas_thread_update_config(self) -> None:
        modified = {}
        while self.alive:
            try:
                d = self.modified_config_queue.get(timeout=10)
                config_name = self.alas_name
                config_updater = self.alas_config
            except queue.Empty:
                continue
            modified[d["name"]] = d["value"]
            while True:
                try:
                    d = self.modified_config_queue.get(timeout=1)
                    modified[d["name"]] = d["value"]
                except queue.Empty:
                    self._save_config(modified, config_name, config_updater)
                    modified.clear()
                    break

    def _save_config(
        self,
        modified: Dict[str, Any],
        config_name: str,
        config_updater: Any = State.config_updater,
    ) -> None:
        if os.environ.get("DEMO") == "1":
            return

        try:
            skip_time_record = False
            valid = []
            invalid = []
            config = config_updater.read_file(config_name)
            n = current_time()
            for p, v in deep_iter(config, depth=3):
                if p[-1].endswith("un") and not isinstance(v, bool):
                    if (v - n).days >= 31:
                        deep_set(config, p, "")
            for k, v in modified.copy().items():
                arg_def = deep_get(self.ALAS_ARGS, k, {})
                valuetype = (
                    arg_def.get("valuetype") if isinstance(arg_def, dict) else None
                )
                widget_type = arg_def.get("type") if isinstance(arg_def, dict) else None
                options = arg_def.get("option") if isinstance(arg_def, dict) else None
                # YAML 参数定义允许省略类型；运行时解析器会处理 None，
                # 这里保留原行为并向类型检查器声明该动态边界。
                v = parse_pin_value(
                    v, cast(str, valuetype), cast(str, widget_type), options
                )
                validate = deep_get(self.ALAS_ARGS, k + ".validate")
                if not len(str(v)):
                    default = deep_get(self.ALAS_ARGS, k + ".value")
                    modified[k] = default
                    deep_set(config, k, default)
                    valid.append(k)
                    pin["_".join(k.split("."))] = default

                elif not validate or re_fullmatch(validate, v):
                    deep_set(config, k, v)
                    modified[k] = v
                    valid.append(k)
                    for set_key, set_value in config_updater.save_callback(k, v):
                        modified[set_key] = set_value
                        deep_set(config, set_key, set_value)
                        valid.append(set_key)
                        pin["_".join(set_key.split("."))] = to_pin_value(set_value)
                    # ==================== 自定义弹窗逻辑 ====================
                    # 当保存侵蚀1兑换凭证保留值为 0 时弹出提示
                    try:
                        is_zero_preserve = int(cast(Any, v)) == 0
                    except (TypeError, ValueError):
                        is_zero_preserve = False
                    if (
                        k
                        in [
                            "OpsiHazard1Leveling.OpsiHazard1Leveling.OperationCoinsPreserve",
                            "OpsiScheduling.OpsiScheduling.OperationCoinsPreserve",
                        ]
                        and is_zero_preserve
                    ):
                        from pywebio.output import popup, put_html, PopupSize

                        popup(
                            "你在干什么？",
                            [
                                put_html(
                                    '<div style="line-height:1.8;font-size:14px;">'
                                    "任务帮助文本这里都写了，你是完全不看啊，写了跟白写了一样还问问问我就要我偏不，你就是找骂<br><br>"
                                    "为什么保留黄币没有暴露在前端，因为那是用来防呆的，防的就是像你一样的脑瘫自以为是71魔怔人，盲目地将保留数量改成0，然后没有黄币买不起行动力，然后跑跑跑黄币和行动力全亏完又回来瞎鸡巴乱叫，像你妈的个弱智睁大你的马眼看看猫商店的行动力箱子是要用黄币买的，没黄币你买鸡巴还做春秋大梦赚行动力<br><br>"
                                    "为什么 Alas社区准则 不允许讨论71，就是因为像你一样的71魔怔人太多了，然后大魔怔人带小魔怔人，跟苍蝇吃屎一样一生生一窝，我不骂你那不知道的还以为你这是主流玩法，我是不知道你从哪里看的狗屎攻略还是民科搞发明创造出来的，你只需要打开功能开始运行就能获得顶尖玩家的决策水平，但是有现成的功能你不用，十足超人高中生发现了世界的真理，只有你是聪明逼剩余都是傻逼<br><br>"
                                    "我来告诉你71怎么刷，那就是帮助文本里写的可惜你没看，告诉你答案你不服气我就要改，改改改改你妈了个臭嗨改，能力没有皮是比包皮还皮，能耐得飞起比性无能还能，说白了你不是来寻求最大收益的，你是来砸场子的，你非要Alas对着你那收益屌差的游戏玩法去设计，连同全体Alas用户跟着运行<br><br>"
                                    "我来告诉你71魔怔人是怎么样的魔怔，首先第一个就是打死不留黄币，第二大就是打死不短猫<br><br>"
                                    "1.打死不留黄币，完全不知道71要消耗黄币，觉得自己很多黄币以为行动力是无中生有超级摸牌<br>"
                                    "2.打死不短猫，完全不知道黄币靠短猫回，屯几千行动力当天地银元留给亲妈下葬<br>"
                                    "3.打死不带奶，带一摞低级船不带输出不带奶贪经验贪到死，打一回合死一百万人修一百万次<br>"
                                    "4.幻想当赌神，年轻人第一次网络菠菜，行动力亏没了不仅大声叫还要继续刷，裤衩子亏没了还要梭哈<br>"
                                    "5.幻想刷委托，跑图又慢概率又低，觉得能无限打怪当2-4代餐<br>"
                                    "6.幻想有魔法，什么只留蓝箱子能提高猫商店刷新概率，哇说出这话的人不枪毙两小时概率论老师真是死不瞑目<br><br>"
                                    "反正我讲了这么多我知道你是肯定不会听的，你的内心肯定是屌你妈逼臭傻逼，完全听不进去，但是我还是要把整个71的玩法再念叨一遍，不是讲给你听的，是讲给看我骂你的人听的<br><br>"
                                    "1.71的收益是经验和金菜金材料，以及让你的Alas一直运行虽然不知道在干什么但是感觉很爽。71的经验是每10w黄币73w（单个角色没有心情加成）就像天上掉金子一样稍微接点就够发一辈子的那种。如果你的帐号进入游戏末期，经验没用因为卡心智那收益就是每10w黄币换9.36金菜，石油就2-4刷委托这样能获得经验物资魔方金菜钻石等等所有的游戏资源<br>"
                                    "2.71的收益来源是黄币，行动力是催化剂，71大量消耗黄币获取行动力，短猫消耗多余行动力补充部分黄币，二者是相辅相成的，Alas会自动保持他们之间的动态平衡。20小时71能消耗10w黄币多884行动力，再短猫4小时返还3.5w，每月能获取的黄币是有限的因此71的收益也是有限的<br>"
                                    "3.运行71的前提是你能完成大世界每日商店深渊隐秘balabala全部来获得金彩材料，多余的黄币再来运行71，否则就是本末倒置<br>"
                                    "4.千万不要买紫币，紫币的主要来源是要塞，白票的主要来源是月度boss，只要你大世界用Alas全勤紫币和白票都是不缺的，猫商店紫币多20%那是多20%白票，但在71里白票的价值体系直接作废所有东西用黄币来衡量，买紫币相当于用稀缺资源兑换溢出资源<br>"
                                    "5.71本质是赛博菠菜，消耗5行动力赌5%猫商店刷新，外加两个装置各4%其中一个拆了能爆点行动力，赌赢了你别笑赌输了你别叫，没有抽卡保底就是嗯roll， 猫商店刷新权重 解包都有也没有玄学，只能说从数学期望的角度是赚的，但没保底的随机是真的恶心。有1000行动力本钱就是90%概率不翻车，2000就是98%，已经边际效应了再高不能了不如赶紧转换为黄币<br>"
                                    "6.建议行动力买满，这样玩输了还有加仓的机会能再次转起来，丢10000油进71产出的经验也比丢主线图高出一个数量级<br>"
                                    "7.开启71的任务后Alas的运行逻辑会发生变化，用来提高收益和减少呆瓜，包括前面说的71短猫动态平衡，全局不买紫币，还有最少留100行动力防止明天不够做每日，月初用赚来的行动力做隐秘深渊要塞防止行动力被秒吸干转不起来，月底停71防止浪费"
                                    "</div>"
                                )
                            ],
                            size=PopupSize.LARGE,
                        )
                    # ========================================================
                else:
                    modified.pop(k)
                    invalid.append(k)
                    logger.warning(f"[WebUI-任务配置] 无效值 {v}，键 {k}，跳过保存")
            self.pin_remove_invalid_mark(valid)
            self.pin_set_invalid_mark(invalid)
            if modified:
                toast(
                    t("Gui.Toast.ConfigSaved"),
                    duration=1,
                    position="right",
                    color="success",
                )
                logger.info(
                    f"[WebUI-任务配置] 保存配置 {filepath_config(config_name)}, {dict_to_kv(modified)}"
                )
                config_updater.write_file(config_name, config)
                self._invalidate_config_search_cache()
        except Exception as e:
            logger.exception(e)
