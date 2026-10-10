/**
 * @fileoverview 基础表单控件封装（密码输入框、复选框与数值步进器等）。
 */

import { useEffect, useRef, useState, type ComponentProps } from 'react'
import { Check, Eye, EyeOff } from 'lucide-react'
import { useApp } from '../app/context'

export { Select } from './Select'

/** 使用真实复选框承载焦点和表单语义，图标只负责呈现。 */
export function Checkbox({children, ...props}: ComponentProps<'input'>) {
  return <label className="checkbox-control"><span className="checkbox-mark"><input {...props} type="checkbox"/><Check size={13} strokeWidth={3} aria-hidden="true"/></span><span>{children}</span></label>
}

export function PasswordInput(props: ComponentProps<'input'>) {
  const [visible, setVisible] = useState(false)
  const {ui} = useApp()
  return <span className="password-control"><input {...props} type={visible ? 'text' : 'password'}/><button type="button" className="password-reveal" disabled={props.disabled} aria-label={visible ? ui('common.hidePassword') : ui('common.showPassword')} aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={18} aria-hidden="true"/> : <Eye size={18} aria-hidden="true"/>}</button></span>
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
