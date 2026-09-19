import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { NavLink, useLocation, useParams } from 'react-router-dom'
import { Anchor, CalendarDays, ChevronRight, Compass, Gift, Palmtree, Search, Settings2, Ship, Sparkles, Swords, Wrench, type LucideIcon } from 'lucide-react'
import { useApp } from '../app/context'

const groupIcons: Record<string, LucideIcon> = {
  Alas: Settings2, Farm: Swords, Event: Sparkles, EventDaily: CalendarDays,
  Reward: Gift, DailyMission: CalendarDays, Opsi: Compass, Island: Palmtree, FleetManagement: Ship, Tool: Wrench,
}

export function isDesktopDevice(): boolean {
  if (typeof window === 'undefined') return false
  const isWide = window.innerWidth > 950
  const hasFinePointer = typeof window.matchMedia === 'function'
    ? !window.matchMedia('(hover: none)').matches
    : true
  return isWide && hasFinePointer
}

export function TaskNavFlyout({ defaultOpenKey }: { defaultOpenKey?: string } = {}) {
  const { schema, t, ui } = useApp()
  const { instance } = useParams()
  const location = useLocation()
  const base = instance ? `/i/${instance}` : ''

  const [search, setSearch] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [openMenuKey, setOpenMenuKey] = useState<string | null>(defaultOpenKey ?? null)
  const [flyoutPosition, setFlyoutPosition] = useState({ left: 0, top: 0 })
  const [portalReady, setPortalReady] = useState(false)

  const navContainerRef = useRef<HTMLDivElement>(null)
  const flyoutRef = useRef<HTMLDivElement>(null)
  const buttonRefs = useRef<Record<string, HTMLButtonElement | null>>({})
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearCloseTimer = useCallback(() => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current)
      closeTimerRef.current = null
    }
  }, [])

  const scheduleClose = useCallback(() => {
    clearCloseTimer()
    closeTimerRef.current = setTimeout(() => {
      setOpenMenuKey(null)
    }, 150)
  }, [clearCloseTimer])

  useEffect(() => {
    return () => clearCloseTimer()
  }, [clearCloseTimer])

  useEffect(() => setPortalReady(true), [])

  // 路由跳转时收起二级菜单
  useEffect(() => {
    clearCloseTimer()
    setOpenMenuKey(null)
  }, [location.pathname, clearCloseTimer])

  // 点击外部收起
  useEffect(() => {
    if (!openMenuKey) return
    const handleOutsidePointer = (event: PointerEvent) => {
      const target = event.target as Node
      if (flyoutRef.current?.contains(target)) return
      const currentBtn = buttonRefs.current[openMenuKey]
      if (currentBtn?.contains(target)) return
      clearCloseTimer()
      setOpenMenuKey(null)
    }
    document.addEventListener('pointerdown', handleOutsidePointer)
    return () => document.removeEventListener('pointerdown', handleOutsidePointer)
  }, [openMenuKey, clearCloseTimer])

  // 按 Escape 收起
  useEffect(() => {
    if (!openMenuKey) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        const keyToFocus = openMenuKey
        clearCloseTimer()
        setOpenMenuKey(null)
        buttonRefs.current[keyToFocus]?.focus()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [openMenuKey, clearCloseTimer])

  // 浮层挂到 body，避免主侧栏的 backdrop 上下文阻断二次模糊。
  const updateFlyoutPosition = useCallback(() => {
    if (!openMenuKey || !flyoutRef.current) return
    const btn = buttonRefs.current[openMenuKey]
    const flyout = flyoutRef.current
    if (!btn) return

    const btnRect = btn.getBoundingClientRect()
    const flyoutRect = flyout.getBoundingClientRect()
    const isDesktop = isDesktopDevice()

    let idealTopInViewport: number
    if (isDesktop) {
      // 电脑端：上边缘对齐
      idealTopInViewport = btnRect.top
    } else {
      // 手机端：原来的中线和点击的那一项中线对齐
      const itemCenterInViewport = btnRect.top + btnRect.height / 2
      idealTopInViewport = itemCenterInViewport - flyoutRect.height / 2
    }

    const minViewportTop = 8
    const maxViewportTop = Math.max(minViewportTop, window.innerHeight - flyoutRect.height - 8)
    const clampedViewportTop = Math.max(minViewportTop, Math.min(idealTopInViewport, maxViewportTop))

    setFlyoutPosition({
      left: window.innerWidth <= 480 ? 8 : btnRect.right + (window.innerWidth <= 950 ? 4 : 19),
      top: clampedViewportTop,
    })
  }, [openMenuKey])

  useLayoutEffect(() => {
    updateFlyoutPosition()
  }, [openMenuKey, portalReady, updateFlyoutPosition])

  useEffect(() => {
    if (!openMenuKey) return
    window.addEventListener('resize', updateFlyoutPosition)
    const scrollContainer = navContainerRef.current?.querySelector('.task-nav')
    scrollContainer?.addEventListener('scroll', updateFlyoutPosition, { passive: true })
    return () => {
      window.removeEventListener('resize', updateFlyoutPosition)
      scrollContainer?.removeEventListener('scroll', updateFlyoutPosition)
    }
  }, [openMenuKey, updateFlyoutPosition])

  // 鼠标悬停一级菜单：仅电脑端有效
  const handleGroupMouseEnter = (key: string) => {
    if (!isDesktopDevice()) return
    clearCloseTimer()
    const btn = buttonRefs.current[key]
    if (btn) {
      const btnRect = btn.getBoundingClientRect()
      setFlyoutPosition({
        left: btnRect.right + (window.innerWidth <= 950 ? 4 : 19),
        top: Math.max(8, btnRect.top),
      })
    }
    setOpenMenuKey(key)
  }

  // 鼠标离开一级菜单：仅电脑端有效
  const handleGroupMouseLeave = () => {
    if (!isDesktopDevice()) return
    scheduleClose()
  }

  // 点击一级菜单处理
  const handleGroupClick = (key: string) => {
    clearCloseTimer()
    if (isDesktopDevice()) {
      // 电脑端：鼠标悬停已弹出，点击保持展开
      setOpenMenuKey(key)
    } else {
      // 手机端行为不变：点击切换展开/收起
      setOpenMenuKey(prev => (prev === key ? null : key))
    }
  }

  // 鼠标进入二级菜单浮层
  const handleFlyoutMouseEnter = () => {
    if (!isDesktopDevice()) return
    clearCloseTimer()
  }

  // 鼠标离开二级菜单浮层
  const handleFlyoutMouseLeave = () => {
    if (!isDesktopDevice()) return
    scheduleClose()
  }

  const activeGroup = schema && openMenuKey ? schema.menu[openMenuKey] : null
  const activeTasks = activeGroup
    ? activeGroup.tasks.filter(
        task =>
          t(`Task.${task}.name`).toLowerCase().includes(search.toLowerCase()) ||
          task.toLowerCase().includes(search.toLowerCase())
      )
    : []

  return (
    <div className="task-nav-container" ref={navContainerRef}>
      <div className="sidebar-label task-nav-heading">{ui('nav.taskConfig')}<button className="icon-button" aria-label={searchOpen ? ui('nav.taskSearchCollapse') : ui('nav.taskSearchExpand')} aria-expanded={searchOpen} aria-controls="task-search" onClick={() => {setSearchOpen(!searchOpen); setSearch(''); setOpenMenuKey(null)}}><Search size={15}/></button></div>
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
            const filteredTasks = group.tasks.filter(
              task =>
                t(`Task.${task}.name`).toLowerCase().includes(search.toLowerCase()) ||
                task.toLowerCase().includes(search.toLowerCase())
            )
            if (!filteredTasks.length) return null

            const isGroupActive = group.tasks.some(task =>
              location.pathname.endsWith(`/task/${task}`)
            )
            const isExpanded = openMenuKey === key
            const GroupIcon = groupIcons[key] ?? Anchor

            return (
              <button
                key={key}
                type="button"
                ref={el => {
                  buttonRefs.current[key] = el
                }}
                className={[
                  'task-group-button',
                  isExpanded && 'expanded',
                  isGroupActive && 'active',
                ]
                  .filter(Boolean)
                  .join(' ')}
                onClick={() => handleGroupClick(key)}
                onMouseEnter={() => handleGroupMouseEnter(key)}
                onMouseLeave={handleGroupMouseLeave}
                aria-haspopup="menu"
                aria-expanded={isExpanded}
              >
                <GroupIcon size={18} className="task-group-icon" />
                <span className="task-group-title">{t(`Menu.${key}.name`)}</span>
                <ChevronRight size={13} className="task-group-arrow" />
              </button>
            )
          })}
      </nav>

      {openMenuKey && activeGroup && (() => {
        const flyout = (
        <div
          ref={flyoutRef}
          className="task-submenu-flyout"
          style={{ left: `${flyoutPosition.left}px`, top: `${flyoutPosition.top}px` }}
          role="menu"
          aria-label={t(`Menu.${openMenuKey}.name`)}
          onMouseEnter={handleFlyoutMouseEnter}
          onMouseLeave={handleFlyoutMouseLeave}
        >
          <div className="task-submenu-list">
            {activeTasks.map(task => (
              <NavLink
                key={task}
                to={`${base}/task/${task}`}
                className={({ isActive }) =>
                  ['task-submenu-item', isActive && 'active'].filter(Boolean).join(' ')
                }
                onClick={() => {
                  clearCloseTimer()
                  setOpenMenuKey(null)
                }}
                role="menuitem"
              >
                <span className="task-submenu-dot" />
                <span className="task-submenu-item-text">{t(`Task.${task}.name`)}</span>
              </NavLink>
            ))}
          </div>
        </div>
        )
        return portalReady ? createPortal(flyout, document.body) : flyout
      })()}
    </div>
  )
}
