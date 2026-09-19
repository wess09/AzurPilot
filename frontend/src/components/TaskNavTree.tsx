import { useState } from 'react'
import { NavLink, useLocation, useParams } from 'react-router-dom'
import { Anchor, CalendarDays, ChevronDown, Compass, Gift, Palmtree, Search, Settings2, Ship, Sparkles, Swords, Wrench, type LucideIcon } from 'lucide-react'
import { useApp } from '../app/context'

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
export function TaskNavTree({ defaultOpenKey }: { defaultOpenKey?: string } = {}) {
  const { schema, t, ui } = useApp()
  const { instance } = useParams()
  const location = useLocation()
  const base = instance ? `/i/${instance}` : ''

  const [search, setSearch] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [openKeys, setOpenKeys] = useState<string[]>(() => (defaultOpenKey ? [defaultOpenKey] : []))

  function toggle(key: string) {
    setOpenKeys(keys => (keys.includes(key) ? keys.filter(item => item !== key) : [...keys, key]))
  }

  const keyword = search.trim().toLowerCase()
  const matches = (task: string) =>
    t(`Task.${task}.name`).toLowerCase().includes(keyword) || task.toLowerCase().includes(keyword)

  return (
    <div className="task-nav-container">
      <div className="sidebar-label task-nav-heading">{ui('nav.taskConfig')}<button className="icon-button" aria-label={searchOpen ? ui('nav.taskSearchCollapse') : ui('nav.taskSearchExpand')} aria-expanded={searchOpen} aria-controls="task-search" onClick={() => {setSearchOpen(!searchOpen); setSearch('')}}><Search size={15}/></button></div>
      {searchOpen && <div className="nav-search" id="task-search">
        <Search size={14} />
        <input
          autoFocus
          aria-label={ui('nav.searchTask')}
          value={search}
          onChange={event => setSearch(event.target.value)}
          placeholder={ui('nav.searchTaskPlaceholder')}
        />
      </div>}

      <nav className="task-nav">
        {schema &&
          Object.entries(schema.menu).map(([key, group]) => {
            const tasks = keyword ? group.tasks.filter(matches) : group.tasks
            if (!tasks.length) return null

            const isGroupActive = group.tasks.some(task =>
              location.pathname.endsWith(`/task/${task}`)
            )
            const isExpanded = Boolean(keyword) || isGroupActive || openKeys.includes(key)
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
                  onClick={() => toggle(key)}
                  aria-expanded={isExpanded}
                  aria-controls={`task-group-${key}`}
                >
                  <GroupIcon size={18} className="task-group-icon" />
                  <span className="task-group-title">{t(`Menu.${key}.name`)}</span>
                  <ChevronDown size={13} className="task-group-arrow" />
                </button>
                {isExpanded && <div className="task-submenu-list" id={`task-group-${key}`}>
                  {tasks.map(task => (
                    <NavLink
                      key={task}
                      to={`${base}/task/${task}`}
                      className={({ isActive }) =>
                        ['task-submenu-item', isActive && 'active'].filter(Boolean).join(' ')
                      }
                    >
                      <span className="task-submenu-dot" />
                      <span className="task-submenu-item-text">{t(`Task.${task}.name`)}</span>
                    </NavLink>
                  ))}
                </div>}
              </div>
            )
          })}
      </nav>
    </div>
  )
}
