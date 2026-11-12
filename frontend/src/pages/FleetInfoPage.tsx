/**
 * @fileoverview 舰队信息页：查看 FleetScan 扫描出的六支舰队编成，并提供扫描开关。
 */

import {useEffect, useState} from 'react'
import {useParams} from 'react-router-dom'
import {Ship} from 'lucide-react'
import {api} from '../api/client'
import {useApp, useConnection} from '../app/context'
import {Switch} from '../components/official-ui/switch'
import {Checkbox} from '../components/official-ui/checkbox'
import {Label} from '../components/ui/label'
import {editor} from '../config/editors'
import {Empty, ErrorBox, Loading, PageTitle} from '../components/ui'
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
  const [value, setValue] = useState<unknown>(), [loaded, setLoaded] = useState(false)
  const [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const [updateEmotion, setUpdateEmotion] = useState(true)
  const reason = connection !== 'ready' ? ui('mind.scanDisconnected')
    : !current ? ui('mind.scanLoading')
    : current.status === 'updating' ? ui('mind.scanUpdating')
    : current.status === 'running' && !scanning ? ui('mind.scanRunning') : ''

  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    const load = async () => {
      try {
        const config = await api.request('config.get', {instance})
        if (active) {
          setValue(config.values.FleetInfo?.FleetInfo?.Result)
          setUpdateEmotion(config.values.FleetInfo?.FleetInfo?.UpdateEmotion !== false)
          setLoaded(true); setError('')
        }
      } catch (error) {if (active) setError((error as Error).message)}
    }
    void load()
    const timer = scanning ? setInterval(() => void load(), 3000) : undefined
    return () => {active = false; clearInterval(timer)}
  }, [instance, connection, scanning])

  async function toggleScan() {
    setBusy(true); setError('')
    try {
      if (scanning) await api.request('scheduler.stop', {instance})
      else {
        // 先等该实例的配置编辑队列落定，再读 revision 发起 patch，避免排队中的改动丢进覆盖。
        await editor(`config:${instance}`).settled()
        const config = await api.request('config.get', {instance})
        await api.request('config.patch', {instance, revision: config.revision, changes: [
          {path: 'FleetInfo.FleetInfo.UpdateEmotion', value: updateEmotion},
        ]})
        await api.request('tasks.run', {instance, task: 'FleetScan'})
        notify(ui('task.started'))
      }
    } catch (error) {setError((error as Error).message)}
    finally {setBusy(false)}
  }

  return <>
    <PageTitle title={t('Task.FleetInfo.name')} actions={<>
      <span className="flex items-center gap-3"><Checkbox id="fleet-update-emotion" checked={updateEmotion} disabled={!loaded || scanning || busy || !!reason} onCheckedChange={next => setUpdateEmotion(next === true)}/><Label htmlFor="fleet-update-emotion">{ui('fleet.updateEmotion')}</Label></span>
      <span>{t('Task.FleetScan.name')}</span><Switch checked={scanning} aria-label={t('Task.FleetScan.name')} disabled={!loaded || busy || !!reason} title={reason || undefined} onCheckedChange={() => void toggleScan()}/>
    </>}/>
    <p className="muted">{ui('rotation.duplicates')}</p>
    {reason && <p className="muted" role="status">{reason}</p>}
    {error && <ErrorBox message={error}/>}
    {loaded ? <FleetInfo value={value}/> : !error && <Loading/>}
    {scanning && <section className="panel"><h2>{ui('monitor.logs')}</h2><LogPanel/></section>}
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
  return <div className="fleet-grid">{[1, 2, 3, 4, 5, 6].map(fleet => <section className="panel" key={fleet}><div className="panel-heading"><h2>{ui('fleet.title', {number: fleet})}</h2><Ship size={18}/></div>{Object.entries(columns).map(([key, label]) => <div className="fleet-column" key={key}><h3>{label}</h3>{fleets[key]?.[fleet]?.length ? fleets[key][fleet].map((ship, index) => <div key={index}>
    <span>{typeof ship !== 'string' && Number.isInteger(ship.slot) && ship.slot! >= 1 && ship.slot! <= 6 ? `${ui('fleet.slot', {number: ship.slot!})} · ` : ''}{typeof ship === 'string' ? ship : ship.name || ui('fleet.unknown')}</span>
    <small>{typeof ship !== 'string' && ship.level ? `Lv.${ship.level} · ` : ''}{ui('fleet.emotion', {value: typeof ship !== 'string' && Number.isInteger(ship.emotion) && ship.emotion! >= 0 && ship.emotion! <= 150 ? ship.emotion! : ui('fleet.unknown')})}</small>
  </div>) : <p>{ui('fleet.noRecord')}</p>}</div>)}</section>)}</div>
}
