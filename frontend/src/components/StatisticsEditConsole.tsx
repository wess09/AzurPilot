/**
 * @fileoverview 统计页布局自定义编辑控制台组件。
 */
import {Button} from './ui/button'

import { RotateCcw } from 'lucide-react'
import type { ReactNode } from 'react'
import { useApp } from '../app/context'
import type { PageId } from '../app/statisticsLayout'

interface StatisticsEditConsoleProps {
  /** 存储里是否已有自定义布局，决定还原按钮是否可用。 */
  customized: boolean
  /** 全部页面及其启用状态，按默认页序排列。 */
  pages: {id: PageId; label: string; enabled: boolean}[]
  onTogglePage: (id: PageId) => void
  onReset: () => void
  /** 组合链条的槽位区，随控制台一起收纳。 */
  children?: ReactNode
}

/** 布局编辑的控制台：收纳不便放在卡片上的控件，并给出还原入口。 */
export function StatisticsEditConsole({customized, pages, onTogglePage, onReset, children}: StatisticsEditConsoleProps) {
  const {ui} = useApp()
  return <section className="panel statistics-edit-console" aria-label={ui('stats.editConsole')}>
    <div className="panel-heading">
      <h3>{ui('stats.editConsole')}</h3>
      <span className="statistics-edit-state">{ui(customized ? 'stats.editLayoutCustom' : 'stats.editLayoutDefault')}</span>
      <Button variant="destructive" disabled={!customized} onClick={onReset}><RotateCcw size={15}/>{ui('stats.editReset')}</Button>
    </div>
    {children}
    <p className="panel-note">{ui('stats.editConsoleHint')}</p>
    <p className="panel-note">{ui('stats.orderHint')}</p>
    <div className="statistics-edit-actions">
      {pages.map(page => (
        <Button
          key={page.id}
          type="button"
          size="sm" variant={page.enabled ? 'default' : 'outline'}
          aria-pressed={page.enabled}
          onClick={() => onTogglePage(page.id)}
        >
          <span>{page.label}</span>
        </Button>
      ))}
    </div>
  </section>
}
