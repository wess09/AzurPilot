/**
 * @fileoverview 外观偏好区块：配色模式选择与调色板挑选，直接读写主题存储。
 */

import { useSyncExternalStore } from 'react'
import { useApp } from '../app/context'
import { colorModes, fixedColorModes, type ColorMode } from '../app/palettes'
import { applyTheme, getThemePreference, subscribeTheme } from '../app/theme'
import { Select } from './FormControls'
import { PaletteSwatches } from './PaletteSwatches'

const modeLabels = {
  auto: 'settings.modeAuto',
  light: 'settings.themeLight',
  dark: 'settings.themeDark',
  terminal: 'settings.modeTerminal',
  'retro-gray': 'settings.modeRetroGray',
  'retro-blue': 'settings.modeRetroBlue',
  'retro-red': 'settings.modeRetroRed',
} as const

/** 外观偏好设置块：配色模式下拉与调色板色卡，改动经 applyTheme 立即生效，不走表单暂存。 */
export function ThemePreferences() {
  const {ui} = useApp()
  const {colorMode, palette} = useSyncExternalStore(subscribeTheme, getThemePreference, getThemePreference)
  return <>
    <div className="field-row">
      <div className="field-label"><label htmlFor="ui-color-mode">{ui('settings.colorMode')}</label><p>{ui('settings.colorModeHelp')}</p></div>
      <div className="field-control">
        <Select id="ui-color-mode" value={colorMode} onChange={event => applyTheme({...getThemePreference(), colorMode: event.target.value as ColorMode})}>
          {colorModes.map(mode => <option key={mode} value={mode}>{ui(modeLabels[mode])}</option>)}
        </Select>
      </div>
    </div>
    {/* 固定主题模式自带整套色值与明暗，优先于所选调色板，藏起选择器 */}
    {!fixedColorModes[colorMode] && <div className="field-row palette-field">
      <div className="field-label"><label>{ui('settings.palette')}</label><p>{ui('settings.paletteHelp')}</p></div>
      <div className="field-control palette-control">
        <PaletteSwatches value={palette} onChange={next => {if (next) applyTheme({...getThemePreference(), palette: next})}} legend={ui('settings.palette')}/>
      </div>
    </div>}
  </>
}
