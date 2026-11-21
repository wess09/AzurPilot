/**
 * @fileoverview 全局系统部署设置页面。
 *
 * 版式与任务设置页一致：每组一张 `.panel.config-group` 卡片，字段是
 * `.field-row`（标签与说明在左、控件在右侧固定列）。
 */

import {LoadBoundary} from '../components/ui/load-boundary'


import { AlertCircle } from 'lucide-react'
import { PageTitle, Panel, PanelHeading } from '../components/ui'
import { useApp } from '../app/context'
import { Alert, AlertDescription } from '../components/ui/alert'
import { EditStatus } from '../components/EditStatus'
import { LauncherCard } from '../components/LauncherCard'
import { htmlToPlainText } from '../app/htmlText'
import { useDeploySettings } from '../app/useDeploySettings'
import { REMOTE_ACCESS_GROUPS } from '../app/settingsGroups'
import { prepareValue } from '../config/editors'
import { SettingsField } from './SettingsField'

/** 系统级部署设置与启动器设置；外观偏好在「界面设置」，远程访问与 WebUI 在「远程访问」。 */
export function Settings() {
  const {data, error, reload, edits, queue} = useDeploySettings()
  const {t, ui} = useApp()

  return <>
    <PageTitle title={ui('nav.settings')} placement="screen-reader"/>
    <div className="settings-page">
      {edits.storageError && <Alert variant="destructive"><AlertCircle/><AlertDescription>{edits.storageError}</AlertDescription></Alert>}
      <LauncherCard/>
      <LoadBoundary ready={!!data} error={error} retry={reload}>{data && (
        data.groups.filter(group => !REMOTE_ACCESS_GROUPS.includes(group.key)).map(group => (
          <Panel compact key={group.key}>
            <PanelHeading title={t(`Gui.DeploySetting.Group${group.key}`)} icon={<span className="group-indicator"/>}/>
            {group.fields.map(field => {
              const id = `deploy-${field.key}`
              const current = edits.edits[field.key]?.value ?? field.value
              const invalid = edits.edits[field.key]?.status === 'error'
              const descriptionId = `${id}-description`
              return <div className="field-row" key={field.key}>
                <div className="field-label">
                  <label htmlFor={id}>{field.label}</label>
                  <p id={descriptionId}>{field.key === 'Password' ? ui('settings.passwordHelp') : htmlToPlainText(field.help)}</p>
                </div>
                <div className="field-control">
                  <SettingsField
                    id={id}
                    label={field.label}
                    type={field.type}
                    options={field.options}
                    value={current}
                    invalid={invalid}
                    disabled={data.demo}
                    descriptionId={descriptionId}
                    onChange={value => {
                      const {payload, text, error} = prepareValue(value, field)
                      queue.change(field.key, text ?? value, payload, error)
                    }}
                  />
                  <EditStatus id={id} edit={edits.edits[field.key]}/>
                </div>
              </div>
            })}
          </Panel>
        ))
      )}</LoadBoundary>
    </div>
  </>
}
