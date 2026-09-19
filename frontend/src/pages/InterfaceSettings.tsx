import { Select } from '../components/FormControls'
import { languages, useApp, useConnection } from '../app/context'
import { PageTitle } from '../components/ui'
import { ThemePreferences } from '../components/ThemePreferences'
import { BackgroundPreferences } from '../components/BackgroundPreferences'

/** 界面设置：主题、配色、背景与语言，只影响当前浏览器，不写进实例配置。 */
export function InterfaceSettings() {
  const {theme, setTheme, language, setLanguage, ui} = useApp()
  const connection = useConnection()

  return (
    <>
      <PageTitle title={ui('nav.interface')} />
      <section className="panel config-group">
        <div className="field-row">
          <div className="field-label">
            <label htmlFor="ui-theme">{ui('settings.theme')}</label>
          </div>
          <div className="field-control">
            <Select id="ui-theme" value={theme} onChange={event => setTheme(event.target.value as typeof theme)}>
              <option value="light">{ui('settings.themeLight')}</option>
              <option value="dark">{ui('settings.themeDark')}</option>
              <option value="minimal">{ui('settings.themeMinimal')}</option>
              <option value="extreme">{ui('settings.themeExtreme')}</option>
            </Select>
          </div>
        </div>
        {(theme === 'minimal' || theme === 'extreme') && <ThemePreferences/>}
        {(theme === 'light' || theme === 'dark') && <BackgroundPreferences/>}
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
