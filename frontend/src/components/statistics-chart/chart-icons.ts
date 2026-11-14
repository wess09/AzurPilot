/**
 * @fileoverview 图表系列图标：按系列自带图标或中文名匹配本地资源图标。
 * 从 StatisticsChart.tsx 原 63-94 行提取，纯搬迁未改动。
 */
import {resolveIcon} from '../StatisticsTable'
import {withTranslatedKeys} from '../statisticsText'
import type {StatSeries} from '../../api/types'

const iconBase = import.meta.env.BASE_URL
// 键为中文名；withTranslatedKeys 补上译名，翻译后的序列名仍能找到图标。
const chartResourceIcons: Record<string, string> = withTranslatedKeys({
  '石油': `${iconBase}oil.webp`,
  '物资': `${iconBase}gold.webp`,
  '钻石': `${iconBase}diamond.webp`,
  '心智魔方': `${iconBase}cube.webp`,
  '魔方': `${iconBase}cube.webp`,
  '活动 PT': `${iconBase}pt.webp`,
  '核心数据': `${iconBase}core_data.webp`,
  '荣誉勋章': `${iconBase}honor_medal.webp`,
  '功勋': `${iconBase}merit.webp`,
  '舰队币': `${iconBase}stamina.webp`,
  '心智单元': `${iconBase}cognitive_chips.webp`,
  '行动力': `${iconBase}guild_coin.webp`,
  '行动力资产': `${iconBase}action_asset.webp`,
  '海里数': `${iconBase}nautical_miles.webp`,
  '作战补给凭证': `${iconBase}supply_token.webp`,
  '特别兑换凭证': `${iconBase}special_token.webp`,
  '完成委托': `${iconBase}honor_medal.webp`,
})

/** 图表系列图标：优先用系列自带的 icon，否则按中文名精确匹配资源图标，再退到互相包含的模糊匹配。 */
/** 取系列图标：优先系列自带 icon 字段，否则按中文名查本地资源图标表。 */
export function getChartIcon(series: StatSeries): string | undefined {
  if (series.icon) return resolveIcon(series.icon)?.src
  const {label} = series
  if (chartResourceIcons[label]) return chartResourceIcons[label]
  for (const [key, icon] of Object.entries(chartResourceIcons)) {
    if (label.includes(key) || key.includes(label)) return icon
  }
  return undefined
}
