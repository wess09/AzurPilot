/**
 * @fileoverview 界面外观偏好设置页面（主题、配色、背景与多语言）。
 */

import { Select } from '../components/FormControls'
import { languages, useApp, useConnection } from '../app/context'
import { PageTitle } from '../components/ui'
import { SegmentedControl } from '../components/SegmentedControl'
import { ThemeCustomPreference } from '../components/ThemeCustomPreference'
import { ThemePreferences } from '../components/ThemePreferences'
import { BackgroundPreferences } from '../components/BackgroundPreferences'

/** 界面设置：主题、材质、明暗、配色、背景与语言，只影响当前浏览器，不写进实例配置。 */
export function InterfaceSettings() {
  const {theme, setTheme, material, setMaterial, resolvedMode, language, setLanguage, ui} = useApp()
  const connection = useConnection()
  const minimal = theme === 'minimal'

  return (
    <>
      <PageTitle title={ui('nav.interface')} />
      <section className="panel config-group">
        <div className="field-row">
          <div className="field-label">
            <label htmlFor="ui-theme">{ui('settings.theme')}</label>
          </div>
          <div className="field-control">
            <Select id="ui-theme" value={minimal ? 'minimal' : 'legacy'} onChange={event => {
              setTheme(event.target.value === 'minimal' ? 'minimal' : resolvedMode === 'dark' ? 'legacy-dark' : 'legacy-light')
            }}>
              <option value="legacy">{ui('settings.familyLegacy')}</option>
              <option value="minimal">{ui('settings.themeMinimal')}</option>
            </Select>
          </div>
        </div>
        {minimal ? <ThemePreferences/> : <>
          <div className="field-row">
            <div className="field-label">
              <label>{ui('settings.material')}</label>
            </div>
            <div className="field-control">
              <SegmentedControl className="settings-segmented" label={ui('settings.material')} value={material} onChange={setMaterial} options={[
                {value: 'glass', label: ui('settings.materialGlass')},
                {value: 'plain', label: ui('settings.materialPlain')},
              ]}/>
            </div>
          </div>
          <div className="field-row">
            <div className="field-label">
              <label>{ui('settings.mode')}</label>
            </div>
            <div className="field-control">
              <SegmentedControl className="settings-segmented" label={ui('settings.mode')} value={resolvedMode} onChange={mode => setTheme(mode === 'dark' ? 'legacy-dark' : 'legacy-light')} options={[
                {value: 'light', label: ui('settings.themeLight')},
                {value: 'dark', label: ui('settings.themeDark')},
              ]}/>
            </div>
          </div>
          <ThemeCustomPreference/>
          <BackgroundPreferences/>
        </>}
        <div className="field-row">
          <div className="field-label">
            <label htmlFor="ui-language">{ui('settings.language')}</label>
          </div>
          <div className="field-control">
            <Select id="ui-language" value={language} disabled={connection !== 'ready'} onChange={event => setLanguage(event.target.value as typeof language)}>
              {Object.entries(languages).map(([key, label]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </Select>
          </div>
        </div>
      </section>
    </>
  )
}
