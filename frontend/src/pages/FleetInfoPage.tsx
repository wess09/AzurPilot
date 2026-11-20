/**
 * @fileoverview 舰队信息页：查看 FleetScan 扫描出的六支舰队编成，并提供扫描开关。
 */

import {LoadBoundary} from '../components/ui/load-boundary'
import {Button} from '../components/ui/button'


import {useCallback, useEffect, useRef, useState} from 'react'
import {usePageRead} from '../app/usePageRead'
import {Panel, PanelHeading} from '../components/ui/page'
import {useParams} from 'react-router-dom'
import {Ship} from 'lucide-react'
import {api} from '../api/client'
import type {Config} from '../api/types'
import {useApp, useConnection} from '../app/context'
import {Switch} from '../components/official-ui/switch'
import {Checkbox} from '../components/official-ui/checkbox'
import {Label} from '../components/ui/label'
import {editor} from '../config/editors'
import {expectConfig, isConfigConflict} from '../config/expectConfig'
import {Empty, ErrorBox, PageTitle} from '../components/ui'
import {LogPanel} from '../components/LogPanel'

/**
 * 舰队信息页：展示扫描结果并控制 FleetScan 任务。
 *
 * 扫描进行中每 3 秒轮询一次最新结果；启动扫描前先把「扫描时更新心情」写进实例配置，
 * 任务按它决定是否更新心情。连接断开、后台更新或已有任务运行时只提示原因，不给操作入口。
 */
export function FleetInfoPage() {
  const {instance = ''} = useParams()
  const {ui, t, instances, notify} = useApp(), connection = useConnection()
  const current = instances.find(item => item.name === instance)
  const scanning = current?.status === 'running' && current.currentTask === 'FleetScan'
  const [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false), [conflict, setConflict] = useState(false)
  const [updateEmotion, setUpdateEmotion] = useState(true)
  const reason = connection !== 'ready' ? ui('mind.scanDisconnected')
    : !current ? ui('mind.scanLoading')
    : current.status === 'updating' ? ui('mind.scanUpdating')
    : current.status === 'running' && !scanning ? ui('mind.scanRunning') : ''

  const load = useCallback(() => api.request('config.get', {instance}), [instance])
  const pollAfter = useCallback(() => scanning ? 3000 : 0, [scanning])
  const read = usePageRead(instance, connection === 'ready', load, pollAfter)
  const baseline = useRef<{key: string; value?: Config}>({key: instance})
  if (baseline.current.key !== instance) baseline.current = {key: instance}
  const editing = useRef(false)
  editing.current = dirty || busy
  useEffect(() => {setDirty(false); setConflict(false); setError('')}, [instance])
  const loaded = read.ready
  const value = read.data?.values.FleetInfo?.FleetInfo?.Result
  useEffect(() => {
    if (read.data && (!editing.current || baseline.current.value === undefined)) {
      const next = read.data.values.FleetInfo?.FleetInfo?.UpdateEmotion !== false
      baseline.current.value = read.data
      setUpdateEmotion(next)
    }
  }, [instance, read.data])

  async function toggleScan() {
    setBusy(true); setError('')
    try {
      if (scanning) await api.request('scheduler.stop', {instance})
      else {
        await editor(`config:${instance}`).settled()
        const result = await api.request('config.patch', {instance, changes: expectConfig(baseline.current.value, [
          {path: 'FleetInfo.FleetInfo.UpdateEmotion', value: updateEmotion},
        ])})
        baseline.current.value = result
        setDirty(false); setConflict(false)
        read.setData(result)
        await api.request('tasks.run', {instance, task: 'FleetScan'})
        notify(ui('task.started'))
      }
    } catch (error) {if (isConfigConflict(error)) setConflict(true); else setError((error as Error).message)}
    finally {setBusy(false)}
  }

  return <>
    <PageTitle title={t('Task.FleetInfo.name')} actions={<>
      <span className="flex items-center gap-3"><Checkbox id="fleet-update-emotion" checked={updateEmotion} disabled={!loaded || scanning || busy || !!reason} onCheckedChange={next => {setUpdateEmotion(next === true); setDirty(true)}}/><Label htmlFor="fleet-update-emotion">{ui('fleet.updateEmotion')}</Label></span>
      <span>{t('Task.FleetScan.name')}</span><Switch checked={scanning} aria-label={t('Task.FleetScan.name')} disabled={!loaded || busy || !!reason} title={reason || undefined} onCheckedChange={() => void toggleScan()}/>
    </>}/>
    <p className="muted">{ui('rotation.duplicates')}</p>
    {reason && <p className="muted" role="status">{reason}</p>}
    {conflict && <p role="alert">{ui('edit.conflict')} <Button type="button" variant="outline" onClick={() => {setDirty(false); setConflict(false); read.reload()}}>{ui('edit.reloadDiscard')}</Button></p>}
    <LoadBoundary ready={loaded} error={error || read.error} retry={read.reload}>{loaded && <FleetInfo value={value}/>}</LoadBoundary>
    {scanning && <Panel><h2>{ui('monitor.logs')}</h2><LogPanel/></Panel>}
  </>
}

/**
 * 渲染扫描结果：六支舰队各分先锋、主力、潜艇三列。
 *
 * value 是后端原始结果，可能是对象或 JSON 字符串；解析失败整体显示错误框。
 * 舰位与心情超出合法范围时按「未知」显示，不猜测异常值。
 */
export function FleetInfo({value}: {value: unknown}) {
  const {ui} = useApp()
  if (!value || (typeof value === 'object' && !Object.keys(value).length)) return <Empty icon={<Ship size={32}/>} title={ui('fleet.emptyTitle')}>{ui('fleet.emptyHint')}</Empty>
  let fleets: Record<string, Record<string, Array<{name: string; level?: number; emotion?: number | null; slot?: number} | string>>>
  try {fleets = typeof value === 'string' ? JSON.parse(value) : value} catch {return <ErrorBox message={ui('fleet.invalid')}/>}
  const columns = {vanguard: ui('fleet.vanguard'), main: ui('fleet.main'), submarine: ui('fleet.submarine')}
  return <div className="fleet-grid">{[1, 2, 3, 4, 5, 6].map(fleet => <Panel key={fleet}><PanelHeading title={ui('fleet.title', {number: fleet})} actions={<Ship size={18}/>}/>{Object.entries(columns).map(([key, label]) => <div className="fleet-column" key={key}><h3>{label}</h3>{fleets[key]?.[fleet]?.length ? fleets[key][fleet].map((ship, index) => <div key={index}>
    <span>{(() => {
      const slot = typeof ship === 'string' ? undefined : ship.slot
      if (slot === undefined || !Number.isInteger(slot) || slot < 1 || slot > 6) return ''
      return `${ui('fleet.slot', {number: slot})} · `
    })()}{typeof ship === 'string' ? ship : ship.name || ui('fleet.unknown')}</span>
    <small>{typeof ship !== 'string' && ship.level ? `Lv.${ship.level} · ` : ''}{ui('fleet.emotion', {value: (() => {
      const emotion = typeof ship === 'string' ? undefined : ship.emotion
      if (emotion == null || !Number.isInteger(emotion) || emotion < 0 || emotion > 150) return ui('fleet.unknown')
      return emotion
    })()})}</small>
  </div>) : <p>{ui('fleet.noRecord')}</p>}</div>)}</Panel>)}</div>
}
