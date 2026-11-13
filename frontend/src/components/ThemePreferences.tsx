/**
 * @fileoverview 外观偏好区块：简约主题的配色模式选择，直接读写主题存储。
 */

import { useSyncExternalStore } from 'react'
import { useApp } from '../app/context'
import { colorModes, type ColorMode } from '../app/palettes'
import { applyTheme, getThemePreference, subscribeTheme } from '../app/theme'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../pages/settings-ui/select'
import { Field, FieldDescription, FieldLabel } from '../pages/settings-ui/field'

const modeLabels = {
  auto: 'settings.modeAuto',
  light: 'settings.themeLight',
  dark: 'settings.themeDark',
  terminal: 'settings.modeTerminal',
  'retro-gray': 'settings.modeRetroGray',
  'retro-blue': 'settings.modeRetroBlue',
  'retro-red': 'settings.modeRetroRed',
} as const

/** 外观偏好设置块：配色模式下拉，改动经 applyTheme 立即生效，不走表单暂存。 */
export function ThemePreferences() {
  const {ui} = useApp()
  const {colorMode} = useSyncExternalStore(subscribeTheme, getThemePreference, getThemePreference)
  return <Field orientation="vertical">
    <FieldLabel htmlFor="ui-color-mode">{ui('settings.colorMode')}</FieldLabel>
    <Select value={colorMode} onValueChange={next => applyTheme({...getThemePreference(), colorMode: next as ColorMode})}>
      <SelectTrigger id="ui-color-mode" aria-label={ui('settings.colorMode')} className="w-full max-w-64">
        <SelectValue/>
      </SelectTrigger>
      <SelectContent>
        {colorModes.map(mode => <SelectItem key={mode} value={mode}>{ui(modeLabels[mode])}</SelectItem>)}
      </SelectContent>
    </Select>
    <FieldDescription>{ui('settings.colorModeHelp')}</FieldDescription>
  </Field>
}
