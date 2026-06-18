"""
PyWebIO Pin 交互组件的扩展封装。

基于 pywebio.pin 进行二次开发，为所有 put_xxx() 函数添加 **other_html_attrs 参数，
支持传入自定义 HTML 属性。提供针对 Alas 配置系统的各种输入控件（如下拉选择框、
数字输入及开关等）的自动化渲染与数值同步转换。
"""

from pywebio.io_ctrl import Output
from module.webui.utils import *
from pywebio.output import OutputPosition
from pywebio.pin import _pin_output, check_dom_name_value, pin_update


def put_input(name, type='text', *, label='', value=None, placeholder=None, readonly=None, datalist=None,
              help_text=None, scope=None, position=OutputPosition.BOTTOM, **other_html_attrs) -> Output:
    """输出文本输入控件。参数详见 `pywebio.input.input()`。"""
    from pywebio.input import input
    check_dom_name_value(name, 'pin `name`')
    single_input_return = input(name=name, label=label, value=value, type=type, placeholder=placeholder,
                                readonly=readonly, datalist=datalist, help_text=help_text, **other_html_attrs)
    return _pin_output(single_input_return, scope, position)


def put_textarea(name, *, label='', rows=6, code=None, maxlength=None, minlength=None, value=None, placeholder=None,
                 readonly=None, help_text=None, scope=None, position=OutputPosition.BOTTOM, **other_html_attrs) -> Output:
    """输出多行文本输入控件。参数详见 `pywebio.input.textarea()`。"""
    from pywebio.input import textarea
    check_dom_name_value(name, 'pin `name`')
    single_input_return = textarea(
        name=name, label=label, rows=rows, code=code, maxlength=maxlength,
        minlength=minlength, value=value, placeholder=placeholder, readonly=readonly, help_text=help_text, **other_html_attrs)
    return _pin_output(single_input_return, scope, position)


def put_select(name, options=None, *, label='', multiple=None, value=None, help_text=None,
               scope=None, position=OutputPosition.BOTTOM, **other_html_attrs) -> Output:
    """输出下拉选择控件。参数详见 `pywebio.input.select()`。"""
    from pywebio.input import select
    check_dom_name_value(name, 'pin `name`')
    single_input_return = select(name=name, options=options, label=label, multiple=multiple,
                                 value=value, help_text=help_text, **other_html_attrs)
    return _pin_output(single_input_return, scope, position)


def put_checkbox(name, options=None, *, label='', inline=None, value=None, help_text=None,
                 scope=None, position=OutputPosition.BOTTOM, **other_html_attrs) -> Output:
    """输出复选框控件。参数详见 `pywebio.input.checkbox()`。"""
    from pywebio.input import checkbox
    check_dom_name_value(name, 'pin `name`')
    single_input_return = checkbox(name=name, options=options, label=label, inline=inline, value=value,
                                   help_text=help_text, **other_html_attrs)
    return _pin_output(single_input_return, scope, position)