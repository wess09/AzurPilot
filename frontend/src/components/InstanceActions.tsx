import { useEffect, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router-dom'
import { Settings2, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { Resource, Status } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { editor } from '../config/editors'
import { EditStatus } from './EditStatus'
import { FieldInput } from './FieldInput'
import { ResourceSettings } from './ResourceCards'
import { ErrorBox, Modal } from './ui'

/** showLabel：紧凑主题下按钮改挂日志面板工具栏，空间充足故补上文字。 */
export function InstanceActions({instance, status, resources, selectedResources, onResourcesChange, showLabel = false}: {instance: string; status: Status; resources: Resource[]; selectedResources: string[]; onResourcesChange: (keys: string[]) => void; showLabel?: boolean}) {
  const [open, setOpen] = useState(false)
  const {ui} = useApp()
  // 无障碍名称用「实例设置」，可见文字在紧凑下换成「资源卡片设置」。
  return <><button className="button" aria-label={ui('instance.settings')} title={ui('instance.settings')} onClick={() => setOpen(true)}><Settings2 size={16}/>{showLabel && <span>{ui('resource.settings')}</span>}</button>{open && <InstanceSettings instance={instance} status={status} resources={resources} selectedResources={selectedResources} onResourcesChange={onResourcesChange} onClose={() => setOpen(false)}/>}</>
}

function InstanceSettings({instance, status, resources, selectedResources, onResourcesChange, onClose}: {instance: string; status: Status; resources: Resource[]; selectedResources: string[]; onResourcesChange: (keys: string[]) => void; onClose: () => void}) {
  const connection = useConnection()
  const {refresh, notify, ui} = useApp()
  const navigate = useNavigate()
  const queue = editor(`startup:${instance}`)
  const edits = useSyncExternalStore(queue.subscribe, queue.getSnapshot)
  const [startup, setStartup] = useState<boolean>()
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    const confirmed = queue.confirmed()
    void api.request('startup.get', {instance}).then(value => {
      if (active) {setStartup(value.enabled); queue.reconcile(confirmed)}
    }).catch(error => {if (active) setError(error.message)})
    return () => {active = false}
  }, [connection, instance, queue])
  async function remove() {
    setBusy(true); setError('')
    try {
      const config = await api.request('config.get', {instance})
      await api.request('instances.delete', {instance, revision: config.revision})
      await refresh(); onClose(); navigate('/'); notify(ui('instance.backupNotice'))
    } catch (error) {setError((error as Error).message)} finally {setBusy(false)}
  }
  return <Modal title={instance} onClose={onClose}><div className="form-stack">
    {(error || edits.storageError) && <ErrorBox message={error || edits.storageError}/>}
    <div className="field-row"><label htmlFor="instance-startup">{ui('instance.autoRun')}</label><div><FieldInput id="instance-startup" label={ui('instance.autoRun')} value={edits.edits.enabled?.value ?? startup ?? false} disabled={startup === undefined} onChange={value => queue.change('enabled', value)}/><EditStatus id="instance-startup" edit={edits.edits.enabled} retry={queue.retry}/></div></div>
    <ResourceSettings resources={resources} selected={selectedResources} onChange={onResourcesChange}/>
    {deleting && <p>{ui('instance.deletePrompt', {name: instance})}</p>}
    <button className="button danger" disabled={busy || connection !== 'ready' || status === 'running' || status === 'updating'} onClick={() => deleting ? void remove() : setDeleting(true)}><Trash2 size={15}/>{deleting ? ui('instance.deleteConfirm') : ui('instance.delete')}</button>
  </div></Modal>
}
