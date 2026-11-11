import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import type { Value } from '../api/types'
import { useApp } from '../app/context'
import { useDraftInput } from '../components/FormControls'
import { Button } from './settings-ui/button'
import { Input } from './settings-ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './settings-ui/select'
import { Switch } from './settings-ui/switch'

export function SettingsField({id, label, type, value, options, disabled, invalid, descriptionId, onChange}: {
  id: string
  label: string
  type: string
  value: Value
  options?: Value[]
  disabled: boolean
  invalid: boolean
  descriptionId?: string
  onChange: (value: Value) => void
}) {
  const {ui} = useApp()
  const [visible, setVisible] = useState(false)
  const draft = useDraftInput(value === null ? '' : String(value), onChange)
  const accessibility = {
    id,
    'aria-label': label,
    'aria-invalid': invalid || undefined,
    'aria-describedby': [descriptionId, invalid ? `${id}-status` : undefined].filter(Boolean).join(' ') || undefined,
    disabled,
  }

  if (type === 'bool' || type === 'checkbox' || typeof value === 'boolean') {
    return <Switch {...accessibility} checked={!!value} onCheckedChange={onChange}/>
  }

  if (options?.length) {
    const selected = JSON.stringify(value)
    const choices = options.some(option => option === value) ? options : [value, ...options]
    return <Select value={selected} disabled={disabled} onValueChange={next => onChange(JSON.parse(next) as Value)}>
      <SelectTrigger {...accessibility}>
        <SelectValue placeholder={ui('common.select')}/>
      </SelectTrigger>
      <SelectContent>
        {choices.map(option => <SelectItem key={JSON.stringify(option)} value={JSON.stringify(option)}>
          {String(option ?? ui('common.notSet'))}
        </SelectItem>)}
      </SelectContent>
    </Select>
  }

  const isNumber = typeof value === 'number' || ['int', 'number', 'float'].includes(type)
  return <>
    <Input {...accessibility} {...draft} type={type === 'password' && !visible ? 'password' : 'text'}
      inputMode={isNumber ? 'decimal' : undefined} autoComplete={type === 'password' ? 'new-password' : 'off'}/>
    {type === 'password' && <Button type="button" variant="outline" size="icon" disabled={disabled}
      aria-label={visible ? ui('common.hidePassword') : ui('common.showPassword')}
      aria-pressed={visible} onClick={() => setVisible(!visible)}>
      {visible ? <EyeOff/> : <Eye/>}
    </Button>}
  </>
}
