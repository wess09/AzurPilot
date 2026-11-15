/**
 * @fileoverview 配置字段错误提示组件：仅在字段处于错误态时渲染。
 */

import type { Edit } from '../config/EditQueue'
import { CircleAlert } from 'lucide-react'
import { MarqueeText } from './MarqueeText'

/**
 * 字段旁的错误提示：只显示错误本体（已保存/正在保存等过程提示已移除）。
 * 文案超宽时沿用侧栏任务名的灯带跑马灯（MarqueeText：双副本无缝循环、自动测宽）滚动展示全文；
 * 动效偏好下静止，回落省略号与 title 提示。
 *
 * @param edit 字段最近一条保存记录，非错误态不渲染。
 * @param id 用于拼装状态节点的 DOM id（`${id}-status`）：输入控件出错时以 aria-describedby 指向它。
 */
export function EditStatus({edit, id}: {edit?: Edit; id: string}) {
  if (!edit || edit.status !== 'error') return null
  return (
    <div id={`${id}-status`} className="edit-status edit-error" role="alert" title={edit.error}>
      <CircleAlert size={14} aria-hidden="true"/>
      <MarqueeText className="edit-status-text" text={edit.error ?? ''}/>
    </div>
  )
}
