/**
 * @fileoverview 存在 localStorage 里的界面偏好：读出、写入并通知订阅者。
 */

/**
 * 创建一组「读 / 订阅 / 写」偏好访问器。
 *
 * @param key localStorage 键。
 * @param parse 将存储原始值解析为偏好值，同时提供缺省回退。
 * @returns 可供 `useSyncExternalStore` 使用的偏好访问器。
 */
export function prefStore<T extends string>(key: string, parse: (raw: string | null) => T) {
  const listeners = new Set<() => void>()
  return {
    read: (): T => {
      try {
        return parse(localStorage.getItem(key))
      } catch {
        return parse(null)
      }
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener)
      return () => { listeners.delete(listener) }
    },
    write: (value: T) => {
      try {
        localStorage.setItem(key, value)
      } catch { /* 存储不可用时本次会话内仍生效。 */ }
      listeners.forEach(listener => listener())
    },
  }
}
