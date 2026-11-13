/**
 * @fileoverview 基础表单控件封装（密码输入框、复选框等）。
 */

import { useEffect, useId, useRef, useState, type ChangeEvent, type ComponentProps } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { useApp } from '../app/context'
import { Checkbox as ShadcnCheckbox } from './ui/checkbox'
import { Input } from './ui/input'
import { Label } from './ui/label'

export { Select } from './Select'

/** 勾选框交给组件库：勾、焦点环、禁用态与键盘语义由它统一提供。 */
export function Checkbox({children, checked, disabled, onChange}: ComponentProps<'input'>) {
  const generated = useId()
  return <span className="flex items-center gap-3">
    <ShadcnCheckbox
      id={generated}
      checked={!!checked}
      disabled={disabled}
      // 组件库只回布尔值：包成 input 的 ChangeEvent 形状，让调用方沿用 onChange 契约。
      onCheckedChange={next => onChange?.({target: {checked: next}} as unknown as ChangeEvent<HTMLInputElement>)}
    />
    <Label htmlFor={generated}>{children}</Label>
  </span>
}

/** 密码框：输入框来自组件库，右侧明码切换保持原位置。 */
export function PasswordInput(props: ComponentProps<'input'>) {
  const [visible, setVisible] = useState(false)
  const {ui} = useApp()
  return <div className="relative">
    <Input {...props} className="pr-10" type={visible ? 'text' : 'password'}/>
    <button
      type="button"
      className="absolute inset-y-0 right-0 grid w-10 place-items-center text-muted-foreground hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
      disabled={props.disabled}
      aria-label={visible ? ui('common.hidePassword') : ui('common.showPassword')}
      aria-pressed={visible}
      onClick={() => setVisible(!visible)}
    >{visible ? <EyeOff size={16} aria-hidden="true"/> : <Eye size={16} aria-hidden="true"/>}</button>
  </div>
}

/**
 * 输入草稿：键入期间只改本地值，失焦或回车才提交；提交后外部值没跟着变，输入框回到外部值。
 * @param resubmitOnEdit 编辑过就提交，即使草稿与外部值相同。
 */
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
