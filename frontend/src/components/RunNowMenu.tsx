/**
 * @fileoverview 任务计划里的「批量立刻运行」：一次把多个等待中任务的下次运行时间清空。
 */

import { useState } from 'react'
import { Play } from 'lucide-react'
import { api } from '../api/client'
import type { Overview, Schema } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { Modal } from './ui'

type Task = Overview['tasks'][number]

/** 重启任务会重启游戏，批量运行时不动它，需要时到任务页单独点。 */
const SKIP = new Set(['Restart'])
/** config.patch 单次最多 200 条修改。 */
const PATCH_LIMIT = 200
const FALLBACK_NEXT_RUN = '2020-01-01 00:00:00'

/** 可以批量提前的任务：等待中、不在跳过列表，按任务计划里的顺序。 */
export function waitingTasks(tasks: Task[]) {
  return tasks.filter(task => task.state === 'waiting' && !SKIP.has(task.name)).map(task => task.name)
}

/** 按菜单分组拆分等待中的任务；没有等待任务的分组不列出。组内保持任务计划顺序。 */
export function groupWaiting(waiting: string[], menu: Schema['menu']) {
  return Object.entries(menu)
    .map(([key, group]) => ({key, tasks: waiting.filter(task => group.tasks.includes(task))}))
    .filter(group => group.tasks.length > 0)
}

/** 与任务页单个播放按钮相同：把 Scheduler.NextRun 设为参数默认值（落在过去），调度器下一轮即视为待运行。 */
export function runNowChanges(tasks: string[], args: Schema['args']) {
  return tasks.map(task => {
    const value = args[task]?.Scheduler?.NextRun?.value
    return {path: `${task}.Scheduler.NextRun`, value: typeof value === 'string' && value ? value : FALLBACK_NEXT_RUN}
  })
}

export function RunNowMenu({instance, tasks}: {instance: string; tasks: Task[]}) {
  const {schema, t, ui, notify} = useApp()
  const connection = useConnection()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const waiting = waitingTasks(tasks)
  if (!schema || !waiting.length) return null
  const groups = groupWaiting(waiting, schema.menu)

  async function run(names: string[]) {
    if (!schema) return
    setBusy(true)
    try {
      const changes = runNowChanges(names, schema.args)
      for (let start = 0; start < changes.length; start += PATCH_LIMIT) {
        await api.request('config.patch', {instance, changes: changes.slice(start, start + PATCH_LIMIT)})
      }
      notify(ui('scheduler.runNowDone', {count: names.length}))
      setOpen(false)
    } catch (error) {
      notify((error as Error).message, true)
    } finally {
      setBusy(false)
    }
  }

  const disabled = busy || connection !== 'ready'
  return <>
    <button type="button" className="button subtle icon-only rail-run-now" aria-label={ui('scheduler.runNowMenu')} title={ui('scheduler.runNowMenu')}
            disabled={connection !== 'ready'} onClick={() => setOpen(true)}><Play size={14}/></button>
    {open && <Modal title={ui('scheduler.runNowMenu')} onClose={() => setOpen(false)} className="run-now-modal">
      <div className="form-stack">
        <p>{ui('scheduler.runNowHelp')}</p>
        <button type="button" className="button primary" disabled={disabled} onClick={() => void run(waiting)}>
          <Play size={15}/>{ui('scheduler.runAllNow', {count: waiting.length})}
        </button>
        <div className="run-now-groups">
          {groups.map(group => <button type="button" className="button" key={group.key} disabled={disabled}
                                       title={group.tasks.map(task => t(`Task.${task}.name`)).join(', ')}
                                       onClick={() => void run(group.tasks)}>
            <Play size={14}/>{t(`Menu.${group.key}.name`)} ({group.tasks.length})
          </button>)}
        </div>
      </div>
    </Modal>}
  </>
}
