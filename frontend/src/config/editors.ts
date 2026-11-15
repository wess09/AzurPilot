/**
 * @fileoverview 全局配置与部署设置编辑器单例及各类型字段草稿维护。
 */

import { api } from '../api/client'
import type { Field, Value } from '../api/types'
import { EditQueue } from './EditQueue'
import { translateCurrentUi } from '../i18n'

const prefix = 'azurpilot.edits.'
const queues = new Map<string, EditQueue>()

/**
 * 取某个作用域的字段编辑队列（同作用域复用同一实例）。
 *
 * 作用域是 `deploy`、`config:<实例>` 或 `startup:<实例>`，决定提交走哪个后端接口。
 * 草稿落在 sessionStorage，刷新后由 resumeEditors 恢复；浏览器禁用存储时退化为纯内存队列。
 */
export function editor(scope: string) {
  let queue = queues.get(scope)
  if (queue) return queue
  let storage: Storage | undefined
  try { storage = window.sessionStorage } catch { /* 队列仍在内存中工作，并显示持久化失败。 */ }
  queue = new EditQueue(prefix + scope, {
    ready: () => api.getSnapshot() === 'ready',
    send: (path, value) => scope === 'deploy'
      ? api.request('settings.patch', {values: {[path]: value}})
      : scope.startsWith('startup:')
        ? api.request('startup.set', path === 'remember'
          ? {instance: scope.slice(8), remember: value as boolean}
          : {instance: scope.slice(8), enabled: value as boolean})
        : api.request('config.patch', {instance: scope.slice(7), changes: [{path, value}]}),
  }, storage)
  queues.set(scope, queue)
  return queue
}

/** 重连和整页刷新后，恢复所有实例的未完成提交，不依赖当前显示哪个页面。 */
export function resumeEditors() {
  try {
    for (const key of Object.keys(window.sessionStorage)) {
      if (key.startsWith(prefix)) editor(key.slice(prefix.length))
    }
  } catch { /* 浏览器禁用存储时仍重试内存队列。 */ }
  for (const queue of queues.values()) queue.retry()
}

/**
 * 规范化配置字段的草稿值与提交值。
 *
 * 数字的原始文本与提交值分离，清空值时按旧版规则回落默认值。
 * @param value 用户输入值。
 * @param field 字段类型、默认值、数值类型与校验范围。
 * @returns 提交值、可回填的默认文本及校验错误。
 */
export function prepareValue(value: Value, field: Pick<Field, 'type' | 'value' | 'valuetype' | 'validate' | 'preserve_empty'>): {payload: Value; text?: Value; error?: string} {
  const valueType = field.valuetype ?? field.type
  const numeric = valueType !== 'str' && !['select', 'multiselect', 'checkbox'].includes(field.type)
    && (typeof field.value === 'number' || ['number', 'int', 'float'].includes(valueType))
  // preserve_empty 表示空值本身有意义，这类字段照旧提交空值，不做回落。
  // 旧版本逻辑：当文本框/数字/时间等内容被全部清空时，自动还原为默认设置，便于后续修改。
  if (!field.preserve_empty && String(value).trim() === '') {
    const fallback = field.value
    if (fallback !== null && fallback !== undefined && String(fallback) !== '') {
      return {payload: fallback, text: String(fallback)}
    }
  }
  if (!numeric) return {payload: value}
  const text = String(value).trim()
  const number = Number(text)
  // JSON 无法区分默认值 1 与 1.0；任务字段的精确整数类型交给后端校验。
  const integer = valueType === 'int'
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text) || !Number.isFinite(number)) {
    return {payload: value, error: translateCurrentUi('edit.invalidNumber')}
  }
  if (integer && !Number.isSafeInteger(number)) return {payload: value, error: translateCurrentUi('edit.invalidInteger')}
  if (Number.isInteger(number) && !Number.isSafeInteger(number)) return {payload: value, error: translateCurrentUi('edit.numberOutOfRange')}
  const range = Array.isArray(field.validate) ? [field.validate[0], field.validate[1]] : []
  const [minimum, maximum] = range
  if (minimum !== undefined && maximum !== undefined && (number < minimum || number > maximum)) {
    return {payload: value, error: translateCurrentUi('edit.validateRange', {min: minimum, max: maximum})}
  }
  return {payload: number}
}
