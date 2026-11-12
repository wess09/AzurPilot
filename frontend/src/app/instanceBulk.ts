/**
 * @fileoverview 实例一键批量启停逻辑与目标过滤。
 */

import type {Instance} from '../api/types'

/** 一键启停的动作，与标签页上那枚单实例启停钮同一套语义。 */
type BulkAction = 'start' | 'stop'

/** 全部实例都在运行才暂停，否则一律启用。 */
export function bulkAction(instances: Instance[]): BulkAction {
    return instances.length > 0 && instances.every(item => item.status === 'running') ? 'stop' : 'start'
}

/** 挑出真正需要改变状态的实例：已在目标状态里的不再发请求。 */
export function bulkTargets(instances: Instance[], action: BulkAction): string[] {
    return instances.filter(item => action === 'start' ? item.status !== 'running' : item.status === 'running').map(item => item.name)
}
