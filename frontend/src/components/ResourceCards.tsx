/**
 * @fileoverview 仪表盘资源（石油、物资、魔方等）统计卡片组件。
 */

import { useLayoutEffect, useRef, useSyncExternalStore } from 'react'
import type { Resource } from '../api/types'
import { useApp } from '../app/context'
import { readDashboardPrefs, subscribeDashboardPrefs } from '../app/dashboardPrefs'
import { actionPointDogIcon, resourceLabels, ResourceIcon } from './resource-cards/icons'
import { recordText, ResourceValue } from './resource-cards/value'

export {actionPointDogIcon, defaultResourceKeys, moveResourceKey} from './resource-cards/icons'
export {ResourceSettings} from './resource-cards/settings'
/**
 * 仪表盘资源卡片网格：按用户选定顺序渲染资源卡，支持合并大卡、卡片/文字自适应等偏好。
 * @param resources 最近一次同步的资源快照；选定键里没有的按「等待同步」渲染。
 * @param selected 展示的资源键，顺序即卡片排列顺序。
 */
export function ResourceCards({resources, selected}: {resources: Resource[]; selected: string[]}) {
  const {ui} = useApp()
  const prefs = useSyncExternalStore(subscribeDashboardPrefs, readDashboardPrefs, readDashboardPrefs)
  const gridRef = useRef<HTMLDivElement>(null)
  const mergedRef = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const grid = gridRef.current
    if (!grid) return
    const contents = [...grid.querySelectorAll<HTMLElement>('.resource-value-content')]
    const fit = () => {
      // 整组先读宽度、恢复主题字号，再量自然宽度并写入结果，避免逐卡触发同步布局。
      const widths = contents.map(content => content.parentElement?.clientWidth ?? 0)
      for (const content of contents) content.style.removeProperty('font-size')
      const natural = contents.map(content => content.getBoundingClientRect().width)
      const shrunk = contents.flatMap((content, index) => {
        const width = widths[index]
        const naturalWidth = natural[index]
        if (width === undefined || naturalWidth === undefined || width <= 0 || naturalWidth <= width) return []
        const scale = Math.max(0, width - 4) / naturalWidth
        content.style.fontSize = `${scale}em`
        return [{content, width, scale}]
      })
      // 字形栅格化会使缩放后的字宽与比例估算有偏差，只对仍溢出的数值修正一次。
      const rendered = shrunk.map(({content}) => content.getBoundingClientRect().width)
      shrunk.forEach(({content, width, scale}, index) => {
        const renderedWidth = rendered[index]
        if (renderedWidth !== undefined && renderedWidth > width) content.style.fontSize = `${scale * Math.max(0, width - 4) / renderedWidth}em`
      })
    }
    fit()
    let frame: number | undefined
    const observer = new ResizeObserver(() => {
      if (frame !== undefined) return
      frame = requestAnimationFrame(() => {
        frame = undefined
        fit()
      })
    })
    for (const content of contents) {
      observer.observe(content)
      if (content.parentElement) observer.observe(content.parentElement)
    }
    return () => {
      observer.disconnect()
      if (frame !== undefined) cancelAnimationFrame(frame)
    }
  }, [selected, prefs.merged])

  // 卡片适应：按容器宽度算一行放得下几张，列数即「卡片数与一排容量」的较小者 ——
  // 溢出到第二排以后时末排沿用第一排尺寸，总数不足一排时列数就等于卡片数因而仍均分。
  useLayoutEffect(() => {
    const grid = gridRef.current
    // 通用卡片把卡片包成一张大卡，列数要算在真正装卡片的那一层上。
    const target = prefs.merged ? mergedRef.current : grid
    if (!grid || !target || !(prefs.fitCards || prefs.merged)) return
    const fit = () => {
      const style = getComputedStyle(target)
      const gap = parseFloat(style.columnGap) || 0
      const min = parseFloat(style.getPropertyValue('--resource-card-min')) || 0
      if (!target.clientWidth || !min) return
      const perRow = Math.max(1, Math.floor((target.clientWidth + gap) / (min + gap)))
      target.style.gridTemplateColumns = `repeat(${Math.min(selected.length, perRow)}, minmax(0, 1fr))`
    }
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(target)
    return () => { observer.disconnect(); target.style.gridTemplateColumns = '' }
  }, [prefs.fitCards, prefs.merged, selected.length])

  const entries = selected.map((key, index) => {
    const resource = resources.find(item => item.name === key)
    // record 为 2020-01-01 占位时间戳表示尚未真正同步过，按无记录处理。
    const recorded = resource?.record && !resource.record.startsWith('2020-01-01')
    const labelKey = resourceLabels[key]
    const label = labelKey ? ui(labelKey) : resource?.label ?? key
    const limit = resource?.limit
    const total = resource?.total
    const showLimit = typeof limit === 'number' && limit > 0
    const showTotal = !!recorded && !showLimit && resource?.name === 'ActionPoint' && typeof resource.value === 'number' && typeof total === 'number' && Number.isFinite(total) && total >= resource.value
    const value = resource?.value
    const currentText = recorded && value != null ? value.toLocaleString() : '—'
    const totalText = showTotal ? (total as number).toLocaleString() : undefined
    // 总行动力优先时总量与当前值互换；行动力以外的字段不受影响。
    const displayValue = prefs.totalFirst && totalText ? totalText : currentText
    const suffix = prefs.totalFirst && totalText ? currentText : recorded && showLimit ? limit.toLocaleString() : totalText
    const record = recordText(resource?.record)
    const foot = recorded ? (record.stale ? ui('resource.recordedTooOld') : record.text) : ui('resource.waitingSync')
    const iconSrc = prefs.dogIcon ? actionPointDogIcon(resource) : undefined
    return {key, index, label, displayValue, suffix, foot, iconSrc}
  })

  const className = ['resource-grid',
    (prefs.fitCards || prefs.merged) && 'resource-fit',
    prefs.fitText && 'resource-fit-text',
    prefs.dense && 'resource-dense'].filter(Boolean).join(' ')

  // 两种排法共用同一段卡片内部渲染，也都套在 .resource-card-body 里——那张二级面。
  const cardBody = (entry: typeof entries[number]) => <>
    <div className="resource-heading"><span>{entry.label}</span><div className="resource-image-wrap"><ResourceIcon resourceKey={entry.key} size={32} src={entry.iconSrc}/></div></div>
    <ResourceValue value={entry.displayValue} suffix={entry.suffix}/>
    <div className="resource-foot">{entry.foot}</div>
  </>

  return <div className={className} ref={gridRef}>{prefs.merged
    ? <section className="resource-card resource-merged">
      <div className="resource-card-body" ref={mergedRef}>{entries.map(entry => <section key={entry.key} className={`resource-merged-item resource-${entry.index % 4}`}>{cardBody(entry)}</section>)}</div>
    </section>
    : entries.map(entry => <section key={entry.key} className={`resource-card resource-${entry.index % 4}`}>
      <div className="resource-card-body">{cardBody(entry)}</div>
    </section>)}</div>
}
