/**
 * @fileoverview 实例一键批量启停逻辑与目标过滤。
 */

import type {Instance} from '../api/types'

/** 一键启停的动作，与标签页上那枚单实例启停钮同一套语义。 */
type BulkAction = 'start' | 'stop'

/**
 * 根据实例运行状态决定一键操作。
 *
 * @param instances 当前实例列表。
 * @returns 全部运行时为 stop，否则为 start。
 */
export function bulkAction(instances: Instance[]): BulkAction {
    return instances.length > 0 && instances.every(item => item.status === 'running') ? 'stop' : 'start'
}

/**
 * 挑出真正需要改变状态的实例。
 *
 * @param instances 当前实例列表。
 * @param action 目标启停动作。
 * @returns 仍需发出请求的实例名。
 */
export function bulkTargets(instances: Instance[], action: BulkAction): string[] {
    return instances.filter(item => action === 'start' ? item.status !== 'running' : item.status === 'running').map(item => item.name)
}
