/**
 * @fileoverview 配置字段可见性判断辅助逻辑。
 */

import type { Field, Value } from '../api/types'

/**
 * 判断配置字段是否参与渲染：`_info` 组与显式 hide 的字段一律不出现。
 *
 * @param argument 字段所属的参数组名，`_info` 组不渲染任何字段。
 */
export function isFieldVisible(argument: string, field: Field, value: Value) {
  if (argument === '_info' || field.display === 'hide') return false
  // 沿用旧版 put_arg_storage：空字典不生成字段，也不生成空分组或导航。
  if (field.type === 'storage' && value !== null && typeof value === 'object' && !Array.isArray(value) && !Object.keys(value).length) return false
  return true
}
