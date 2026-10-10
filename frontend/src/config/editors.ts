/**
 * @fileoverview 全局配置与部署设置编辑器单例及各类型字段草稿维护。
 */

import { api } from '../api/client'
import type { Field, Value } from '../api/types'
import { EditQueue } from './EditQueue'
import { translateCurrentUi } from '../i18n'

const prefix = 'azurpilot.edits.'
const queues = new Map<string, EditQueue>()

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

/** 数字的原始文本与提交值分离，保留负号、小数点等输入中间态。
 *  文本框、时间或数字内容被全部清空时，按旧版本逻辑自动还原为默认设置，便于后续修改。
 *  配置加载时 `config_update()` 也把空值还原成默认值。NextRun 的默认值落在过去，
 *  保存后调度器下一轮就把它当待运行任务。 */
export function prepareValue(value: Value, field: Pick<Field, 'type' | 'value' | 'validate' | 'preserve_empty'>): {payload: Value; text?: Value; error?: string} {
  const numeric = !['select', 'multiselect', 'checkbox'].includes(field.type)
    && (typeof field.value === 'number' || ['number', 'int', 'float'].includes(field.type))
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
  const integer = field.type === 'int'
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(text) || !Number.isFinite(number)) {
    return {payload: value, error: translateCurrentUi('edit.invalidNumber')}
  }
  if (integer && !Number.isSafeInteger(number)) return {payload: value, error: translateCurrentUi('edit.invalidInteger')}
  if (Number.isInteger(number) && !Number.isSafeInteger(number)) return {payload: value, error: translateCurrentUi('edit.numberOutOfRange')}
  if (Array.isArray(field.validate) && (number < field.validate[0] || number > field.validate[1])) {
    return {payload: value, error: translateCurrentUi('edit.validateRange', {min: field.validate[0], max: field.validate[1]})}
  }
  return {payload: number}
}
