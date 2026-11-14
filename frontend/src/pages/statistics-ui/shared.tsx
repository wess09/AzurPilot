/**
 * 从 Statistics.tsx 原 122-124、134-135 行提取，纯搬迁未改动。
 * 统计页各拆分文件共用的分类映射与页面顺序常量。
 */
import type { Parameters } from '../../api/generated'
import type { UiKey } from '../../i18n'
import { defaultStatisticsLayout } from '../../app/statisticsLayout'

export const categories: Record<Category, UiKey> = {resources: 'stats.category.resources', action: 'stats.category.action', opsi: 'stats.category.opsi', commission: 'stats.category.commission', ships: 'stats.category.ships', loot: 'stats.category.loot', research: 'stats.category.research', storage: 'stats.category.storage'}
export type Category = NonNullable<Parameters['statistics.report']['category']>
export type StatisticsView = Category | 'management'

/* 页面显示开关按固定顺序排列，与排序后的页面顺序无关。 */
export const fixedPageOrder = defaultStatisticsLayout().pages.flat()
