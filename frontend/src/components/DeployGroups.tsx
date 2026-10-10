/**
 * @fileoverview 部署设置分组表单渲染组件。
 */

import type { Settings as SettingsData } from '../api/types'
import type { EditQueue, EditSnapshot } from '../config/EditQueue'
import { useApp } from '../app/context'
import { htmlToPlainText } from '../app/htmlText'
import { prepareValue } from '../config/editors'
import { EditStatus } from './EditStatus'
import { FieldInput } from './FieldInput'

/**
 * 渲染本页负责的部署设置分组。
 *
 * `only` 与 `except` 二选一：前者只渲染列出的分组，后者渲染除此之外的全部分组。
 * 字段控件与提交队列和实例配置一致：输入即提交，由 `EditQueue` 负责重试与草稿。
 */
export function DeployGroups({data, only, except, edits, queue}: {
  data: SettingsData
  only?: string[]
  except?: string[]
  edits: EditSnapshot
  queue: EditQueue
}) {
  const {t, ui} = useApp()
  const groups = data.groups.filter(group => only
    ? only.includes(group.key)
    : except ? !except.includes(group.key) : true)
  return <>
    {groups.map(group => (
      <section className="panel config-group" key={group.key}>
        <div className="panel-heading">
          <h2 data-text={t(`Gui.DeploySetting.Group${group.key}`)}>{t(`Gui.DeploySetting.Group${group.key}`)}</h2>
        </div>
        {group.fields.map(field => {
          const isMultiline = ['textarea', 'yaml', 'task_priority'].includes(field.type)
          return (
          <div className={`field-row ${isMultiline ? 'field-row-multiline' : ''}`} key={field.key}>
            <div className="field-label">
              <label htmlFor={`deploy-${field.key}`}>{field.label}</label>
              <p>{field.key === 'Password' ? ui('settings.passwordHelp') : htmlToPlainText(field.help)}</p>
              {/* 多行控件的提示跟标题同一行，浮在它右端。 */}
              {isMultiline && <EditStatus id={`deploy-${field.key}`} edit={edits.edits[field.key]} retry={queue.retry} queue={queue}/>}
            </div>
            <div className="field-control">
              <FieldInput
                id={`deploy-${field.key}`}
                label={field.label}
                type={field.type}
                options={field.options}
                value={edits.edits[field.key]?.value ?? field.value}
                preserveText
                invalid={edits.edits[field.key]?.status === 'error'}
                disabled={data.demo}
                onChange={value => {
                  const {payload, text, error} = prepareValue(value, field)
                  queue.change(field.key, text ?? value, payload, error)
                }}
              />
              {!isMultiline && <EditStatus id={`deploy-${field.key}`} edit={edits.edits[field.key]} retry={queue.retry} queue={queue}/>}
            </div>
          </div>
          )
        })}
      </section>
    ))}
  </>
}
