/**
 * @fileoverview 旧版侧边栏树状展开任务列表组件。
 */

import { useState } from 'react'
import { MarqueeText } from './MarqueeText'
import { NavLink, useLocation, useParams } from 'react-router-dom'
import { Anchor, CalendarDays, ChevronDown, Compass, Gift, Palmtree, Search, Settings2, Ship, Sparkles, Swords, Wrench, type LucideIcon } from 'lucide-react'
import { useApp } from '../app/context'
import { taskNavItems, taskLabel } from './taskNavItems'
import { SearchHits } from './SearchHits'

const groupIcons: Record<string, LucideIcon> = {
  Alas: Settings2, Farm: Swords, Event: Sparkles, EventDaily: CalendarDays,
  Reward: Gift, DailyMission: CalendarDays, Opsi: Compass, Island: Palmtree, FleetManagement: Ship, Tool: Wrench,
}

/**
 * 侧栏的任务菜单：一级是分组，展开后具体任务直接往下列（旧 WebUI 的树状格式）。
 *
 * 展开状态只记「用户点开过的分组」；当前任务所在的分组始终展开，
 * 搜索时命中的分组也一律展开，清空搜索后回到用户自己的展开选择。
 */
export function TaskNavTree({ defaultOpenKey, onNavigate }: { defaultOpenKey?: string; onNavigate?: () => void } = {}) {
  const { schema, t, ui } = useApp()
  const { instance } = useParams()
  const location = useLocation()
  const base = instance ? `/i/${instance}` : ''

  const [search, setSearch] = useState('')
  const [openKeys, setOpenKeys] = useState<string[]>(() => (defaultOpenKey ? [defaultOpenKey] : []))
  // 手动收起的大类，记录收起时所在的页面路径。
  const [collapsed, setCollapsed] = useState<{key: string; from: string}>()

  function toggle(key: string) {
    setOpenKeys(keys => (keys.includes(key) ? keys.filter(item => item !== key) : [...keys, key]))
  }

  /** 收起当前所在的大类：收起状态与 openKeys 同时清掉该组。 */
  function collapseActive(key: string, isCollapsedHere: boolean) {
    setCollapsed(isCollapsedHere ? undefined : {key, from: location.pathname})
    setOpenKeys(keys => keys.filter(item => item !== key))
  }



  const keyword = search.trim().toLowerCase()
  const matches = (task: string) =>
    taskLabel(task, ui, t).toLowerCase().includes(keyword) || task.toLowerCase().includes(keyword)

  return (
    <div className="task-nav-container">
      <div className="sidebar-label task-nav-heading">{ui('nav.taskConfig')}</div>
      <div className="nav-search" id="task-search">
        <Search size={14} />
        <input
          aria-label={ui('nav.searchTask')}
          value={search}
          onChange={event => setSearch(event.target.value)}
          placeholder={ui('nav.searchTaskPlaceholder')}
        />
      </div>

      <SearchHits search={search} onNavigate={onNavigate}/>

      <nav className="task-nav">
        {schema &&
          Object.entries(schema.menu).map(([key, group]) => {
            const items = taskNavItems(key, group.tasks)
            const tasks = keyword ? items.filter(matches) : items
            if (!tasks.length) return null

            const isGroupActive = items.some(task =>
              location.pathname.endsWith(`/task/${task}`)
            )
            const collapsedHere = collapsed?.key === key && collapsed.from === location.pathname
            const isExpanded = Boolean(keyword) || (isGroupActive ? !collapsedHere : openKeys.includes(key))
            const GroupIcon = groupIcons[key] ?? Anchor

            return (
              <div className="task-group" key={key}>
                <button
                  type="button"
                  className={[
                    'task-group-button',
                    isExpanded && 'expanded',
                    isGroupActive && 'active',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onClick={() => (isGroupActive ? collapseActive(key, collapsedHere) : toggle(key))}
                  aria-expanded={isExpanded}
                  aria-controls={`task-group-${key}`}
                >
                  <GroupIcon size={18} className="task-group-icon" />
                  <MarqueeText className="task-group-title" text={t(`Menu.${key}.name`)}/>
                  <ChevronDown size={13} className="task-group-arrow" />
                </button>
                <div className={'task-submenu-list' + (isExpanded ? ' expanded' : '')} id={`task-group-${key}`}>
                  <div className="task-submenu-inner">
                    {tasks.map(task => (
                      <NavLink
                        key={task}
                        to={`${base}/task/${task}`}
                        className={({ isActive }) =>
                          ['task-submenu-item', isActive && 'active'].filter(Boolean).join(' ')
                        }
                        onClick={onNavigate}
                      >
                        <span className="task-submenu-dot" />
                        <MarqueeText className="task-submenu-item-text" text={taskLabel(task, ui, t)}/>
                      </NavLink>
                    ))}
                  </div>
                </div>
              </div>
            )
          })}
      </nav>
    </div>
  )
}
