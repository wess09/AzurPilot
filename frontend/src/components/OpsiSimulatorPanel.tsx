/**
 * @fileoverview 大世界模拟器的后台控制、结果图与独立日志。
 */
import { useCallback, useState } from 'react'
import { FlaskConical, Play, Square, Terminal } from 'lucide-react'
import { api } from '../api/client'
import type { OpsiSimulatorStatus } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { LogPanel } from './LogPanel'
import { ErrorBox, Panel, PanelHeading } from './ui'
import {LoadBoundary} from './ui/load-boundary'
import {usePageRead} from '../app/usePageRead'

const pollEveryHalfSecond = () => 500

/**
 * 大世界（Opsi）模拟器面板：启停后台模拟，轮询进度、结果指标与结果图，模拟日志交给 LogPanel 渲染。
 *
 * @param instance 实例 ID。
 * @param beforeStart 启动前的校验回调；它抛错时中止启动，错误显示在面板上。
 */
export function OpsiSimulatorPanel({instance, beforeStart}: {instance: string; beforeStart: () => Promise<void>}) {
  const {t, ui, language} = useApp()
  const connection = useConnection()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(async (previous: OpsiSimulatorStatus | undefined) => {
    const next = await api.request('opsi.simulator.status', {instance, after: previous?.logs.cursor ?? 0})
    // A changed run without a reset can be a restarted server whose cursor has caught up.
    if (previous && previous.runId !== next.runId && !next.logs.reset)
      return api.request('opsi.simulator.status', {instance, after: 0})
    return next
  }, [instance])
  const {data, ready, error: pollError, reload, setData, invalidate} = usePageRead(instance, connection === 'ready' && !busy, load, pollEveryHalfSecond)
  const loadFigure = useCallback(() => api.request('opsi.simulator.figure', {instance}), [instance])
  const figure = usePageRead(JSON.stringify([instance, data?.figure]), connection === 'ready' && !!data?.figure, loadFigure)

  async function toggle() {
    invalidate()
    setBusy(true)
    setError('')
    try {
      let next: OpsiSimulatorStatus
      if (data?.running) next = await api.request('opsi.simulator.stop', {instance})
      else {
        await beforeStart()
        next = await api.request('opsi.simulator.start', {instance})
      }
      setData(next)
    } catch (error) {
      setError((error as Error).message)
    } finally {
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

  return <Panel className="tool-log-panel opsi-simulator-panel" aria-label={t('Task.OpsiSimulator.name')} data-run-id={data?.runId}>
    <PanelHeading title={t('Task.OpsiSimulator.name')} icon={<FlaskConical size={18}/>} actions={<button className="button primary" onClick={toggle}
        disabled={busy || connection !== 'ready' || !data || data.state === 'stopping'}>
        {data?.running ? <Square size={16}/> : <Play size={16}/>}
        {ui(data?.running ? 'simulator.stop' : 'simulator.start')}
      </button>}/>
    {error && <ErrorBox message={error}/>}
    <LoadBoundary ready={ready} error={pollError} retry={reload}>
    <p className="simulator-status" role="status">
      {ui(`simulator.${data?.state ?? 'idle'}`)}
      {Boolean(data?.totalSamples) && data ? ` · ${number(data.completedSamples)} / ${number(data.totalSamples)}` : false}
    </p>
    {data?.error && <ErrorBox message={data.error}/>}
    {metrics && <dl className="simulator-results" aria-label={ui('simulator.results')}>
      {metrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>}
    {data?.figure && <LoadBoundary ready={figure.ready} error={figure.error} retry={figure.reload}>
      {figure.data?.image && <img className="simulator-figure" src={figure.data.image} alt={ui('simulator.figure')}/>}
    </LoadBoundary>}
    <PanelHeading title={ui('monitor.logs')} icon={<Terminal size={18}/>}/>
    <LogPanel logs={data?.logs ?? null}/>
    </LoadBoundary>
  </Panel>
}
