/**
 * @fileoverview 统计页各拆分文件共用的分类映射与页面顺序常量。
 *
 * 从 Statistics.tsx 拆分而来。
 */
import type { Parameters } from '../../api/generated'
import type { UiKey } from '../../i18n'
import { defaultStatisticsLayout } from '../../app/statisticsLayout'

/** 统计分类 → 目录文案键；键集与后端 statistics.report 的 category 对齐。 */
export const categories: Readonly<Record<Category, UiKey>> = {resources: 'stats.category.resources', action: 'stats.category.action', opsi: 'stats.category.opsi', commission: 'stats.category.commission', ships: 'stats.category.ships', loot: 'stats.category.loot', research: 'stats.category.research', storage: 'stats.category.storage'}
/** 统计分类标识，取自后端契约。 */
export type Category = NonNullable<Parameters['statistics.report']['category']>
/** 统计导航里的入口：普通分类或独立的「资源管理」页。 */
export type StatisticsView = Category | 'management'

/** 页面显示开关按固定顺序排列，与排序后的页面顺序无关。 */
export const fixedPageOrder: readonly Category[] = defaultStatisticsLayout().pages.flat()
