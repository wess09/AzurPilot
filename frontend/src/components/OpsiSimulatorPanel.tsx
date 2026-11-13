/**
 * @fileoverview 大世界模拟器的后台控制、结果图与独立日志。
 */
import { useEffect, useRef, useState } from 'react'
import { FlaskConical, Play, Square, Terminal } from 'lucide-react'
import { api } from '../api/client'
import type { OpsiSimulatorStatus } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { LogPanel } from './LogPanel'
import { ErrorBox } from './ui'

/**
 * 大世界（Opsi）模拟器面板：启停后台模拟，轮询进度、结果指标与结果图，模拟日志交给 LogPanel 渲染。
 *
 * @param instance 实例 ID。
 * @param beforeStart 启动前的校验回调；它抛错时中止启动，错误显示在面板上。
 */
export function OpsiSimulatorPanel({instance, beforeStart}: {instance: string; beforeStart: () => Promise<void>}) {
  const {t, ui, language} = useApp()
  const connection = useConnection()
  const [data, setData] = useState<OpsiSimulatorStatus>()
  const [error, setError] = useState('')
  const [pollError, setPollError] = useState('')
  const [busy, setBusy] = useState(false)
  const [image, setImage] = useState<string | null>(null)
  const [figureError, setFigureError] = useState('')
  const [retry, setRetry] = useState(0)
  // version 在启停动作开始与结束各加一：动作期间发出的轮询回包按版本丢弃，不顶掉动作刚拿到的状态。
  const action = useRef({busy: false, version: 0})

  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    let after = 0
    async function poll() {
      const version = action.current.version
      try {
        const value = await api.request('opsi.simulator.status', {instance, after})
        if (active && !action.current.busy && version === action.current.version) {
          after = value.logs.cursor
          // 回包的 runId 更小视为迟到数据，保留较新的状态。
          setData(previous => previous && previous.runId > value.runId ? previous : value)
          setPollError('')
        }
      } catch (error) {
        if (active) setPollError((error as Error).message)
      } finally {
        // 等本次请求完成再轮询，避免慢设备上积累请求。
        if (active) timer = setTimeout(poll, 500)
      }
    }
    void poll()
    return () => { active = false; clearTimeout(timer) }
  }, [connection, instance])

  useEffect(() => {
    setImage(null)
    setFigureError('')
    if (!data?.figure || connection !== 'ready') return
    let active = true
    void api.request('opsi.simulator.figure', {instance}).then(value => {
      if (active) setImage(value.image)
    }).catch(error => { if (active) setFigureError(error.message) })
    return () => { active = false }
  }, [connection, instance, data?.figure, retry])

  async function toggle() {
    action.current.busy = true
    action.current.version += 1
    setBusy(true)
    setError('')
    try {
      if (data?.running) setData(await api.request('opsi.simulator.stop', {instance}))
      else {
        await beforeStart()
        setData(await api.request('opsi.simulator.start', {instance}))
      }
    } catch (error) {
      setError((error as Error).message)
    } finally {
      action.current.busy = false
      action.current.version += 1
      setBusy(false)
    }
  }

  const number = (value: number) => value.toLocaleString(language, {maximumFractionDigits: 2})
  const result = data?.result
  const metrics = result && [
    [ui('simulator.cl1Count'), number(result.cl1Count)],
    [ui('simulator.meowCount'), number(result.meowCount)],
    [ui('simulator.crash'), `${number(result.crashedProbability * 100)}%`],
    [ui('simulator.cl1Time'), `${number(result.cl1Time / 3600)} h`],
    [ui('simulator.meowTime'), `${number(result.meowTime / 3600)} h`],
    [ui('simulator.ap'), number(result.ap)],
    [ui('simulator.coin'), number(result.coin)],
  ]

  return <section className="panel tool-log-panel opsi-simulator-panel" aria-label={t('Task.OpsiSimulator.name')} data-run-id={data?.runId}>
    <div className="panel-heading">
      <div><FlaskConical size={18}/><h2>{t('Task.OpsiSimulator.name')}</h2></div>
      <button className="button primary" onClick={toggle}
        disabled={busy || connection !== 'ready' || !data || data.state === 'stopping'}>
        {data?.running ? <Square size={16}/> : <Play size={16}/>}
        {ui(data?.running ? 'simulator.stop' : 'simulator.start')}
      </button>
    </div>
    <p className="simulator-status" role="status">
      {ui(`simulator.${data?.state ?? 'idle'}`)}
      {Boolean(data?.totalSamples) && ` · ${number(data!.completedSamples)} / ${number(data!.totalSamples)}`}
    </p>
    {error && <ErrorBox message={error}/>}
    {pollError && <ErrorBox message={pollError}/>}
    {data?.error && <ErrorBox message={data.error}/>}
    {metrics && <dl className="simulator-results" aria-label={ui('simulator.results')}>
      {metrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>}
    {figureError && <ErrorBox message={figureError} retry={() => setRetry(value => value + 1)}/>}
    {image && <img className="simulator-figure" src={image} alt={ui('simulator.figure')}/>}
    <div className="panel-heading"><div><Terminal size={18}/><h2>{ui('monitor.logs')}</h2></div></div>
    <LogPanel logs={data?.logs ?? null}/>
  </section>
}
