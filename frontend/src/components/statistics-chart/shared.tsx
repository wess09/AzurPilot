/**
 * @fileoverview 图表拆分文件的共享选项与类型别名。
 * 从 StatisticsChart.tsx 原 23-31 行提取，纯搬迁未改动。
 */
import type { UiKey } from '../../i18n'
import type { buildSeriesView } from '../statisticsData'
import type { useApp } from '../../app/context'

/** 采样粒度候选：K 线没有「每次记录」这一档，其余档位固定，避免重复项。 */
export function bucketOptions(isCandlestick: boolean, ui: (key: UiKey) => string) {
  return [
    ...(isCandlestick ? [] : [{value: 0, label: ui('stats.eachRecord')}]),
    {value: 5, label: ui('stats.fiveMinutes')},
    {value: 60, label: ui('stats.hourly')},
    {value: 1440, label: ui('stats.daily')},
  ]
}

/** buildSeriesView 的返回视图，图表渲染与指标区共用的数据形状。 */
export type ChartView = ReturnType<typeof buildSeriesView>

/** 图表单条数据点。 */
export type SeriesDatum = ChartView['seriesData'][number]

/** 数据点附加系列色与原始索引，供 ECharts 与指标区取色。 */
export type SeriesDatumWithColor = SeriesDatum & {color: string; index: number}

/** useApp 提供的翻译函数类型。 */
export type ChartUi = ReturnType<typeof useApp>['ui']
