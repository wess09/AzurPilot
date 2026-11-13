/**
 * @fileoverview 侧栏搜索命中的配置项路径：从侧栏传给配置页，读到之后即清空。
 */

let pending: string | null = null
const listeners = new Set<() => void>()

/** 记下要定位的配置项路径，并通知订阅者。
 *
 * 路径形如 `Task.Group.Arg`，与配置页字段的 DOM id 一致。 */
export function setSearchTarget(path: string) {
  pending = path
  listeners.forEach(listener => listener())
}

/** 订阅待定位路径的变化，返回取消订阅函数。 */
export function subscribeSearchTarget(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** 读取待定位的路径但不取走它：字段渲染出来之前可能要查好几次。 */
export function peekSearchTarget(): string | null {
  return pending
}

/** 定位结束（成功或放弃）后清空，避免下次进入页面时又被定位一次。 */
export function clearSearchTarget() {
  pending = null
}
