/**
 * 从 Statistics.tsx 原 208-230、256-284、361-368 行提取，纯搬迁未改动。
 * 统计页数据流：刷新/盘点/导出、原始记录表数据与分节上报的数据缓存。
 */
import { useCallback, useState, useSyncExternalStore } from 'react'
import { getSelectedKeysForCategory, getStatisticsPrefs, getStatisticsPrefsVersion, subscribeStatisticsPrefs } from '../../app/statisticsPrefs'
import { api } from '../../api/client'
import { editor } from '../../config/editors'
import { buildSeriesView, downloadCsv } from '../../components/statisticsData'
import { useApp } from '../../app/context'
import type { StatisticsReport } from '../../api/types'
import type { Category } from './shared'
import { categories } from './shared'

export function useStatisticsData({instance, category}: {instance: string; category: Category}) {
  const {ui, notify} = useApp()
  const [revision, setRevision] = useState(0)
  const [data, setData] = useState<StatisticsReport>()
  const [refreshing, setRefreshing] = useState(false)
  const [startingStorage, setStartingStorage] = useState(false)
  const [storageError, setStorageError] = useState('')
  /* 原始记录表的内容由图表计算，这里只给它一张卡片的位置。 */
  useSyncExternalStore(subscribeStatisticsPrefs, getStatisticsPrefsVersion, getStatisticsPrefsVersion)
  const prefs = getStatisticsPrefs()

  /* 原始记录卡自己算同一份数据：筛选与图表一致，两边读同一份偏好。 */
  const rawTableOf = (page: Category, report: StatisticsReport | undefined) => {
    if (!report) return null
    const view = buildSeriesView(report.series, {selectedKeys: getSelectedKeysForCategory(page, report.series), mode: prefs.chartMode, bucket: prefs.bucket, from: prefs.rangeFrom, to: prefs.rangeTo})
    return {
      title: view.isSingle ? ui('stats.rawTitle', {label: view.selectedSeries[0].label}) : ui('stats.multiMetrics'),
      columns: view.isSingle ? [ui('stats.time'), ui('stats.value'), ui('stats.source')] : [ui('stats.time'), ...view.selectedSeries.map(item => item.label), ui('stats.source')],
      rows: view.mergedRows,
      defaultSort: {index: 0, descending: true},
    }
  }

  async function refresh() {
    setRefreshing(true)
    try {
      if (category === 'loot') await api.request('statistics.refreshLoot', {instance})
      setRevision(value => value + 1)
    } catch {
      /* 刷新失败时保持当前视图：各分节自身的取数错误会呈现。 */
    } finally {setRefreshing(false)}
  }
  async function runStorageStatistics() {
    setStartingStorage(true)
    setStorageError('')
    try {
      await editor(`config:${instance}`).settled()
      await api.request('tasks.run', {instance, task: 'StorageStatistics'})
      notify(ui('stats.storageStarted'))
    } catch (error) {
      setStorageError((error as Error).message)
    } finally {setStartingStorage(false)}
  }
  function download() {
    if (!data) return
    downloadCsv(`${instance}-${ui(categories[category!])}-${data.month}`, [
      [ui('stats.metric'), ui('stats.value'), ui('stats.unit')], ...data.metrics.map(item => [item.label, item.value, item.unit]),
      ...data.tables.flatMap(table => [[table.title], table.columns, ...table.rows, []]),
      ...data.series.flatMap(series => [[series.label], [ui('stats.time'), ui('stats.value'), ui('stats.source')], ...series.points.map(point => [point.time, point.value, point.source ?? '']), []]),
      ...(data.notes.length ? [[ui('stats.notes')], ...data.notes.map(note => [note])] : []),
    ])
  }
  const [chainData, setChainData] = useState<Partial<Record<Category, StatisticsReport>>>({})
  const [chainError, setChainError] = useState<Partial<Record<Category, string>>>({})
  /* 分节上报数据：同一份数据复用同一对象。 */
  const reportOf = useCallback((page: Category, report: StatisticsReport | undefined, error = '') => {
    setChainData(prev => (prev[page] === report ? prev : {...prev, [page]: report}))
    setChainError(prev => (prev[page] === error ? prev : {...prev, [page]: error}))
    if (page === category) setData(report)
  }, [category])

  return {revision, setRevision, data, refreshing, startingStorage, storageError, chainData, chainError, rawTableOf, refresh, runStorageStatistics, download, reportOf}
}
