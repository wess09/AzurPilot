/**
 * @fileoverview 实例名称合法性校验正则表达式与命名规则约束。
 */

// 实例名会成为配置文件名。字符集与后端 `module/api/config_service.py` 的 NAME 一致：
// 中日文、字母、数字、下划线、点号、空格与短横线。保留名与首点号的拦截只在后端，
// 表单放行的名字若不合规，由后端报错。
// 各范围写成转义序列，避免肉眼无法分辨的兼容区字形被写错码点。
const HIRAGANA = '\u3041-\u3096'
const KATAKANA = '\u30a1-\u30fa\u30fc\u31f0-\u31ff\uff66-\uff9f'
const HAN = '\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff'
const CJK = `${HIRAGANA}${KATAKANA}${HAN}`

// 前端 pattern 属性按 v 标志原样编译，不认 `\w` 这类转义，字符类要逐段写全。
/** HTML 表单可直接使用的实例名称正则表达式。 */
export const INSTANCE_NAME_PATTERN = `[A-Za-z0-9${CJK}][A-Za-z0-9_. ${CJK}\\-]{0,63}`
