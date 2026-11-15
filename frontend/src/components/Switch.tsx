/**
 * @fileoverview 开关控件：由 shadcn/ui 的 Switch 承载。
 *
 * 轨道、滑块、按压反馈、焦点环与禁用态都由组件提供；
 * 轨道颜色取主题强调色，与下拉框、勾选框同一支颜色。
 */

import { Switch as ShadcnSwitch } from './ui/switch'

/**
 * 表单开关的薄封装：不渲染任何可见文字，label/invalid/describedBy 全部走 aria 属性，
 * 视觉态（轨道色、焦点环、禁用）交给 shadcn/ui 的 Switch。
 */
export function Switch({id, checked, disabled, label, title, invalid, describedBy, onChange}: {
  id?: string
  checked: boolean
  disabled?: boolean
  label?: string
  title?: string
  invalid?: boolean
  describedBy?: string
  onChange: (checked: boolean) => void
}) {
  return <ShadcnSwitch
    id={id}
    checked={checked}
    disabled={disabled}
    aria-label={label}
    aria-invalid={invalid || undefined}
    aria-describedby={describedBy}
    title={title}
    onCheckedChange={onChange}
  />
}
