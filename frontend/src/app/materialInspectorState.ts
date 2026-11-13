/**
 * @fileoverview 材质检视器状态：整站悬浮/停靠的开关、停靠与最小化三态，跨组件共享。
 *
 * 检视器本体见 MaterialInspector.tsx；仅停靠值持久化，开合与最小化刷新后回到默认。
 */

interface MaterialInspectorState {
  open: boolean
  docked: boolean
  minimized: boolean
}

const STORAGE_DOCKED_KEY = 'azurpilot.materialInspector.docked'

const readDocked = (): boolean => {
  try {
    const val = localStorage.getItem(STORAGE_DOCKED_KEY)
    return val !== null ? val === '1' : true
  } catch {
    /* 存储不可用时用默认值：停靠与否只影响观感，不必阻断渲染。 */
    return true
  }
}

let state: MaterialInspectorState = {
  open: false,
  docked: readDocked(),
  minimized: false,
}

const listeners = new Set<() => void>()

/** 读取检视器当前状态快照，配 useSyncExternalStore 作 getSnapshot 使用。 */
export const getMaterialInspector = () => state

/** 订阅检视器状态变化，返回取消订阅函数。 */
export function subscribeMaterialInspector(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** 合并 patch 进状态并广播；停靠值变化时落盘，存储不可用则只保本会话。 */
function publish(patch: Partial<MaterialInspectorState>) {
  const previous = state
  state = { ...state, ...patch }
  if (state.docked !== previous.docked) {
    try {
      localStorage.setItem(STORAGE_DOCKED_KEY, state.docked ? '1' : '0')
    } catch {
      /* 存储不可用时仅当前会话有效 */
    }
  }
  listeners.forEach(l => l())
}

/** 打开检视器；打开时一并退出最小化，保证内容可见。 */
export const openMaterialInspector = () => publish({ open: true, minimized: false })
/** 关闭检视器，不影响停靠与最小化状态。 */
export const closeMaterialInspector = () => publish({ open: false })
/** 在悬浮与停靠之间切换；停靠选择落盘，刷新后保留。 */
export const toggleMaterialInspectorDocked = () => publish({ docked: !state.docked })
/** 切换最小化（收起内容但保持打开）。 */
export const toggleMaterialInspectorMinimized = () => publish({ minimized: !state.minimized })
/** 直接设置最小化与否。 */
export const setMaterialInspectorMinimized = (minimized: boolean) => publish({ minimized })
