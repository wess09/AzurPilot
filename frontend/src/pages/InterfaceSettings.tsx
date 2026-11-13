/**
 * @fileoverview 界面外观偏好设置页面（主题、配色、背景与多语言）。
 *
 * 版式与任务设置页一致：每组一张 `.panel.config-group` 玻璃卡，卡内是
 * `.field-row`（标签在左、控件在右侧固定列）与 `.panel-heading` 分组标题。
 */

import { useSyncExternalStore } from 'react'
import { Select } from '../components/FormControls'
import { Switch } from '../components/Switch'
import { useApp, useConnection, languages } from '../app/context'
import { ThemePreferences } from '../components/ThemePreferences'
import { BackgroundPreferences } from '../components/BackgroundPreferences'
import { readSchedulerPosition, setSchedulerPosition, subscribeSchedulerPosition } from '../app/schedulerPositionPrefs'
import { readRailVisible, setRailVisible, subscribeRailVisible } from '../app/railPrefs'

/** 设置分组卡：标题占面板首行，正文由调用方给出的 `.field-row` 组成。 */
function SettingsGroup({title, children}: {title: string; children: React.ReactNode}) {
  return <section className="panel config-group">
    <div className="panel-heading">
      <div>
        <span className="group-indicator"/>
        <h2 role="heading" aria-level={2}>{title}</h2>
      </div>
    </div>
    {children}
  </section>
}

/** 界面设置：主题、调度器位置、材质、明暗、配色、背景与语言，只影响当前浏览器，不写进实例配置。 */
export function InterfaceSettings() {
  const {theme, setTheme, material, setMaterial, resolvedMode, language, setLanguage, ui} = useApp()
  const schedulerPosition = useSyncExternalStore(subscribeSchedulerPosition, readSchedulerPosition, readSchedulerPosition)
  const railVisibility = useSyncExternalStore(subscribeRailVisible, readRailVisible, readRailVisible)
  const connection = useConnection()
  const minimal = theme === 'minimal'

  return <>
    <h1 className="legacy-sr-title">{ui('nav.interface')}</h1>
    <div className="settings-page">
      <SettingsGroup title={ui('settings.theme')}>
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
              <label htmlFor="ui-material">{ui('settings.material')}</label>
            </div>
            <div className="field-control">
              <Select id="ui-material" value={material} onChange={event => setMaterial(event.target.value as typeof material)}>
                <option value="glass">{ui('settings.materialGlass')}</option>
                <option value="plain">{ui('settings.materialPlain')}</option>
              </Select>
            </div>
          </div>
          <div className="field-row">
            <div className="field-label">
              <label htmlFor="ui-mode">{ui('settings.mode')}</label>
            </div>
            <div className="field-control">
              <Select id="ui-mode" value={resolvedMode} onChange={event => setTheme(event.target.value === 'dark' ? 'legacy-dark' : 'legacy-light')}>
                <option value="light">{ui('settings.themeLight')}</option>
                <option value="dark">{ui('settings.themeDark')}</option>
              </Select>
            </div>
          </div>
        </>}
      </SettingsGroup>

      <SettingsGroup title={ui('settings.schedulerPosition')}>
        <div className="field-row">
          <div className="field-label">
            <label>{ui('settings.schedulerPosition')}</label>
            <p>{ui('settings.schedulerPositionHelp')}</p>
          </div>
          <div className="field-control">
            <Select id="ui-scheduler-position" value={schedulerPosition} onChange={event => setSchedulerPosition(event.target.value as typeof schedulerPosition)}>
              <option value="left">{ui('settings.schedulerPositionLeft')}</option>
              <option value="right">{ui('settings.schedulerPositionRight')}</option>
            </Select>
          </div>
        </div>
        <div className="field-row">
          <div className="field-label">
            <label htmlFor="ui-rail-visible">{ui('settings.showSchedulerRail')}</label>
            <p>{ui('settings.showSchedulerRailHelp')}</p>
          </div>
          <div className="field-control">
            <Switch id="ui-rail-visible" label={ui('settings.showSchedulerRail')} checked={railVisibility === 'shown'} onChange={checked => setRailVisible(checked ? 'shown' : 'hidden')}/>
          </div>
        </div>
      </SettingsGroup>

      {!minimal && <SettingsGroup title={ui('settings.background')}>
        <BackgroundPreferences/>
      </SettingsGroup>}

      <SettingsGroup title={ui('settings.language')}>
        <div className="field-row">
          <div className="field-label">
            <label htmlFor="ui-language">{ui('settings.language')}</label>
          </div>
          <div className="field-control">
            <Select id="ui-language" value={language} disabled={connection !== 'ready'} onChange={event => setLanguage(event.target.value as typeof language)}>
              {Object.entries(languages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </Select>
          </div>
        </div>
      </SettingsGroup>
    </div>
  </>
}
