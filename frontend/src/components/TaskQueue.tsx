/**
 * @fileoverview 任务队列与拖拽排序列表组件。
 */

import { useLayoutEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import type { Overview } from '../api/types'
import { useApp } from '../app/context'
/** 条目位置。用布局坐标：它不含脚本正在写的 transform，
 *  动画没停时也能读到真实位置。 */
export type Box = {left: number; top: number}

/** 条目位置与尺寸。条目被移除后，靠它才能在原地画出一份等大的副本。 */
export type Placement = Box & {width: number; height: number}

/** 条目在文档里的布局坐标：沿 offsetParent 链累加到 body，
 *  谁当 offsetParent 都得到同一套数值；动画未结束时读到的仍是真实落点。 */
function documentBox(node: HTMLElement) {
  let left = 0
  let top = 0
  for (let step: HTMLElement | null = node; step; step = step.offsetParent as HTMLElement | null) {
    left += step.offsetLeft
    top += step.offsetTop
    if (step === document.body) break
  }
  return {left, top}
}

/** 一次渲染前后同一条目发生位移时的起止偏移；不足 1px 的抖动不算移动。
 *  返回空表示不必为这条播动画。 */
export function movedBy(before: Box | undefined, after: Box) {
  if (!before) return null
  const dx = before.left - after.left
  const dy = before.top - after.top
  if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return null
  return {dx, dy}
}

/**
 * 任务计划：运行中、待运行、等待中合并为一个列表。
 *
 * 条目显示任务名、下次执行时间与状态文字。时间只写值不带「执行时间：」前缀，
 * 运行中的任务同样把时间列出来（只标状态的话就看不出它排在什么时候）。
 * 运行中的状态文字带三点呼吸与扫光，用来表示调度器正在跑它。
 * `onNavigate` 供移动端抽屉在点击任务后收起使用，桌面端不传。
 *
 * 条目同处一个容器，状态变化时能被测到位置变化并连续平移过去。
 * 容器的高度用补间兑现，离开的条目在原地收缩塌陷，插入的条目自中心放大。
 */
export function TaskQueue({instance, data, onNavigate}: {instance: string; data?: Overview; onNavigate?: () => void}) {
  const {t, ui} = useApp()
  const positions = useRef(new Map<string, Placement>())
  const known = useRef(new Set<string>())
  const list = useRef<HTMLDivElement>(null)
  const heights = useRef(new Map<string, number>())
  const snapshots = useRef(new Map<string, HTMLElement>())
  const synced = useRef(false)
  const host = useRef<HTMLDivElement | null>(null)

  useLayoutEffect(() => {
    const container = list.current
    if (!container) return
    // 容器被换掉时，先前的记账对新节点作废，重新建基准。
    const fresh = !synced.current || host.current !== container
    synced.current = true
    host.current = container
    if (fresh) {
      known.current.clear()
      heights.current.clear()
    }
    const previous = fresh ? new Map<string, Placement>() : positions.current
    const next = new Map<string, Placement>()
    const moving: {element: HTMLElement; state: string; dx: number; dy: number}[] = []
    const arrived: HTMLElement[] = []
    const bodies: HTMLElement[] = []
    // 条目只在列表内部移动，位移不会超过列表自身尺寸。
    const span = {w: container.offsetWidth, h: container.offsetHeight}
    // 减去容器自身的位置，条目坐标即与容器相对，整页位移不会算成条目在动。
    const origin = documentBox(container)
    for (const body of container.querySelectorAll<HTMLElement>('.rail-queue-body')) {
      bodies.push(body)
      const state = body.closest('.rail-queue-group')!.className.split(' ').pop()!
      for (const element of body.querySelectorAll<HTMLElement>('[data-task]')) {
        // 键带上组名：同一条目换组后是另一个节点，位置按组分别记账。
        const key = `${state}/${element.dataset.task}`
        const box = documentBox(element)
        const after = {left: box.left - origin.left, top: box.top - origin.top, width: element.offsetWidth, height: element.offsetHeight}
        // 这一轮结束后元素可能已被移除，动画要用它当替身。
        snapshots.current.set(key, element.cloneNode(true) as HTMLElement)
        next.set(key, after)
        const shift = movedBy(previous.get(key), after)
        if (shift && Math.abs(shift.dx) <= span.w && Math.abs(shift.dy) <= span.h) moving.push({element, state, ...shift})
      }
    }
    const departed: {key: string; box: Placement}[] = []
    for (const [key, box] of previous) {
      if (!next.has(key)) departed.push({key, box})
    }
    for (const element of container.querySelectorAll<HTMLElement>('[data-task]')) {
      const state = element.closest('.rail-queue-group')!.className.split(' ').pop()!
      if (!known.current.has(`${state}/${element.dataset.task}`)) arrived.push(element)
    }
    for (const key of next.keys()) known.current.add(key)
    // 首次记录只建立基准，不播动画。
    positions.current = next
    // 正在塌陷的分组只播塌陷动画。
    const collapsing = new Set(departed.map(({key}) => key.split('/')[0]))
    if (fresh || matchMedia('(prefers-reduced-motion: reduce)').matches) return
    // 组的挤压缩放：高度骤变会让下方内容瞬移，补间后容器不再跳。
    for (const body of bodies) {
      const state = body.closest('.rail-queue-group')!.className.split(' ').pop()!
      const target = body.offsetHeight
      const seen = heights.current.get(state)
      // 动画中途量到的 offsetHeight 是中间值，取两者较大者当起点。
      const from = seen === undefined ? undefined : Math.max(seen, target)
      heights.current.set(state, target)
      if (from === undefined || from === target || collapsing.has(state)) continue
      body.animate([{height: `${from}px`}, {height: `${target}px`}], {duration: 260, easing: 'cubic-bezier(.22, .61, .36, 1)'})
    }
    for (const {element, state, dx, dy} of moving) {
      if (collapsing.has(state)) continue
      element.animate(
        [{transform: `translate(${dx}px, ${dy}px)`}, {transform: 'none'}],
        {duration: 320, easing: 'cubic-bezier(.22, .61, .36, 1)'},
      )
    }
    // 插入：在腾出的空位中心自小放大。
    for (const element of arrived) {
      element.animate(
        [{opacity: 0, transform: 'scale(.72)'}, {opacity: 1, transform: 'none'}],
        {duration: 260, easing: 'cubic-bezier(.22, .61, .36, 1)'},
      )
    }
    // 移除：把副本送回原位收缩塌陷；它塌掉的就是腾出的那段高度。
    for (const {key} of departed) {
      const source = snapshots.current.get(key)
      const state = key.split('/')[0]
      const body = container.querySelector<HTMLElement>(`.rail-queue-group.${state} .rail-queue-body`)
      const target = heights.current.get(state)
      if (!source || !body || target === undefined) continue
      const gap = Number.parseFloat(getComputedStyle(body).rowGap) || 0
      // 这一组的高度由「目标值 + 离场条目」收缩到目标值。
      body.animate([{height: `${target + source.offsetHeight + gap}px`}, {height: `${target}px`}], {duration: 260, easing: 'cubic-bezier(.22, .61, .36, 1)'})
      source.style.pointerEvents = 'none'
      body.appendChild(source)
      const animation = source.animate(
        [{opacity: 1, transform: 'scale(1)', height: `${source.offsetHeight}px`, marginBottom: `${gap}px`, offset: 0},
         {opacity: 0, transform: 'scale(.86)', height: `${source.offsetHeight}px`, marginBottom: `${gap}px`, offset: .4},
         {opacity: 0, transform: 'scale(.86)', height: '0px', marginBottom: '0px', offset: 1}],
        {duration: 260, easing: 'cubic-bezier(.22, .61, .36, 1)'},
      )
      animation.finished.then(() => source.remove()).catch(() => source.remove())
    }
  /* 条目位置只在 data 变化时改变。 */
  }, [data])

  const labels = {
    running: ui('scheduler.running'),
    pending: ui('scheduler.pending'),
    waiting: ui('scheduler.waiting'),
  }
  // 运行中与待运行同组：按「运行中 → 待运行 → 等待中」排，组内保持后端给出的优先级顺序。
  const tasks = (['running', 'pending', 'waiting'] as const)
    .flatMap(state => (data?.tasks ?? []).filter(task => task.state === state))

  return <div className="rail-task-list" ref={list}>
    {tasks.length > 0 ? (
      <>
        <div className="rail-task-heading">
          <strong>{ui('scheduler.plan')}</strong>
          <span>{tasks.length}</span>
        </div>
        <section className="rail-queue-group tasks" aria-label={ui('scheduler.plan')}>
          <div className="rail-queue-body">
            {tasks.map(task => {
              const nextRun = task.nextRun?.replace('T', ' ').trim()
              return <Link key={task.name} data-task={task.name} className={`rail-task-item ${task.state}`}
                           to={`/i/${instance}/task/${task.name}`} onClick={onNavigate}>
                <div className="rail-task-main">
                  <strong>{t(`Task.${task.name}.name`)}</strong>
                  {nextRun && <small>{nextRun}</small>}
                </div>
                <span className={`rail-task-state ${task.state}`}>
                  {task.state === 'running' && <span className="thinking-dots" aria-hidden="true"><i/><i/><i/></span>}
                  <span className="state-label">{labels[task.state]}</span>
                </span>
                <ChevronRight size={13}/>
              </Link>
            })}
          </div>
        </section>
      </>
    ) : <div className="rail-empty">{ui('scheduler.noEnabled')}</div>}
  </div>
}
