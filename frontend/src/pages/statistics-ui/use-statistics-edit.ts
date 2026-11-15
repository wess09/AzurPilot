/**
 * @fileoverview 统计页编辑模式：布局状态、进入/重置/应用布局与图卡放大状态。
 *
 * 从 Statistics.tsx 拆分而来。
 */
import { useCallback, useState } from 'react'
import { hasStatisticsLayout, readStatisticsEditMode, readStatisticsLayout, resetStatisticsLayout, writeStatisticsEditMode, writeStatisticsLayout } from '../../app/statisticsLayout'
import type { StatisticsLayout } from '../../app/statisticsLayout'
import type { UiTranslator } from '../../i18n'

/**
 * 统计页编辑模式 Hook：编辑开关、布局草稿、重置与放大图卡状态。
 *
 * @param params.ui 文案函数。
 * @param params.notify 提示回调。
 */
export function useStatisticsEdit({ui, notify}: {ui: UiTranslator; notify: (message: string, error?: boolean) => void}) {
  const [editMode, setEditMode] = useState(readStatisticsEditMode)
  const [customized, setCustomized] = useState(hasStatisticsLayout)
  const [layout, setLayout] = useState(readStatisticsLayout)
  const toggleEditMode = () => {
    const next = !editMode
    writeStatisticsEditMode(next)
    setEditMode(next)
    notify(ui(next ? 'stats.editEntered' : 'stats.editExited'))
  }
  const resetLayout = () => {
    resetStatisticsLayout()
    setLayout(readStatisticsLayout())
    setCustomized(false)
    notify(ui('stats.editResetDone'))
  }
  const applyLayout = (next: StatisticsLayout) => {
    writeStatisticsLayout(next)
    setLayout(next)
    setCustomized(true)
  }
  /* 组合页里的每个分区各有一张图卡，放大只作用于被点的那张。 */
  const [expandedChart, setExpandedChart] = useState<string | null>(null)
  const toggleExpanded = useCallback((page: string) => setExpandedChart(current => current === page ? null : page), [])

  return {editMode, customized, layout, applyLayout, toggleEditMode, resetLayout, expandedChart, toggleExpanded}
}
