/**
 * @fileoverview 全局系统部署设置页面。
 */

import { AlertCircle } from 'lucide-react'
import { useApp } from '../app/context'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Alert, AlertDescription } from '../components/ui/alert'
import { Badge } from '../components/ui/badge'
import { Button } from './settings-ui/button'
import { Spinner } from './settings-ui/spinner'
import { Field, FieldContent, FieldDescription, FieldGroup, FieldLabel } from './settings-ui/field'
import { LauncherCard } from '../components/LauncherCard'
import { htmlToPlainText } from '../app/htmlText'
import { useDeploySettings } from '../app/useDeploySettings'
import { REMOTE_ACCESS_GROUPS } from '../app/settingsGroups'
import { prepareValue } from '../config/editors'
import type { Edit, EditQueue } from '../config/EditQueue'
import { SettingsField } from './SettingsField'

function SettingsStatus({id, edit, queue}: {id: string; edit?: Edit; queue: EditQueue}) {
  const {ui} = useApp()
  if (!edit || !queue.savedVisible(edit)) return null
  const message = edit.status === 'error' ? ui('edit.inputPreserved', {error: edit.error ?? ''})
    : edit.status === 'saved' ? ui('edit.saved')
      : edit.status === 'saving' ? ui('edit.saving') : ui('edit.waitingConnection')
  if (edit.status === 'error') return <Alert id={`${id}-status`} variant="destructive">
    <AlertDescription>{message}{edit.retryable && <Button variant="outline" onClick={queue.retry}>{ui('edit.retry')}</Button>}</AlertDescription>
  </Alert>
  return <Badge id={`${id}-status`} variant="secondary" role="status">{message}</Badge>
}

/** 系统级部署设置与启动器设置；外观偏好在「界面设置」，远程访问与 WebUI 在「远程访问」。 */
export function Settings() {
  const {data, error, edits, queue} = useDeploySettings()
  const {t, ui} = useApp()

  return (
    <>
      <h1>{ui('nav.settings')}</h1>
      {error && <Alert variant="destructive"><AlertCircle/><AlertDescription>{error}</AlertDescription></Alert>}
      {edits.storageError && <Alert variant="destructive"><AlertCircle/><AlertDescription>{edits.storageError}</AlertDescription></Alert>}
      <LauncherCard/>
      {!data ? <span role="status"><Spinner aria-hidden="true"/>{ui('common.loading')}</span> : (
        data.groups.filter(group => !REMOTE_ACCESS_GROUPS.includes(group.key)).map(group => (
          <Card key={group.key}>
            <CardHeader>
              <CardTitle role="heading" aria-level={2}>{t(`Gui.DeploySetting.Group${group.key}`)}</CardTitle>
            </CardHeader>
            <CardContent><FieldGroup>
              {group.fields.map(field => {
                const id = `deploy-${field.key}`
                const current = edits.edits[field.key]?.value ?? field.value
                const invalid = edits.edits[field.key]?.status === 'error'
                const isBoolean = field.type === 'bool' || field.type === 'checkbox' || typeof current === 'boolean'
                const descriptionId = `${id}-description`
                const label = <FieldLabel htmlFor={id}>{field.label}</FieldLabel>
                const description = <FieldDescription id={descriptionId}>{field.key === 'Password' ? ui('settings.passwordHelp') : htmlToPlainText(field.help)}</FieldDescription>
                const status = <SettingsStatus id={id} edit={edits.edits[field.key]} queue={queue}/>
                const control = <SettingsField
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
                return <Field key={field.key} orientation={isBoolean ? 'horizontal' : 'vertical'}
                  data-invalid={invalid || undefined} data-disabled={data.demo || undefined}>
                  {isBoolean ? <><FieldContent>{label}{description}{status}</FieldContent>{control}</>
                    : <>{label}{control}{description}{status}</>}
                </Field>
              })}
            </FieldGroup></CardContent>
          </Card>
        ))
      )}
    </>
  )
}
