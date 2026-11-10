/**
 * @fileoverview 基础表单控件封装（密码输入框、复选框与数值步进器等）。
 */

import { useEffect, useRef, useState, type ChangeEvent, type ComponentProps } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { useApp } from '../app/context'
import { Checkbox as ShadcnCheckbox } from './ui/checkbox'
import { Input } from './ui/input'

export { Select } from './Select'

/** 勾选框交给组件库：勾、焦点环、禁用态与键盘语义由它统一提供。 */
export function Checkbox({children, checked, disabled, id, onChange}: ComponentProps<'input'>) {
  return <label className="flex min-h-8 cursor-pointer items-center gap-2.5 text-sm has-[button:disabled]:cursor-not-allowed has-[button:disabled]:opacity-50" htmlFor={id}>
    <ShadcnCheckbox
      id={id}
      checked={!!checked}
      disabled={disabled}
      onCheckedChange={next => onChange?.({target: {checked: next}} as unknown as ChangeEvent<HTMLInputElement>)}
    />
    <span>{children}</span>
  </label>
}

/** 密码框：输入框来自组件库，右侧明码切换保持原位置。 */
export function PasswordInput(props: ComponentProps<'input'>) {
  const [visible, setVisible] = useState(false)
  const {ui} = useApp()
  return <span className="password-control">
    <Input {...props} className="pr-10" type={visible ? 'text' : 'password'}/>
    <button type="button" className="password-reveal" disabled={props.disabled} aria-label={visible ? ui('common.hidePassword') : ui('common.showPassword')} aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={16} aria-hidden="true"/> : <Eye size={16} aria-hidden="true"/>}</button>
  </span>
}

/** 输入草稿：键入期间只改本地值，失焦或回车才提交；提交后外部值没跟着变，输入框回到外部值。 */
export function useDraftInput(value: string, commit: (draft: string) => void, resubmitOnEdit = false) {
  const [draft, setDraft] = useState(value)
  const [editing, setEditing] = useState(false)
  const edited = useRef(false)
  useEffect(() => { if (!editing) setDraft(value) }, [value, editing])
  return {
    value: draft,
    onFocus: () => {edited.current = false; setEditing(true)},
    onChange: (event: {target: {value: string}}) => {edited.current = true; setDraft(event.target.value)},
    onBlur: () => {
      const submit = draft !== value || (resubmitOnEdit && edited.current)
      edited.current = false
      setEditing(false)
      if (submit) commit(draft)
    },
    onKeyDown: (event: {key: string; currentTarget: {blur: () => void}}) => {if (event.key === 'Enter') event.currentTarget.blur()},
  }
}

/** 数字输入：在草稿基础上把提交值收敛成不小于 min 的整数。 */
export function NumberDraftInput({value, label, min = 0, onCommit}: {value: number, label: string, min?: number, onCommit: (value: number) => void}) {
  const draft = useDraftInput(String(value), text => {
    const parsed = Number(text)
    if (Number.isFinite(parsed) && parsed >= min) onCommit(Math.floor(parsed))
  })
  return <input type="number" min={min} aria-label={label} title={label} {...draft}/>
}
