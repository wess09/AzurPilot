import {useEffect, useState} from 'react'
import {Link, useParams} from 'react-router-dom'
import {api} from '../api/client'
import {useApp, useConnection} from '../app/context'
import {editor} from '../config/editors'
import {ErrorBox, Loading, PageTitle} from '../components/ui'

type Rule = {slots: number[]; sources: number[]; favourite?: boolean}
type Rules = Record<string, Rule>
type Progress = Record<string, {last_source?: number; source?: number; favourite?: boolean; done?: number[]; pending?: unknown; rescan?: boolean}>
const numbers = [1, 2, 3, 4, 5, 6]
const rotationProgress = (value: unknown): Progress => value && typeof value === 'object' && !Array.isArray(value) ? value as Progress : {}

export function rotationRules(value: unknown): Rules {
  const parsed = typeof value === 'string' ? JSON.parse(value) : value ?? {}
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Invalid fleet rules')
  return Object.fromEntries(numbers.map(number => {
    const rule = parsed[String(number)] ?? {}
    return [number, {slots: Array.isArray(rule.slots) ? rule.slots : [], sources: Array.isArray(rule.sources) ? rule.sources : [], favourite: rule.favourite === true}]
  }))
}

/** 仅编辑联动规则，不注册调度任务，不启动游戏。 */
export function FleetRotation() {
  const {instance = ''} = useParams()
  const {ui, instances, notify} = useApp(), connection = useConnection()
  const [rules, setRules] = useState<Rules>()
  const [progress, setProgress] = useState<Progress>({})
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false)
  const running = instances.find(item => item.name === instance)?.status === 'running'
  const disabled = busy || connection !== 'ready'
  useEffect(() => {
    let active = true
    if (connection !== 'ready') return
    void api.request('config.get', {instance}).then(config => {
      if (!active) return
      const values = config.values.FleetInfo?.FleetRotation
      setRules(rotationRules(values?.Rules))
      setProgress(rotationProgress(values?.State))
      setError(''); setDirty(false)
    }).catch(error => {if (active) setError((error as Error).message)})
    return () => {active = false}
  }, [instance, connection])

  useEffect(() => {
    if (!running || connection !== 'ready') return
    let active = true
    const timer = setInterval(() => {
      void api.request('config.get', {instance}).then(config => {
        if (active) setProgress(rotationProgress(config.values.FleetInfo?.FleetRotation?.State))
      }).catch(error => {if (active) setError((error as Error).message)})
    }, 3000)
    return () => {active = false; clearInterval(timer)}
  }, [instance, connection, running])

  function change(fleet: number, field: 'slots' | 'sources', number: number) {
    setRules(previous => {
      const next = {...previous!}, rule = {...next[fleet]!}
      rule[field] = rule[field].includes(number) ? rule[field].filter(value => value !== number) : [...rule[field], number].sort()
      next[fleet] = rule
      return next
    })
    setDirty(true)
  }

  async function save(reset = false) {
    if (!rules) return
    setBusy(true); setError('')
    try {
      await editor(`config:${instance}`).settled()
      const config = await api.request('config.get', {instance})
      const result = await api.request('config.patch', {instance, revision: config.revision, changes: [
        {path: 'FleetInfo.FleetRotation.Rules', value: JSON.stringify(rules)},
        ...(reset ? [{path: 'FleetInfo.FleetRotation.State', value: {}}] : []),
      ]})
      setProgress(rotationProgress(result.values.FleetInfo.FleetRotation.State))
      setDirty(false); notify(ui('rotation.saved'))
    } catch (error) {setError((error as Error).message)}
    finally {setBusy(false)}
  }

  return <>
    <PageTitle title={ui('rotation.title')} actions={<>
      <button className="button primary" disabled={disabled || !dirty} onClick={() => void save()}>{ui('rotation.save')}</button>
    </>}/>
    <p className="muted">{ui('rotation.help')}</p>
    <p className="muted">{ui('rotation.duplicates')}</p>
    <p><Link to={`/i/${instance}/task/FleetSwitch?tab=training`}>{ui('training.title')}</Link></p>
    {error && <ErrorBox message={error}/>}
    {!rules ? !error && <Loading/> : <div className="fleet-grid">{numbers.map(fleet => <section className="panel" key={fleet} aria-label={ui('fleet.title', {number: fleet})}>
      <div className="panel-heading"><h2>{ui('fleet.title', {number: fleet})}</h2></div>
      <div className="fleet-column"><h3>{ui('rotation.slots')}</h3>{numbers.map(slot => <label className="checkbox-label" key={slot} style={{display: 'flex', margin: '10px 0'}}>
        <input type="checkbox" checked={rules[fleet]!.slots.includes(slot)} disabled={disabled} onChange={() => change(fleet, 'slots', slot)}/>
        {ui('fleet.slot', {number: slot})} · {ui(rules[fleet]!.slots.includes(slot) ? 'rotation.swap' : 'rotation.keep')}
      </label>)}</div>
      <div className="fleet-column"><h3>{ui('rotation.sources')}</h3><div style={{display: 'flex', flexWrap: 'wrap', gap: 10}}>{numbers.filter(number => number !== fleet).map(number => <label className="checkbox-label" key={number}>
        <input type="checkbox" aria-label={ui('rotation.source', {number})} checked={rules[fleet]!.sources.includes(number)} disabled={disabled} onChange={() => change(fleet, 'sources', number)}/>{number}
      </label>)}<label className="checkbox-label">
        <input type="checkbox" checked={rules[fleet]!.favourite} disabled={disabled} onChange={event => {
          const favourite = event.target.checked
          setRules(previous => ({...previous!, [fleet]: {...previous![fleet]!, favourite}})); setDirty(true)
        }}/>{ui('rotation.favourite')}
      </label></div><p className="muted">{ui('rotation.favouriteHelp')}</p></div>
      <div className="fleet-column"><p>{(progress[fleet]?.pending || progress[fleet]?.rescan) && !running ? ui('rotation.uncertain') : progress[fleet]?.source ? ui('rotation.inProgress', {number: progress[fleet]!.source!}) : progress[fleet]?.favourite ? ui('rotation.lastFavourite') : progress[fleet]?.last_source ? ui('rotation.last', {number: progress[fleet]!.last_source!}) : ui('rotation.none')}</p></div>
    </section>)}</div>}
    <button className="button" disabled={disabled || running || !rules} onClick={() => void save(true)}>{ui('rotation.reset')}</button>
  </>
}
