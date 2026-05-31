# OOBE (Out-Of-Box Experience) 初次设置向导
# 在用户首次启动、没有配置文件时引导完成基本设置
#
# 重要：PyWebIO 的 put_html 输出原始 HTML，与 PyWebIO 组件在 DOM 中是平级兄弟节点，
# 不能互相嵌套。因此卡片布局通过 CSS 定位 PyWebIO scope 容器实现，不使用 raw HTML wrapper。
import subprocess
import os

from pywebio.output import (
    clear,
    put_buttons,
    put_html,
    put_scope,
    use_scope,
)
from pywebio.pin import pin
from pywebio.pin import pin_on_change
from pywebio.session import run_js, set_env
from module.webui.pin import put_input, put_select

import module.webui.lang as lang
from module.config.deep import deep_set
from module.config.server import VALID_CHANNEL_PACKAGE, VALID_PACKAGE, VALID_SERVER_LIST, to_server
from module.submodule.submodule import load_config
from module.webui.setting import State
from module.webui.utils import Icon, add_css, filepath_css

# PyWebIO scope 的 DOM ID 格式为 `pywebio-scope-{name}`
OOBE_ROOT = "oobe_root"

CSS = """
/* === OOBE shell === */
body {
    background: #f5f5f7 !important;
}

#pywebio-scope-oobe_root {
    min-height: 100vh;
    display: flex !important;
    align-items: center;
    justify-content: center;
    padding: 28px;
    box-sizing: border-box;
}

#pywebio-scope-oobe_content {
    background: var(--alas-content-bg, #fff);
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 28px;
    box-shadow: 0 28px 80px rgba(0, 0, 0, 0.10), 0 2px 10px rgba(0, 0, 0, 0.04);
    width: 100% !important;
    max-width: 860px;
    min-height: 620px;
    padding: 42px 48px 36px !important;
    box-sizing: border-box;
    overflow: hidden;
}

#pywebio-scope-oobe_content > * {
    animation: oobe-view-enter .42s cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes oobe-view-enter {
    0% {
        opacity: 0;
        transform: translateY(14px) scale(0.992);
        filter: blur(2px);
    }
    100% {
        opacity: 1;
        transform: translateY(0) scale(1);
        filter: blur(0);
    }
}

.oobe-brand {
    text-align: center;
    padding: 4px 0 24px;
    border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}

.oobe-intro {
    min-height: 440px;
    display: grid;
    align-items: center;
    justify-items: center;
    text-align: center;
}

.oobe-intro-center {
    display: grid;
    gap: 28px;
    justify-items: center;
}

.oobe-intro .oobe-hello-rotator {
    height: 92px;
    min-width: 420px;
}

.oobe-intro .oobe-hello-word {
    font-size: 64px;
    font-weight: 650;
}

#pywebio-scope-oobe_content .oobe-intro + .btn-group .btn {
    width: 52px !important;
    min-width: 52px !important;
    height: 52px !important;
    min-height: 52px !important;
    padding: 0 !important;
    border-radius: 999px !important;
    font-size: 25px !important;
    line-height: 1 !important;
    background: rgba(0, 122, 255, 0.10) !important;
    border-color: transparent !important;
    color: #007aff !important;
}

#pywebio-scope-oobe_content .oobe-intro + .btn-group .btn:hover {
    background: rgba(0, 122, 255, 0.16) !important;
}

.oobe-brand-main {
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    gap: 14px;
}

.oobe-hello-stage {
    display: grid;
    gap: 16px;
    justify-items: center;
    margin-bottom: 22px;
}

.oobe-hello-rotator {
    position: relative;
    width: 100%;
    height: 72px;
    overflow: hidden;
}

.oobe-hello-word {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0;
    color: var(--alas-content-text, #1d1d1f);
    font-size: 58px;
    font-weight: 650;
    line-height: 1;
    letter-spacing: 0;
    opacity: 0;
    transform: translateY(18px) scale(0.985);
    animation: oobe-hello-cycle 24s cubic-bezier(0.22, 1, 0.36, 1) infinite;
}

.oobe-hello-word:nth-child(1) { animation-delay: 0s; }
.oobe-hello-word:nth-child(2) { animation-delay: 2s; }
.oobe-hello-word:nth-child(3) { animation-delay: 4s; }
.oobe-hello-word:nth-child(4) { animation-delay: 6s; }
.oobe-hello-word:nth-child(5) { animation-delay: 8s; }
.oobe-hello-word:nth-child(6) { animation-delay: 10s; }
.oobe-hello-word:nth-child(7) { animation-delay: 12s; }
.oobe-hello-word:nth-child(8) { animation-delay: 14s; }
.oobe-hello-word:nth-child(9) { animation-delay: 16s; }
.oobe-hello-word:nth-child(10) { animation-delay: 18s; }
.oobe-hello-word:nth-child(11) { animation-delay: 20s; }
.oobe-hello-word:nth-child(12) { animation-delay: 22s; }

@keyframes oobe-hello-cycle {
    0% {
        opacity: 0;
        transform: translateY(18px) scale(0.985);
        filter: blur(3px);
    }
    4% {
        opacity: 1;
        transform: translateY(0) scale(1);
        filter: blur(0);
    }
    8% {
        opacity: 1;
        transform: translateY(0) scale(1);
        filter: blur(0);
    }
    12% {
        opacity: 0;
        transform: translateY(-18px) scale(0.985);
        filter: blur(3px);
    }
    100% {
        opacity: 0;
        transform: translateY(-18px) scale(0.985);
        filter: blur(3px);
    }
}

@media (prefers-reduced-motion: reduce) {
    #pywebio-scope-oobe_content > * {
        animation: none;
    }
    .oobe-hello-word {
        animation: none;
        opacity: 0;
        transform: none;
        filter: none;
    }
    .oobe-hello-word:first-child {
        opacity: 1;
    }
}

.oobe-brand-icon {
    width: 72px;
    height: 72px;
    flex: 0 0 72px;
    border-radius: 18px;
    overflow: hidden;
    background: #fff;
    box-shadow: 0 14px 34px rgba(0, 0, 0, 0.14);
}

.oobe-brand-icon img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    border-radius: inherit;
}

.oobe-brand-icon .alas-icon,
.oobe-brand-icon .alas-icon > image {
    width: 100% !important;
    height: 100% !important;
}

.oobe-brand-icon .alas-icon {
    display: block;
    border-radius: inherit;
}

.oobe-title {
    font-size: 24px;
    font-weight: 650;
    color: var(--alas-content-text, #1d1d1f);
    margin: 0 0 5px;
    letter-spacing: 0;
    line-height: 1.18;
}

.oobe-subtitle {
    font-size: 14px;
    color: #6e6e73;
    margin: 0;
    line-height: 1.6;
    text-align: left;
}

.oobe-steps {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
    margin: 28px 0 30px;
}

.oobe-step {
    display: flex;
    align-items: center;
    min-width: 0;
    padding: 10px 11px;
    border-radius: 14px;
    border: 1px solid rgba(0, 0, 0, 0.08);
    background: #fbfbfd;
    color: #6e6e73;
}

.oobe-step-index {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    flex: 0 0 22px;
    margin-right: 8px;
    border-radius: 999px;
    background: #e8e8ed;
    color: #6e6e73;
    font-size: 12px;
    font-weight: 750;
}

.oobe-step-label {
    display: block;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 12.5px;
    font-weight: 650;
}

.oobe-step.active {
    border-color: rgba(0, 122, 255, 0.34);
    background: rgba(0, 122, 255, 0.08);
    color: #007aff;
}

.oobe-step.active .oobe-step-index,
.oobe-step.done .oobe-step-index {
    background: #007aff;
    color: #fff;
}

.oobe-step.done {
    color: #007aff;
}

.oobe-section-title {
    margin: 0 0 6px;
    font-size: 18px;
    font-weight: 720;
    color: var(--alas-content-text, #1d1d1f);
    letter-spacing: 0;
}

.oobe-section-hint {
    margin: 0 0 18px;
    color: #6e6e73;
    font-size: 13px;
    line-height: 1.6;
}

.oobe-divider {
    border: none;
    border-top: 1px solid rgba(0, 0, 0, 0.08);
    margin: 22px 0;
}

.oobe-selected-badge {
    display: inline-flex;
    align-items: center;
    min-height: 30px;
    margin-top: 12px;
    padding: 0 12px;
    border-radius: 999px;
    background: rgba(0, 122, 255, 0.08);
    color: #007aff;
    font-size: 12px;
    font-weight: 700;
}

.oobe-choice-section {
    margin-top: 18px;
}

.oobe-choice-title {
    margin: 0 0 10px;
    color: var(--alas-content-text, #1d1d1f);
    font-size: 14px;
    font-weight: 750;
    letter-spacing: 0;
}

.oobe-select-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 14px;
}

.oobe-import-card {
    margin: 10px 0 18px;
    padding: 16px 18px;
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 16px;
    background: #fbfbfd;
}

.oobe-import-card-title {
    margin: 0 0 6px;
    color: var(--alas-content-text, #1d1d1f);
    font-size: 14px;
    font-weight: 750;
}

.oobe-import-card-text {
    margin: 0;
    color: #6e6e73;
    font-size: 13px;
    line-height: 1.6;
}

.oobe-review-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    margin: 6px 0 22px;
    overflow: hidden;
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 12px;
}

.oobe-review-table td {
    padding: 13px 15px;
    border-bottom: 1px solid rgba(0, 0, 0, 0.07);
    font-size: 14px;
    line-height: 1.45;
}

.oobe-review-table tr:last-child td {
    border-bottom: 0;
}

.oobe-review-table td:first-child {
    color: #6e6e73;
    width: 34%;
    font-weight: 650;
    background: #fbfbfd;
}

.oobe-review-table td:last-child {
    color: var(--alas-content-text, #1d1d1f);
    word-break: break-all;
}

#pywebio-scope-oobe_content .form-group {
    margin-bottom: 14px;
}

#pywebio-scope-oobe_content label {
    color: var(--alas-content-text, #1d1d1f);
    font-size: 13px;
    font-weight: 700;
    margin-bottom: 8px;
}

#pywebio-scope-oobe_content .form-control {
    min-height: 44px;
    border: 1px solid rgba(0, 0, 0, 0.12) !important;
    border-radius: 12px !important;
    background: #fbfbfd !important;
    padding: 9px 12px;
    transition: border-color .16s ease, box-shadow .16s ease, background .16s ease;
}

#pywebio-scope-oobe_content .form-control:focus {
    border-color: #007aff !important;
    box-shadow: 0 0 0 4px rgba(0, 122, 255, 0.12) !important;
    background: #fff !important;
}

#pywebio-scope-oobe_content .bootstrap-select,
#pywebio-scope-oobe_content .select,
#pywebio-scope-oobe_content select {
    width: 100% !important;
}

#pywebio-scope-oobe_content .form-group:has(.bootstrap-select),
#pywebio-scope-oobe_content .form-group:has(select) {
    border: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
    padding: 0 !important;
}

#pywebio-scope-oobe_content .form-group > div:has(.bootstrap-select),
#pywebio-scope-oobe_content .form-group > div:has(select),
#pywebio-scope-oobe_content .form-group .input-group {
    border: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
    padding: 0 !important;
}

#pywebio-scope-oobe_content .bootstrap-select {
    border: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
    padding: 0 !important;
}

#pywebio-scope-oobe_content .bootstrap-select > .dropdown-toggle,
#pywebio-scope-oobe_content select.form-control {
    min-height: 54px !important;
    border: 1px solid rgba(0, 0, 0, 0.12) !important;
    border-radius: 16px !important;
    background: #fbfbfd !important;
    color: #1d1d1f !important;
    font-size: 15px !important;
    font-weight: 650 !important;
    line-height: 1.35 !important;
    padding: 0 44px 0 16px !important;
    box-shadow: none !important;
    outline: none !important;
}

#pywebio-scope-oobe_content .bootstrap-select > .dropdown-toggle:focus,
#pywebio-scope-oobe_content .bootstrap-select > .dropdown-toggle:active,
#pywebio-scope-oobe_content .bootstrap-select.show > .dropdown-toggle,
#pywebio-scope-oobe_content select.form-control:focus {
    border-color: #007aff !important;
    background: #fff !important;
    box-shadow: 0 0 0 4px rgba(0, 122, 255, 0.12) !important;
}

#pywebio-scope-oobe_content .bootstrap-select .filter-option {
    display: flex !important;
    align-items: center !important;
    min-height: 52px;
}

#pywebio-scope-oobe_content .bootstrap-select .filter-option-inner,
#pywebio-scope-oobe_content .bootstrap-select .filter-option-inner-inner {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

#pywebio-scope-oobe_content .bootstrap-select .dropdown-menu {
    border: 1px solid rgba(0, 0, 0, 0.10) !important;
    border-radius: 16px !important;
    box-shadow: 0 18px 48px rgba(0, 0, 0, 0.16) !important;
    padding: 8px !important;
    margin-top: 8px !important;
}

#pywebio-scope-oobe_content .bootstrap-select .dropdown-menu li a {
    border-radius: 10px !important;
    color: #1d1d1f !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    padding: 9px 11px !important;
}

#pywebio-scope-oobe_content .bootstrap-select .dropdown-menu li.selected a,
#pywebio-scope-oobe_content .bootstrap-select .dropdown-menu li a:hover {
    background: rgba(0, 122, 255, 0.10) !important;
    color: #007aff !important;
}

#pywebio-scope-oobe_content .bootstrap-select .bs-caret,
#pywebio-scope-oobe_content .bootstrap-select .caret {
    color: #86868b !important;
}

#pywebio-scope-oobe_content .btn {
    border-radius: 999px !important;
    font-size: 14px;
    font-weight: 700;
    padding: 10px 18px;
    min-width: 108px;
    min-height: 42px;
    box-shadow: none !important;
    transition: transform .16s ease, box-shadow .16s ease, background .16s ease;
}

#pywebio-scope-oobe_content .btn:hover {
    transform: translateY(-1px);
    box-shadow: 0 10px 20px rgba(28, 39, 58, 0.12) !important;
}

#pywebio-scope-oobe_content .btn-primary,
#pywebio-scope-oobe_content .btn-success {
    border-color: #007aff !important;
    background: #007aff !important;
    color: #fff !important;
}

#pywebio-scope-oobe_content .btn-success {
    border-color: #34c759 !important;
    background: #34c759 !important;
}

#pywebio-scope-oobe_content .btn-light {
    border: 1px solid rgba(0, 0, 0, 0.12) !important;
    background: #fff !important;
    color: #1d1d1f !important;
}

#pywebio-scope-oobe_content .btn-group {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
}

#pywebio-scope-oobe_content .btn-group > .btn {
    flex: 1 1 138px;
    margin: 0 !important;
}

html[data-theme="dark"] #pywebio-scope-oobe_content,
body.dark #pywebio-scope-oobe_content {
    border-color: rgba(148, 163, 184, 0.16);
}

@media (prefers-color-scheme: dark) {
    body {
        background: #1c1c1e !important;
    }
    .oobe-subtitle,
    .oobe-section-hint,
    .oobe-review-table td:first-child {
        color: #a1a1a6;
    }
    .oobe-hello-word,
    .oobe-title,
    .oobe-section-title,
    #pywebio-scope-oobe_content label,
    .oobe-review-table td:last-child {
        color: #f5f5f7;
    }
    .oobe-step {
        background: rgba(44, 44, 46, 0.72);
        border-color: rgba(255, 255, 255, 0.10);
    }
    .oobe-review-table {
        border-color: rgba(255, 255, 255, 0.10);
    }
    .oobe-review-table td {
        border-bottom-color: rgba(255, 255, 255, 0.08);
    }
    .oobe-review-table td:first-child {
        background: rgba(44, 44, 46, 0.58);
    }
    .oobe-choice-title {
        color: #f5f5f7;
    }
    .oobe-import-card {
        background: rgba(44, 44, 46, 0.58);
        border-color: rgba(255, 255, 255, 0.10);
    }
    .oobe-import-card-title {
        color: #f5f5f7;
    }
    .oobe-import-card-text {
        color: #a1a1a6;
    }
    #pywebio-scope-oobe_content .form-control {
        background: rgba(44, 44, 46, 0.72) !important;
    }
    #pywebio-scope-oobe_content .form-control:focus {
        background: rgba(28, 28, 30, 0.92) !important;
    }
    #pywebio-scope-oobe_content .btn-light {
        background: rgba(44, 44, 46, 0.72) !important;
        color: #e5e7eb !important;
    }
    #pywebio-scope-oobe_content .bootstrap-select > .dropdown-toggle,
    #pywebio-scope-oobe_content select.form-control {
        background: rgba(44, 44, 46, 0.72) !important;
        border-color: rgba(255, 255, 255, 0.12) !important;
        color: #f5f5f7 !important;
    }
    #pywebio-scope-oobe_content .bootstrap-select > .dropdown-toggle:focus,
    #pywebio-scope-oobe_content .bootstrap-select > .dropdown-toggle:active,
    #pywebio-scope-oobe_content .bootstrap-select.show > .dropdown-toggle,
    #pywebio-scope-oobe_content select.form-control:focus {
        background: rgba(58, 58, 60, 0.86) !important;
        border-color: #0a84ff !important;
        box-shadow: 0 0 0 4px rgba(10, 132, 255, 0.20) !important;
    }
    #pywebio-scope-oobe_content .bootstrap-select .dropdown-menu {
        background: #2c2c2e !important;
        border-color: rgba(255, 255, 255, 0.12) !important;
    }
    #pywebio-scope-oobe_content .bootstrap-select .dropdown-menu li a {
        color: #f5f5f7 !important;
    }
    #pywebio-scope-oobe_content .bootstrap-select .dropdown-menu li.selected a,
    #pywebio-scope-oobe_content .bootstrap-select .dropdown-menu li a:hover {
        background: rgba(10, 132, 255, 0.18) !important;
        color: #0a84ff !important;
    }
}

@media (max-width: 640px) {
    #pywebio-scope-oobe_root {
        align-items: stretch;
        padding: 12px;
    }
    #pywebio-scope-oobe_content {
        min-height: calc(100vh - 24px);
        padding: 24px 18px 22px !important;
        border-radius: 14px;
    }
    .oobe-brand {
        padding-bottom: 18px;
    }
    .oobe-brand-main {
        justify-content: flex-start;
    }
    .oobe-hello-stage {
        gap: 10px;
        margin-bottom: 18px;
    }
    .oobe-intro {
        min-height: calc(100vh - 70px);
    }
    .oobe-intro .oobe-hello-rotator {
        height: 62px;
        min-width: 0;
        width: 100%;
    }
    .oobe-intro .oobe-hello-word {
        font-size: 44px;
    }
    #pywebio-scope-oobe_content .oobe-intro + .btn-group .btn {
        width: 48px !important;
        min-width: 48px !important;
        height: 48px !important;
        min-height: 48px !important;
    }
    .oobe-hello-rotator {
        height: 52px;
    }
    .oobe-hello-word {
        font-size: 40px;
    }
    .oobe-brand-icon {
        width: 62px;
        height: 62px;
        flex-basis: 62px;
    }
    .oobe-title {
        font-size: 21px;
    }
    .oobe-steps {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 8px;
        margin: 18px 0 22px;
    }
    .oobe-step {
        padding: 9px 10px;
    }
    #pywebio-scope-oobe_content .btn-group {
        display: grid;
        grid-template-columns: 1fr;
    }
    #pywebio-scope-oobe_content .btn-group > .btn {
        width: 100%;
    }
}
"""


