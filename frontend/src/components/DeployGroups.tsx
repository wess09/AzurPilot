/**
 * @fileoverview 部署设置分组表单渲染组件。
 *
 * 版式与任务设置页一致：每组一张 `.panel.config-group` 卡片，字段是
 * `.field-row`（标签与说明在左、控件在右侧固定列），不再另造卡片结构。
 */

import type { Settings as SettingsData } from '../api/types'
import type { EditQueue, EditSnapshot } from '../config/EditQueue'
import { useApp } from '../app/context'
import { htmlToPlainText } from '../app/htmlText'
import { prepareValue } from '../config/editors'
import { SettingsField } from '../pages/SettingsField'
import { EditStatus } from './EditStatus'

/**
 * 渲染本页负责的部署设置分组。
 *
 * `only` 只渲染列出的分组，不传则渲染全部分组。
 * 字段控件与提交队列和实例配置一致：输入即提交，由 `EditQueue` 负责重试与草稿。
 */
export function DeployGroups({data, only, edits, queue}: {
  data: SettingsData
  only?: string[]
  edits: EditSnapshot
  queue: EditQueue
}) {
  const {t, ui} = useApp()
  const groups = data.groups.filter(group => only
    ? only.includes(group.key)
    : true)
  return <>
    {groups.map(group => (
      <section className="panel config-group" key={group.key}>
        <div className="panel-heading">
          <div>
            <span className="group-indicator"/>
            <h2 role="heading" aria-level={2}>{t(`Gui.DeploySetting.Group${group.key}`)}</h2>
          </div>
        </div>
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
      </section>
    ))}
  </>
}
