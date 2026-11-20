/**
 * @fileoverview 换船装备页：按舰种维护三槽装备码，写入 FleetInfo.FleetEquipment 供智能换船读取。
 */

import {LoadBoundary} from '../components/ui/load-boundary'


import {Button} from '../components/ui/button'
import {useCallback, useEffect, useRef, useState} from 'react'
import {usePageRead} from '../app/usePageRead'
import {Panel, PanelHeading} from '../components/ui/page'
import {useParams} from 'react-router-dom'
import {api} from '../api/client'
import type {Config} from '../api/types'
import {useApp, useConnection} from '../app/context'
import {Switch} from '../components/official-ui/switch'
import {Input} from '../components/official-ui/input'
import {editor} from '../config/editors'
import {expectConfig, isConfigConflict} from '../config/expectConfig'
import {PageTitle} from '../components/ui'

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
  return <div className="fleet-grid">{equipmentTypes.map(kind => <Panel key={kind}>
    <PanelHeading className="flex flex-wrap items-center gap-2.5" title={ui(`fleetEquipment.${kind}`)} actions={<span className="muted">{ui('fleetEquipment.code')}</span>}/>
    <div className="fleet-column grid gap-2.5">{codeSlots.map(index => <label key={index}
      htmlFor={`equipment-${kind}-${index + 1}`} className="flex items-center gap-2">
      <span aria-hidden="true">{index + 1}</span><Input type="text" id={`equipment-${kind}-${index + 1}`}
        aria-label={`${ui(`fleetEquipment.${kind}`)} ${ui('fleetEquipment.code')} ${index + 1}`}
        dir="ltr" spellCheck={false} value={codes[kind][index]} disabled={disabled}
        placeholder={ui('fleetEquipment.placeholder')} onChange={event => change(kind, index, event.target.value)}/>
    </label>)}</div>
  </Panel>)}</div>
}

/** 仅保存智能换船的装备配置，不注册或启动独立游戏任务。 */
export function FleetEquipment() {
  const {instance = ''} = useParams()
  const {ui, notify} = useApp(), connection = useConnection()
  const [enabled, setEnabled] = useState(false), [codes, setCodes] = useState<Codes>()
  const [pending, setPending] = useState(0), [error, setError] = useState('')
  const [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false)
  const [conflict, setConflict] = useState(false)
  const disabled = busy || connection !== 'ready'
  const load = useCallback(async () => {
    const config = await api.request('config.get', {instance})
    equipmentCodes(config.values.FleetInfo?.FleetEquipment?.Codes)
    return config
  }, [instance])
  const read = usePageRead(instance, connection === 'ready', load)
  const baseline = useRef<{key: string; value?: Config}>({key: instance})
  if (baseline.current.key !== instance) baseline.current = {key: instance}
  const editing = useRef(false)
  editing.current = dirty || busy
  useEffect(() => {setDirty(false); setConflict(false); setError('')}, [instance])
  useEffect(() => {
    if (!read.data) return
    const values = read.data.values.FleetInfo?.FleetEquipment
    if (!editing.current || baseline.current.value === undefined) {
      const nextCodes = equipmentCodes(values?.Codes), nextEnabled = values?.Enabled === true
      baseline.current.value = read.data
      setEnabled(nextEnabled); setCodes(nextCodes); setDirty(false)
    }
    setPending(Object.keys(values?.State ?? {}).length)
  }, [instance, read.data])

  async function save(nextEnabled = enabled) {
    if (!codes) return
    setBusy(true); setError('')
    try {
      await editor(`config:${instance}`).settled()
      const result = await api.request('config.patch', {instance, changes: expectConfig(baseline.current.value, [
        {path: 'FleetInfo.FleetEquipment.Enabled', value: nextEnabled},
        {path: 'FleetInfo.FleetEquipment.Codes', value: JSON.stringify(equipmentCodes(codes))},
      ])})
      baseline.current.value = result
      setConflict(false)
      read.setData(result)
      const values = result.values.FleetInfo?.FleetEquipment
      if (!values) {
        setEnabled(false); setCodes(equipmentCodes(undefined))
        setPending(0); setError(''); setDirty(false)
        return
      }
      setEnabled(values.Enabled === true); setCodes(equipmentCodes(values.Codes))
      setPending(Object.keys(values.State ?? {}).length); setDirty(false); notify(ui('fleetEquipment.saved'))
    } catch (error) {if (isConfigConflict(error)) setConflict(true); else setError((error as Error).message)}
    finally {setBusy(false)}
  }
  return <>
    <PageTitle title={ui('fleetEquipment.title')} actions={<>
      <span>{ui('fleetEquipment.enable')}</span><Switch checked={enabled} aria-label={ui('fleetEquipment.enable')}
        disabled={disabled || !codes} onCheckedChange={next => void save(next)}/>
      <Button disabled={disabled || !dirty} onClick={() => void save()}>{ui('fleetEquipment.save')}</Button>
    </>}/>
    <Panel style={{padding: '16px 20px', marginBottom: 20}}>
      <p>{ui('fleetEquipment.help')}</p><p>{ui('fleetEquipment.skip')}</p><p>{ui('fleetEquipment.support')}</p>
    </Panel>
    {pending > 0 && <p role="status">{ui('fleetEquipment.pending', {number: pending})}</p>}
    {conflict && <p role="alert">{ui('edit.conflict')} <Button type="button" variant="outline" onClick={() => {setDirty(false); setConflict(false); read.reload()}}>{ui('edit.reloadDiscard')}</Button></p>}
    <LoadBoundary ready={!!codes && read.ready} error={error || read.error} retry={read.reload}>
    {codes && <EquipmentCodeFields codes={codes} disabled={disabled} change={(kind, index, value) => {
      setCodes(previous => {
        if (!previous) return undefined
        const entries = [...previous[kind]] as CodeSet
        entries[index] = value
        return {...previous, [kind]: entries}
      }); setDirty(true)
    }}/>}</LoadBoundary>
  </>
}
