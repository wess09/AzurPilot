import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { Check, ChevronDown } from 'lucide-react'
import { useApp } from '../app/context'

/**
 * 顶栏的「任务配置」下拉：列出该实例的全部任务，点一下直接跳到对应任务页。
 *
 * 旧版实例页把左侧的分组导航让给了调度器与任务计划，页内就没有了跨任务的入口，
 * 所以这个跳转放在顶栏（面包屑的第三段），与实例下拉同一套交互。
 */
export function TaskSwitcher() {
  const {schema, t, ui} = useApp()
  const {instance} = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const container = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const currentTask = location.pathname.match(/\/task\/([^/]+)/)?.[1] ?? null

  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    container.current?.querySelector<HTMLButtonElement>('[aria-checked="true"], [role="menuitem"]')?.focus()
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  useEffect(() => {setOpen(false)}, [location.pathname])

  const groups = Object.entries(schema?.menu ?? {}).filter(([, group]) => group.page !== 'tool' && group.tasks.length)

  return <div className="task-picker" ref={container} onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false)
  }} onKeyDown={event => {
    if (event.key === 'Escape') {setOpen(false); trigger.current?.focus()}
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    if (!open) {setOpen(true); return}
    const items = Array.from(container.current!.querySelectorAll<HTMLButtonElement>('[role^="menuitem"]:not(:disabled)'))
    const current = items.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
    items[next]?.focus()
  }}>
    <button ref={trigger} type="button" className="task-picker-trigger" aria-label={ui('nav.taskJump')} title={ui('nav.taskJump')} aria-haspopup="menu" aria-expanded={open} aria-controls="task-picker-menu" onClick={() => setOpen(!open)}>
      {ui('nav.taskConfig')}<ChevronDown size={12}/>
    </button>
    {open && <div className="task-picker-menu" id="task-picker-menu" role="menu" aria-label={ui('nav.taskJump')}>
      {groups.length ? groups.map(([key, group]) => <div className="task-picker-group" key={key}>
        <span className="task-picker-group-name">{t(`Menu.${key}.name`)}</span>
        {group.tasks.map(task => <button key={task} role="menuitemradio" aria-checked={task === currentTask} onClick={() => {
          setOpen(false); trigger.current?.focus()
          if (task !== currentTask) navigate(`/i/${instance}/task/${task}`)
        }}><span>{t(`Task.${task}.name`)}</span>{task === currentTask && <Check size={15}/>}</button>)}
      </div>) : <div className="task-picker-empty">{ui('nav.taskJumpEmpty')}</div>}
    </div>}
  </div>
}
