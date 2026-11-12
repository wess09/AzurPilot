/**
 * @fileoverview 换船装备页：按舰种维护三槽装备码，写入 FleetInfo.FleetEquipment 供智能换船读取。
 */

import {Button} from '../components/ui/button'
import {useEffect, useState} from 'react'
import {useParams} from 'react-router-dom'
import {api} from '../api/client'
import {useApp, useConnection} from '../app/context'
import {Switch} from '../components/official-ui/switch'
import {Input} from '../components/official-ui/input'
import {editor} from '../config/editors'
import {ErrorBox, Loading, PageTitle} from '../components/ui'

/** 支持配置装备码的舰种全集，顺序即设置页的分节顺序。 */
export const equipmentTypes = ['DD', 'CL', 'CA', 'CB', 'BC', 'BB', 'CVL', 'CV', 'BBV', 'SS', 'SSV', 'AR', 'BM', 'AE', 'IX'] as const
type ShipType = typeof equipmentTypes[number]
type CodeSet = [string, string, string]
type Codes = Record<ShipType, CodeSet>
const codeSlots = [0, 1, 2] as const

/**
 * 解析并校验装备码配置：接受 JSON 字符串或已解析对象，键必须是 equipmentTypes 中的舰种，
 * 值为至多 3 个字符串码；缺槽补空串，形状不符时抛「Invalid equipment codes」。
 */
export function equipmentCodes(value: unknown): Codes {
  const parsed = typeof value === 'string' ? JSON.parse(value) : value ?? {}
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)
      || Object.keys(parsed).some(key => !equipmentTypes.includes(key as ShipType))) throw new Error('Invalid equipment codes')
  return Object.fromEntries(equipmentTypes.map(kind => {
    const value = Object.hasOwn(parsed, kind) ? parsed[kind] : []
    const entries = typeof value === 'string' ? [value] : value
    if (!Array.isArray(entries) || entries.length > 3 || entries.some(code => typeof code !== 'string')) throw new Error('Invalid equipment codes')
    return [kind, codeSlots.map(index => (entries[index] ?? '').trim())]
  })) as Codes
}

/** 按舰种渲染三格装备码输入框，槽位序号从 1 起。 */
export function EquipmentCodeFields({codes, disabled, change}: {codes: Codes; disabled: boolean; change: (kind: ShipType, index: number, value: string) => void}) {
  const {ui} = useApp()
  return <div className="fleet-grid">{equipmentTypes.map(kind => <section className="panel" key={kind}>
    <div className="panel-heading flex flex-wrap items-center gap-2.5">
      <h2>{ui(`fleetEquipment.${kind}`)}</h2><span className="muted">{ui('fleetEquipment.code')}</span>
    </div>
    <div className="fleet-column grid gap-2.5">{codeSlots.map(index => <label key={index}
      htmlFor={`equipment-${kind}-${index + 1}`} className="flex items-center gap-2">
      <span aria-hidden="true">{index + 1}</span><Input type="text" id={`equipment-${kind}-${index + 1}`}
        aria-label={`${ui(`fleetEquipment.${kind}`)} ${ui('fleetEquipment.code')} ${index + 1}`}
        dir="ltr" spellCheck={false} value={codes[kind][index]} disabled={disabled}
        placeholder={ui('fleetEquipment.placeholder')} onChange={event => change(kind, index, event.target.value)}/>
    </label>)}</div>
  </section>)}</div>
}

/** 仅保存智能换船的装备配置，不注册或启动独立游戏任务。 */
export function FleetEquipment() {
  const {instance = ''} = useParams()
  const {ui, notify} = useApp(), connection = useConnection()
  const [enabled, setEnabled] = useState(false), [codes, setCodes] = useState<Codes>()
  const [pending, setPending] = useState(0), [error, setError] = useState('')
  const [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false)
  const disabled = busy || connection !== 'ready'
  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    void api.request('config.get', {instance}).then(result => {
      if (!active) return
      const values = result.values.FleetInfo?.FleetEquipment
      setEnabled(values?.Enabled === true); setCodes(equipmentCodes(values?.Codes))
      setPending(Object.keys(values?.State ?? {}).length); setError(''); setDirty(false)
    }).catch(error => {if (active) setError((error as Error).message)})
    return () => {active = false}
  }, [instance, connection])

  async function save(nextEnabled = enabled) {
    if (!codes) return
    setBusy(true); setError('')
    try {
      // 先等本实例未提交的编辑落定，再读最新 revision 提交，避免拿着旧修订号撞乐观锁。
      await editor(`config:${instance}`).settled()
      const current = await api.request('config.get', {instance})
      const result = await api.request('config.patch', {instance, revision: current.revision, changes: [
        {path: 'FleetInfo.FleetEquipment.Enabled', value: nextEnabled},
        {path: 'FleetInfo.FleetEquipment.Codes', value: JSON.stringify(equipmentCodes(codes))},
      ]})
      const values = result.values.FleetInfo.FleetEquipment
      setEnabled(values.Enabled === true); setCodes(equipmentCodes(values.Codes))
      setPending(Object.keys(values.State ?? {}).length); setDirty(false); notify(ui('fleetEquipment.saved'))
    } catch (error) {setError((error as Error).message)}
    finally {setBusy(false)}
  }
  return <>
    <PageTitle title={ui('fleetEquipment.title')} actions={<>
      <span>{ui('fleetEquipment.enable')}</span><Switch checked={enabled} aria-label={ui('fleetEquipment.enable')}
        disabled={disabled || !codes} onCheckedChange={next => void save(next)}/>
      <Button disabled={disabled || !dirty} onClick={() => void save()}>{ui('fleetEquipment.save')}</Button>
    </>}/>
    <section className="panel" style={{padding: '16px 20px', marginBottom: 20}}>
      <p>{ui('fleetEquipment.help')}</p><p>{ui('fleetEquipment.skip')}</p><p>{ui('fleetEquipment.support')}</p>
    </section>
    {pending > 0 && <p role="status">{ui('fleetEquipment.pending', {number: pending})}</p>}
    {error && <ErrorBox message={error}/>}
    {codes ? <EquipmentCodeFields codes={codes} disabled={disabled} change={(kind, index, value) => {
      // 该回调只在 codes 就绪的分支里挂载，previous 的非空断言不会落空。
      setCodes(previous => {
        const entries = [...previous![kind]] as CodeSet
        entries[index] = value
        return {...previous!, [kind]: entries}
      }); setDirty(true)
    }}/> : !error && <Loading/>}
  </>
}