class OOBEWizard:
    """OOBE 向导 — 居中卡片式 UI"""

    STEPS = ["intro", "import", "welcome", "server", "emulator", "review"]

    def __init__(self, gui):
        self.gui = gui
        self.step_index = 0
        self.server = "cn"
        self.emulator_serial = "127.0.0.1:5555"
        self.package_name = "com.bilibili.azurlane"
        self.server_name = "cn_android-0"
        self.config_name = "alas"
        self.screenshot_method = "auto"
        existing_lang = getattr(State.deploy_config, "Language", None)
        if existing_lang:
            try:
                lang.set_language(existing_lang)
            except Exception:
                pass

    @use_scope("ROOT", clear=True)
    def start(self):
        set_env(title="AzurPilot - Setup", output_animation=False)
        add_css(filepath_css("alas"))
        if self.gui.is_mobile:
            add_css(filepath_css("alas-mobile"))
        else:
            add_css(filepath_css("alas-pc"))
        if self.gui.theme == "dark":
            add_css(filepath_css("dark-alas"))
        elif self.gui.theme == "socialism":
            add_css(filepath_css("socialism-alas"))
        elif self.gui.theme == "children":
            add_css(filepath_css("children-alas"))
        else:
            add_css(filepath_css("light-alas"))

        put_html(f"<style>{CSS}</style>")
        put_scope(OOBE_ROOT)
        self._render()

    # ─── 导航 ───

    def _next_step(self):
        self.step_index += 1
        run_js("window.scrollTo(0, 0);")
        self._render()

    def _prev_step(self):
        self.step_index -= 1
        self._render()

    # ─── 整体渲染 ───
    # 使用 put_scope("oobe_content") 作为卡片容器（CSS 上方通过 #pywebio-scope-oobe_content 定位）

    def _render(self):
        clear(OOBE_ROOT)
        with use_scope(OOBE_ROOT):
            put_scope("oobe_content")
            with use_scope("oobe_content"):
                if self.STEPS[self.step_index] != "intro":
                    self._render_brand()
                    self._render_steps()
                getattr(self, f"_step_{self.STEPS[self.step_index]}")()

    # ─── 静态装饰 ───

    @staticmethod
    def _hello_words():
        return [
            "你好",
            "Hello",
            "こんにちは",
            "Bonjour",
            "Hola",
            "Ciao",
            "Hallo",
            "안녕하세요",
            "Olá",
            "Привет",
            "Hej",
            "สวัสดี",
        ]

    def _render_hello_rotator(self):
        hello_rotator = "".join(
            f'<span class="oobe-hello-word">{word}</span>'
            for word in self._hello_words()
        )
        return f'<div class="oobe-hello-rotator">{hello_rotator}</div>'

    def _render_brand(self):
        put_html(
            '<div class="oobe-brand">'
            '<div class="oobe-brand-main">'
            '<div class="oobe-brand-icon">'
            f'{Icon.ALAS}'
            '</div>'
            '<div>'
            f'<h1 class="oobe-title">{lang.t("Gui.OOBE.WelcomeTitle")}</h1>'
            f'<p class="oobe-subtitle">{lang.t("Gui.OOBE.WelcomeDescription")}</p>'
            '</div>'
            '</div>'
            '</div>'
        )

    def _render_steps(self):
        labels = [
            lang.t("Gui.OOBE.ImportTitle"),
            lang.t("Gui.OOBE.WelcomeSelectLanguage"),
            lang.t("Gui.OOBE.ServerTitle"),
            lang.t("Gui.OOBE.EmulatorTitle"),
            lang.t("Gui.OOBE.ReviewTitle"),
        ]
        steps = ""
        setup_index = self.step_index - 1
        for i in range(len(labels)):
            cls = "active" if i == setup_index else ("done" if i < setup_index else "")
            steps += (
                f'<div class="oobe-step {cls}">'
                f'<span class="oobe-step-index">{i + 1}</span>'
                f'<span class="oobe-step-label">{labels[i]}</span>'
                '</div>'
            )
        put_html(f'<div class="oobe-steps">{steps}</div>')

    # ─── 步骤 0：欢迎页 ───

    def _step_intro(self):
        put_html(
            '<div class="oobe-intro">'
            '<div class="oobe-intro-center">'
            f'{self._render_hello_rotator()}'
            '</div>'
            '</div>'
        )
        put_buttons(
            [{"label": "→", "value": "next", "color": "light"}],
            onclick=lambda _: self._next_step(),
        ).style("display:flex; justify-content:center;")

    def _render_step_header(self, title, hint):
        put_html(
            f'<h2 class="oobe-section-title">{title}</h2>'
            f'<p class="oobe-section-hint">{hint}</p>'
        )

    # ─── 底部导航 ───

    def _render_footer(self, back=True, next_label=None, next_color="primary",
                       on_next=None, on_back=None):
        from pywebio.output import put_row

        cb_back = on_back or (lambda _: self._prev_step())
        cb_next = on_next or (lambda _: self._next_step())
        label = next_label or f"{lang.t('Gui.OOBE.ButtonNext')} →"

        if back:
            put_row(
                [
                    put_buttons(
                        [{"label": f"← {lang.t('Gui.OOBE.ButtonBack')}", "value": "back",
                          "color": "light"}],
                        onclick=lambda _: cb_back(None),
                    ),
                    put_buttons(
                        [{"label": label, "value": "next", "color": next_color}],
                        onclick=lambda _: cb_next(None),
                    ),
                ],
                size="auto auto",
            ).style("justify-content: space-between; margin-top: 24px;")
        else:
            put_row(
                [
                    None,
                    put_buttons(
                        [{"label": label, "value": "next", "color": next_color}],
                        onclick=lambda _: cb_next(None),
                    ),
                ],
                size="auto auto",
            ).style("justify-content: flex-end; margin-top: 24px;")

    # ─── 步骤 1：导入配置 ───

    def _step_import(self):
        put_html(
            f'<h2 class="oobe-section-title">{lang.t("Gui.OOBE.ImportTitle")}</h2>'
            f'<p class="oobe-section-hint">{lang.t("Gui.OOBE.ImportHint")}</p>'
        )
        put_html(
            '<div class="oobe-import-card">'
            f'<p class="oobe-import-card-title">{lang.t("Gui.OOBE.ImportCardTitle")}</p>'
            f'<p class="oobe-import-card-text">{lang.t("Gui.OOBE.ImportCardText")}</p>'
            '</div>'
        )
        put_html('<hr class="oobe-divider">')
        self._render_footer(
            back=True,
            next_label=lang.t("Gui.OOBE.ImportSkip"),
            next_color="light",
            on_next=lambda _: self._next_step(),
            on_back=lambda _: self._prev_step(),
        )
        put_buttons(
            [{"label": lang.t("Gui.OOBE.ImportButton"), "value": "import", "color": "primary"}],
            onclick=lambda _: self._open_legacy_import_picker(),
        ).style("justify-content:flex-end; margin-top:10px;")

    def _open_legacy_import_picker(self):
        run_js(f"""
        (function(){{
            var input = document.createElement('input');
            input.type = 'file';
            input.setAttribute('webkitdirectory', '');
            input.setAttribute('multiple', '');
            input.style.display = 'none';

            input.addEventListener('change', async function(e) {{
                var files = e.target.files;
                document.body.removeChild(input);
                if (!files || files.length === 0) return;

                var formData = new FormData();
                var matched = 0, total = files.length;

                for (var i = 0; i < total; i++) {{
                    var file = files[i];
                    var relPath = '/' + file.webkitRelativePath.replace(/\\\\/g, '/');
                    var name = relPath.split('/').pop().toLowerCase();
                    var pp = relPath.split('/');
                    var si = 1;
                    if (pp.length >= 3 && pp[1] !== 'config' && pp[1] !== 'log') si = 2;
                    var subPath = pp.slice(si).join('/');

                    var ok = false;
                    if (subPath.startsWith('config/')) {{
                        if ((name.endsWith('.json') || name.endsWith('.db')) && !name.startsWith('template')) ok = true;
                    }} else if (subPath.startsWith('log/cl1/')) {{
                        ok = true;
                    }} else if (subPath === 'log/azurstat_meowofficer_farming.csv') {{
                        ok = true;
                    }}

                    if (!ok) continue;
                    matched++;
                    formData.append('file', file, relPath);
                }}

                if (matched === 0) {{
                    alert({lang.t("Gui.OOBE.ImportErrorNoMatch")!r});
                    return;
                }}

                try {{
                    var resp = await fetch('/api/import_legacy_upload', {{ method: 'POST', body: formData }});
                    var result = await resp.json();
                    if (!result.success) {{
                        alert({lang.t("Gui.OOBE.ImportErrorFailed")!r} + ': ' + (result.error || 'unknown'));
                        return;
                    }}
                    location.reload();
                }} catch (err) {{
                    alert({lang.t("Gui.OOBE.ImportErrorFailed")!r} + ': ' + err.message);
                }}
            }});

            document.body.appendChild(input);
            input.click();
        }})();
        """)


    # ─── 步骤 1：语言选择 ───

    def _step_welcome(self):
        put_html(
            f'<h2 class="oobe-section-title">{lang.t("Gui.OOBE.WelcomeSelectLanguage")}</h2>'
            f'<p class="oobe-section-hint">{lang.t("Gui.OOBE.WelcomeHint")}</p>'
        )
        put_buttons(
            [
                {"label": "简体中文", "value": "zh-CN"},
                {"label": "English", "value": "en-US"},
                {"label": "日本語", "value": "ja-JP"},
                {"label": "繁體中文", "value": "zh-TW"},
            ],
            onclick=lambda l: self._on_language_selected(l),
        )
        put_html('<hr class="oobe-divider">')
        self._render_footer(back=False)

    def _on_language_selected(self, l):
        lang.set_language(l)
        lang_to_server = {"zh-CN": "cn", "en-US": "en", "ja-JP": "jp", "zh-TW": "tw"}
        if l in lang_to_server:
            self.server = lang_to_server[l]
            self.package_name = self._package_for_server(self.server)
            self.server_name = self._default_server_name_for_region(self.server)
        self._render()

    # ─── 步骤 2：服务器选择 ───

    def _step_server(self):
        put_html(
            f'<h2 class="oobe-section-title">{lang.t("Gui.OOBE.ServerTitle")}</h2>'
            f'<p class="oobe-section-hint">{lang.t("Gui.OOBE.ServerHint")}</p>'
        )
        self._render_package_choices()
        pin_on_change("oobe_package_select", onchange=lambda package: self._on_package_changed(package))
        self._render_server_name_choices()
        put_html(
            f'<span class="oobe-selected-badge">'
            f'{lang.t("Gui.OOBE.ServerTitle")}: {self._package_label(self.package_name)}'
            f'</span>'
        )
        put_html('<hr class="oobe-divider">')
        self._render_footer(on_next=lambda _: self._collect_server_and_go(1))

    def _render_package_choices(self):
        put_select(
            name="oobe_package_select",
            label=lang.t("Emulator.PackageName.name"),
            options=self._package_options(),
            value=self.package_name,
        )
        put_html('<div style="height:12px"></div>')

    def _render_server_name_choices(self):
        items = self._server_name_items_for_region(self.server)
        if not items:
            items = [("disabled", lang.t("Emulator.ServerName.disabled"), "")]
        valid_values = {value for value, _, _ in items}
        value = self.server_name if self.server_name in valid_values else items[0][0]
        put_select(
            name="oobe_server_name_select",
            label=lang.t("Emulator.ServerName.name"),
            options=[
                {"label": title if not subtitle else f"{title} ({subtitle})", "value": value}
                for value, title, subtitle in items
            ],
            value=value,
        )

    def _collect_server_and_go(self, direction):
        package = pin.oobe_package_select or self.package_name
        self.package_name = package
        self.server = to_server(package)
        server_name = pin.oobe_server_name_select or self.server_name
        valid_server_names = {value for value, _, _ in self._server_name_items_for_region(self.server)}
        self.server_name = server_name if server_name in valid_server_names else self._default_server_name_for_region(self.server)
        if direction > 0:
            self._next_step()
        else:
            self._prev_step()

    def _on_package_changed(self, package):
        if not package or package == self.package_name:
            return
        self.package_name = package
        self.server = to_server(package)
        self.server_name = self._default_server_name_for_region(self.server)
        self._render()

    def _package_label(self, package):
        labels = {
            "com.bilibili.azurlane": lang.t("Gui.OOBE.ServerCN"),
            "com.YoStarEN.AzurLane": lang.t("Gui.OOBE.ServerEN"),
            "com.YoStarJP.AzurLane": lang.t("Gui.OOBE.ServerJP"),
            "com.hkmanjuu.azurlane.gp": lang.t("Gui.OOBE.ServerTW"),
        }
        if package in labels:
            return labels[package]
        if package in VALID_CHANNEL_PACKAGE:
            server, channel = VALID_CHANNEL_PACKAGE[package]
            return f"{server.upper()} {channel}"
        return package

    def _package_options(self):
        options = [
            {"label": f'{lang.t("Gui.OOBE.ServerCN")} (com.bilibili.azurlane)', "value": "com.bilibili.azurlane"},
            {"label": f'{lang.t("Gui.OOBE.ServerEN")} (com.YoStarEN.AzurLane)', "value": "com.YoStarEN.AzurLane"},
            {"label": f'{lang.t("Gui.OOBE.ServerJP")} (com.YoStarJP.AzurLane)', "value": "com.YoStarJP.AzurLane"},
            {"label": f'{lang.t("Gui.OOBE.ServerTW")} (com.hkmanjuu.azurlane.gp)', "value": "com.hkmanjuu.azurlane.gp"},
        ]
        options.extend(
            {
                "label": f"{self._package_label(pkg)} ({pkg})",
                "value": pkg,
            }
            for pkg in VALID_CHANNEL_PACKAGE
        )
        return options

    @staticmethod
    def _server_prefixes_for_region(region):
        return {
            "cn": ("cn_android", "cn_ios", "cn_channel"),
            "en": ("en",),
            "jp": ("jp",),
            "tw": (),
        }.get(region, ())

    def _server_name_items_for_region(self, region):
        items = []
        for prefix in self._server_prefixes_for_region(region):
            for index, name in enumerate(VALID_SERVER_LIST.get(prefix, [])):
                value = f"{prefix}-{index}"
                label_prefix = "国服" if prefix.startswith("cn") else prefix.upper()
                items.append((value, f"[{label_prefix}] {name}", value))
        if region == "tw":
            items.append(("disabled", lang.t("Emulator.ServerName.disabled"), "TW"))
        return items

    def _default_server_name_for_region(self, region):
        items = self._server_name_items_for_region(region)
        return items[0][0] if items else "disabled"

    @staticmethod
    def _package_for_server(server):
        for pkg, srv in VALID_PACKAGE.items():
            if srv == server:
                return pkg
        return "com.bilibili.azurlane"

    # ─── 步骤 3：模拟器配置 ───

    def _step_emulator(self):
        put_html(
            f'<h2 class="oobe-section-title">{lang.t("Gui.OOBE.EmulatorTitle")}</h2>'
            f'<p class="oobe-section-hint">{lang.t("Gui.OOBE.EmulatorHint")}</p>'
        )
        serial_options = self._serial_options()
        if self.emulator_serial == "127.0.0.1:5555":
            detected = [item["value"] for item in serial_options if item.get("detected")]
            if detected:
                self.emulator_serial = detected[0]
        put_select(
            name="oobe_serial_select",
            label=lang.t("Gui.OOBE.EmulatorSerial"),
            value=self.emulator_serial,
            options=[{k: v for k, v in item.items() if k in ("label", "value")} for item in serial_options],
        )
        pin_on_change(
            "oobe_serial_select",
            onchange=lambda serial: self._on_emulator_serial_changed(serial),
        )
        put_html('<div style="height:12px"></div>')
        put_input(
            name="oobe_package",
            label=lang.t("Gui.OOBE.EmulatorPackage"),
            value=self.package_name,
        )
        put_html('<hr class="oobe-divider">')
        self._render_footer(
            on_next=lambda _: self._collect_emulator_and_go(1),
            on_back=lambda _: self._collect_emulator_and_go(-1),
        )

    def _collect_emulator_and_go(self, direction):
        self._sync_emulator_pin_values()
        if not self.emulator_serial:
            self.emulator_serial = "auto"
        self.emulator_serial = str(self.emulator_serial)
        self.package_name = pin.oobe_package or self.package_name
        if direction > 0:
            self._next_step()
        else:
            self._prev_step()

    def _on_emulator_serial_changed(self, serial):
        if serial:
            self.emulator_serial = str(serial)

    def _sync_emulator_pin_values(self):
        try:
            serial = pin.oobe_serial_select
        except Exception:
            serial = None
        if serial:
            self.emulator_serial = str(serial)
        try:
            package = pin.oobe_package
        except Exception:
            package = None
        if package:
            self.package_name = package

    def _serial_options(self):
        detected = self._detect_adb_devices()
        options = []
        seen = set()

        def add(value, label, detected_device=False):
            if value in seen:
                return
            seen.add(value)
            options.append({"label": label, "value": value, "detected": detected_device})

        for serial in detected:
            add(serial, f"已检测到 / Detected: {serial}", True)

        add("auto", "自动检测 / Auto")
        common = [
            ("127.0.0.1:5555", "BlueStacks / 雷电"),
            ("127.0.0.1:62001", "Nox / 夜神"),
            ("127.0.0.1:59865", "Nox 64-bit / 夜神64位"),
            ("127.0.0.1:7555", "MuMu / MuMu X"),
            ("127.0.0.1:16384", "MuMu 12 / MuMu Pro"),
            ("127.0.0.1:21503", "MEmu / 逍遥"),
            ("emulator-5554", "Android Emulator / 雷电"),
            ("wsa-0", "Windows Subsystem for Android"),
        ]
        for serial, name in common:
            add(serial, f"{name} ({serial})")

        if self.emulator_serial and self.emulator_serial not in seen:
            add(self.emulator_serial, f"当前值 / Current: {self.emulator_serial}")
        return options

    @staticmethod
    def _detect_adb_devices():
        adb = getattr(State.deploy_config, "AdbExecutable", None) or "adb"
        candidates = [adb]
        if adb != "adb" and not os.path.isabs(adb):
            candidates.insert(0, os.path.abspath(adb))
        if adb != "adb":
            candidates.append("adb")

        for executable in candidates:
            try:
                result = subprocess.run(
                    [executable, "devices"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                continue
            if result.returncode != 0:
                continue
            devices = []
            for line in result.stdout.splitlines()[1:]:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    devices.append(parts[0])
            return devices
        return []

    # ─── 步骤 4：确认配置 ───

    def _step_review(self):
        put_html(
            f'<h2 class="oobe-section-title">{lang.t("Gui.OOBE.ReviewTitle")}</h2>'
            f'<p class="oobe-section-hint">{lang.t("Gui.OOBE.ReviewHint")}</p>'
        )
        server_display = {"cn": "CN", "en": "EN", "jp": "JP", "tw": "TW"}.get(self.server, self.server)
        items = [
            (lang.t("Gui.OOBE.ReviewConfigName"), self.config_name),
            (lang.t("Gui.OOBE.ReviewLanguage"), lang.LANG),
            (lang.t("Gui.OOBE.ReviewServer"), server_display),
            (lang.t("Gui.OOBE.ReviewSerial"), self.emulator_serial),
            (lang.t("Gui.OOBE.ReviewPackage"), self.package_name),
            (lang.t("Emulator.ServerName.name"), self.server_name),
        ]
        rows = "".join(
            f"<tr><td>{k}</td><td>{v}</td></tr>"
            for k, v in items
        )
        put_html(f'<table class="oobe-review-table">{rows}</table>')
        put_html('<hr class="oobe-divider">')
        self._render_footer(
            next_label=lang.t("Gui.OOBE.ButtonCreate"),
            next_color="success",
            on_next=lambda _: self._create_config_and_finish(),
        )

    # ─── 创建配置 ───

    def _create_config_and_finish(self):
        try:
            self._sync_emulator_pin_values()
            config = load_config("template")
            data = config.read_file("template")
            deep_set(data, "Alas.Emulator.Serial", self.emulator_serial)
            deep_set(data, "Alas.Emulator.PackageName", self.package_name)
            deep_set(data, "Alas.Emulator.ServerName", self.server_name)
            deep_set(data, "Alas.Emulator.ScreenshotMethod", self.screenshot_method)
            State.config_updater.write_file(self.config_name, data)
        except Exception as e:
            from pywebio.output import put_error
            with use_scope("oobe_content"):
                put_error(f"Failed to create config: {e}")
            return

        run_js("window.location.reload();")
