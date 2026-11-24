/**
 * @fileoverview 顶栏快速任务跳转下拉菜单组件。
 */

import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { Check, ChevronDown } from 'lucide-react'
import { DropdownMenu } from 'radix-ui'
import { useApp } from '../app/context'
import { taskNavItems, taskLabel } from './taskNavItems'

/**
 * 顶栏的「任务配置」下拉：列出该实例的全部任务，点一下直接跳到对应任务页。
 *
 * 现代实例页把左侧的分组导航让给了调度器与任务计划，页内就没有了跨任务的入口，
 * 所以这个跳转放在顶栏（面包屑的第三段），与实例下拉同一套交互。
 */
export function TaskSwitcher() {
  const {schema, t, ui} = useApp()
  const {instance} = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const currentTask = location.pathname.match(/\/task\/([^/]+)/)?.[1] ?? null

  useEffect(() => {setOpen(false)}, [location.pathname])

  const groups = Object.entries(schema?.menu ?? {}).filter(([, group]) => group.page !== 'tool' && group.tasks.length)

  return <div className="task-picker">
    <DropdownMenu.Root open={open} onOpenChange={setOpen}>
      <DropdownMenu.Trigger asChild>
        <button type="button" className="task-picker-trigger" aria-label={ui('nav.taskJump')} title={ui('nav.taskJump')}>
          {ui('nav.taskConfig')}<ChevronDown size={12}/>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="task-picker-menu" aria-label={ui('nav.taskJump')} align="end" sideOffset={8} collisionPadding={8} loop>
          {groups.length ? <DropdownMenu.RadioGroup value={currentTask ?? ''} onValueChange={task => {
            if (task !== currentTask) navigate(`/i/${instance}/task/${task}`)
          }}>
            {groups.map(([key, group]) => <DropdownMenu.Group className="task-picker-group" key={key}>
              <DropdownMenu.Label className="task-picker-group-name">{t(`Menu.${key}.name`)}</DropdownMenu.Label>
              {taskNavItems(key, group.tasks).map(task => <DropdownMenu.RadioItem className="task-picker-item" key={task} value={task}>
                <span>{taskLabel(task, ui, t)}</span><DropdownMenu.ItemIndicator><Check size={15}/></DropdownMenu.ItemIndicator>
              </DropdownMenu.RadioItem>)}
            </DropdownMenu.Group>)}
          </DropdownMenu.RadioGroup> : <div className="task-picker-empty">{ui('nav.taskJumpEmpty')}</div>}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  </div>
}
