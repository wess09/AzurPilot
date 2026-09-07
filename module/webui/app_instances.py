"""WebUI实例切换创建和导入"""

from typing import TYPE_CHECKING, cast

from module.webui.app_dependencies import (
    ProcessManager,
    State,
    alas_instance,
    alas_template,
    clear,
    close_popup,
    get_config_mod,
    load_config,
    pin,
    popup,
    put_buttons,
    put_error,
    put_html,
    put_input,
    put_markdown,
    put_scope,
    put_select,
    run_js,
    t,
    toast,
    use_scope,
)
from module.webui.app_manage import app_manage

if TYPE_CHECKING:
    from module.webui.app import AlasGUI

from module.webui.app_types import WebUIMixinBase


class InstanceMixin(WebUIMixinBase):
    """WebUI实例切换创建和导入"""

    def ui_alas(self, config_name: str) -> None:
        self._set_manage_mode(False)
        if config_name == self.alas_name:
            self.expand_menu()
            return
        self._active_aside = config_name
        self.init_aside(name=config_name)
        clear("content")
        self.alas_name = config_name
        self.alas_mod = get_config_mod(config_name)
        self.alas = ProcessManager.get_manager(config_name)
        self.alas_config = load_config(config_name)
        if hasattr(self, "state_switch"):
            try:
                self.state_switch.switch()
            except Exception:
                # best-effort: ignore if switch not ready
                pass
        self.initial()
        self.alas_set_menu()

    def ui_add_alas(self) -> None:
        with popup(t("Gui.AddAlas.PopupTitle")) as s:

            def get_unused_name():
                all_name = alas_instance()
                for i in range(2, 100):
                    if f"alas{i}" not in all_name:
                        return f"alas{i}"
                else:
                    return ""

            def add():
                name = cast(str, pin["AddAlas_name"])
                origin = cast(str, pin["AddAlas_copyfrom"])

                if name in alas_instance():
                    err = "Gui.AddAlas.FileExist"
                elif set(name) & set(".\\/:*?\"'<>|"):
                    err = "Gui.AddAlas.InvalidChar"
                elif name.lower().startswith("template"):
                    err = "Gui.AddAlas.InvalidPrefixTemplate"
                else:
                    err = ""
                if err:
                    clear(s)
                    put(name, origin)
                    put_error(t(err), scope=s)
                    return

                r = load_config(origin).read_file(origin)
                State.config_updater.write_file(name, r, get_config_mod(origin))
                self.refresh_aside_instances(force=True)
                close_popup()

            def manage():
                close_popup()
                self.ui_manage()

            def put(name=None, origin=None):
                put_input(
                    name="AddAlas_name",
                    label=t("Gui.AddAlas.NewName"),
                    value=name or get_unused_name(),
                    scope=s,
                )
                put_select(
                    name="AddAlas_copyfrom",
                    label=t("Gui.AddAlas.CopyFrom"),
                    options=alas_template() + alas_instance(),
                    value=origin or "template-alas",
                    scope=s,
                )
                put_buttons(
                    buttons=[
                        {"label": t("Gui.AddAlas.Confirm"), "value": "confirm"},
                        {"label": t("Gui.AddAlas.Manage"), "value": "manage"},
                    ],
                    onclick=[
                        add,
                        manage,
                    ],
                    scope=s,
                )

            put()

    @use_scope("content", clear=True)
    def ui_import_legacy(self) -> None:
        """管理菜单：导入旧 AzurPilot 数据。"""
        self.init_menu(name="ManageImportLegacy")
        self.set_title(t("Gui.AppManage.ImportLegacy"))

        def import_legacy_upload():
            toast(
                t("Gui.AppManage.ImportLegacySelecting"),
                color="info",
                duration=0,
            )
            run_js(
                """
            (function(){
                var input = document.createElement('input');
                input.type = 'file';
                input.setAttribute('webkitdirectory', '');
                input.setAttribute('multiple', '');
                input.style.display = 'none';

                input.addEventListener('change', async function(e) {
                    var files = e.target.files;
                    document.body.removeChild(input);
                    if (!files || files.length === 0) return;

                    var formData = new FormData();
                    var matched = 0, skipped = 0, total = files.length;

                    for (var i = 0; i < total; i++) {
                        var file = files[i];
                        var relPath = '/' + file.webkitRelativePath.replace(/\\\\/g, '/');
                        var name = relPath.split('/').pop().toLowerCase();

                        var pp = relPath.split('/');
                        var si = 1;
                        if (pp.length >= 3 && pp[1] !== 'config' && pp[1] !== 'log') si = 2;
                        var subPath = pp.slice(si).join('/');

                        var ok = false;
                        if (subPath.startsWith('config/')) {
                            if ((name.endsWith('.json') || name.endsWith('.db')) && !name.startsWith('template')) ok = true;
                        } else if (subPath.startsWith('log/cl1/')) {
                            ok = true;
                        } else if (subPath === 'log/azurstat_meowofficer_farming.csv') {
                            ok = true;
                        }

                        if (!ok) { skipped++; continue; }
                        matched++;
                        formData.append('file', file, relPath);
                    }

                    if (matched === 0) {
                        sessionStorage.setItem('import_msg', JSON.stringify({ok:false, error:legacyNoMatch}));
                        window.location.assign('/manage');
                        return;
                    }

                    try {
                        var resp = await fetch('/api/import_legacy_upload', { method: 'POST', body: formData });
                        var result = await resp.json();
                        if (result.success) {
                            result.data.total = total;
                            sessionStorage.setItem('import_msg', JSON.stringify({ok:true, data:result.data, total:total}));
                        } else {
                            sessionStorage.setItem('import_msg', JSON.stringify({ok:false, error:result.error || legacyUnknownError}));
                        }
                    } catch (err) {
                        sessionStorage.setItem('import_msg', JSON.stringify({ok:false, error:legacyRequestFailed + ': ' + err.message}));
                    }
                    window.location.assign('/manage');
                });

                document.body.appendChild(input);
                input.click();
            })();
            """,
                legacyNoMatch=t("Gui.AppManage.ImportLegacyNoMatch"),
                legacyRequestFailed=t("Gui.AppManage.ImportLegacyRequestFailed"),
                legacyUnknownError=t("Gui.AppManage.ImportLegacyUnknownError"),
            )

        put_scope("develop_detail")
        with use_scope("develop_detail"):
            put_html(
                '<h2 class="alas-develop-section-title">'
                f"{t('Gui.AppManage.ImportLegacyTitle')}</h2>"
            )
            put_markdown(
                f"{t('Gui.AppManage.ImportLegacyHint')}\n\n"
                f"**{t('Gui.AppManage.ImportLegacyContent')}**\n\n"
                f"> {t('Gui.AppManage.ImportLegacyWarning')}"
            )
            put_scope("import_btn")
        with use_scope("import_btn"):
            put_buttons(
                [
                    {
                        "label": t("Gui.AppManage.ImportLegacyChoose"),
                        "value": "upload",
                        "color": "primary",
                    },
                ],
                onclick=[import_legacy_upload],
            )

    @use_scope("content", clear=True)
    def ui_manage(self) -> None:
        self.mount_shell()
        if self._active_aside == "Manage":
            self.expand_menu()
            return
        self._set_manage_mode(True)
        self._active_aside = "Manage"
        self.init_aside(expand_menu=False)
        self.init_menu()
        self.active_button("aside", "Manage")
        self.set_title(t("Gui.AppManage.PageTitle"))
        self.alas_name = ""
        if hasattr(self, "alas"):
            del self.alas
        self.set_status(0)
        app_manage(cast("AlasGUI", self))

    @staticmethod
    def _set_manage_mode(enabled: bool) -> None:
        run_js(
            "document.body.classList.toggle('alas-manage-active', enabled)",
            enabled=enabled,
        )

    def mount_shell(self) -> None:
        """创建一次页头、侧栏、二级菜单和内容区。"""
        if self._shell_mounted:
            return
        self._show()
        self._shell_mounted = True
        self.set_aside()
        self._inject_unverified_branch_watermark()
