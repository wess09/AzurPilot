import {useEffect, useState} from 'react'
import {useParams} from 'react-router-dom'
import {api} from '../api/client'
import {useApp, useConnection} from '../app/context'
import {Switch} from '../components/Switch'
import {editor} from '../config/editors'
import {ErrorBox, Loading, PageTitle} from '../components/ui'

export const equipmentTypes = ['DD', 'CL', 'CA', 'CB', 'BC', 'BB', 'CVL', 'CV', 'BBV', 'SS', 'SSV', 'AR', 'BM', 'AE', 'IX'] as const
type ShipType = typeof equipmentTypes[number]
type CodeSet = [string, string, string]
type Codes = Record<ShipType, CodeSet>
const codeSlots = [0, 1, 2] as const

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

export function EquipmentCodeFields({codes, disabled, change}: {codes: Codes; disabled: boolean; change: (kind: ShipType, index: number, value: string) => void}) {
  const {ui} = useApp()
  return <div className="fleet-grid">{equipmentTypes.map(kind => <section className="panel" key={kind}>
    <div className="panel-heading" style={{display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap'}}>
      <h2>{ui(`fleetEquipment.${kind}`)}</h2><span className="muted">{ui('fleetEquipment.code')}</span>
    </div>
    <div className="fleet-column" style={{display: 'grid', gap: 10}}>{codeSlots.map(index => <label key={index}
      htmlFor={`equipment-${kind}-${index + 1}`} style={{display: 'flex', alignItems: 'center', gap: 8}}>
      <span aria-hidden="true">{index + 1}</span><input type="text" id={`equipment-${kind}-${index + 1}`}
        aria-label={`${ui(`fleetEquipment.${kind}`)} ${ui('fleetEquipment.code')} ${index + 1}`}
        dir="ltr" spellCheck={false} value={codes[kind][index]} disabled={disabled}
        placeholder={ui('fleetEquipment.placeholder')} onChange={event => change(kind, index, event.target.value)}
        style={{width: '100%', minWidth: 0, flex: 1}}/>
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
      <span>{ui('fleetEquipment.enable')}</span><Switch checked={enabled} label={ui('fleetEquipment.enable')}
        disabled={disabled || !codes} onChange={next => void save(next)}/>
      <button className="button primary" disabled={disabled || !dirty} onClick={() => void save()}>{ui('fleetEquipment.save')}</button>
    </>}/>
    <section className="panel" style={{padding: '16px 20px', marginBottom: 20}}>
      <p>{ui('fleetEquipment.help')}</p><p>{ui('fleetEquipment.skip')}</p><p>{ui('fleetEquipment.support')}</p>
    </section>
    {pending > 0 && <p role="status">{ui('fleetEquipment.pending', {number: pending})}</p>}
    {error && <ErrorBox message={error}/>}
    {codes ? <EquipmentCodeFields codes={codes} disabled={disabled} change={(kind, index, value) => {
      setCodes(previous => {
        const entries = [...previous![kind]] as CodeSet
        entries[index] = value
        return {...previous!, [kind]: entries}
      }); setDirty(true)
    }}/> : !error && <Loading/>}
  </>
}
