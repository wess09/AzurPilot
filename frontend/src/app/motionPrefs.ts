/**
 * @fileoverview 动效调试台（开发者工具）偏好：速度倍率 / 力度档位 / 减少动效模拟。
 *
 * 与 topbarPrefs 同模式：模块加载即生效（首帧正确）、localStorage 持久、subscribe/read 供
 * useSyncExternalStore 使用；仅为开发与验收工具，不写入项目配置文件，影响范围是当前浏览器。
 */

type MotionSpeed = 1 | 2 | 4
type MotionStrength = 'standard' | 'strong'
type MotionPrefs = {speed: MotionSpeed; strength: MotionStrength; reduced: boolean}

const SPEED_KEY = 'azurpilot.motion.speed'
const STRENGTH_KEY = 'azurpilot.motion.strength'
const REDUCED_KEY = 'azurpilot.motion.reduced'

function readStored(): MotionPrefs {
  try {
    const rawSpeed = localStorage.getItem(SPEED_KEY)
    const speed = Number(rawSpeed)
    const strength = localStorage.getItem(STRENGTH_KEY)
    return {
      speed: rawSpeed !== null && (speed === 1 || speed === 2 || speed === 4) ? (speed as MotionSpeed) : 2,
      strength: strength === 'standard' ? 'standard' : 'strong',
      reduced: localStorage.getItem(REDUCED_KEY) === '1',
    }
  } catch { /* 存储被禁时回落默认值，调试台不依赖持久化。 */ return {speed: 2, strength: 'strong', reduced: false} }
}

const browser = typeof window !== 'undefined' && typeof document !== 'undefined'

// 全局倍率走 CSS 变量：motion.css 里所有时长都是 calc(基础值 * --motion-speed)，默认 0.5× 对应倍率 2。
// 力度档位与「减少动效模拟」走 data 属性，由 motion.css 对应选择器消费。
function apply(next: MotionPrefs) {
  if (!browser) return
  const root = document.documentElement
  if (next.speed === 2) root.style.removeProperty('--motion-speed')
  else root.style.setProperty('--motion-speed', String(next.speed))
  if (next.strength === 'strong') root.dataset.motionStrength = 'strong'
  else delete root.dataset.motionStrength
  if (next.reduced) root.dataset.motionReduced = '1'
  else delete root.dataset.motionReduced
}

let state: MotionPrefs = readStored()
apply(state)

const listeners = new Set<() => void>()

/** 订阅偏好变化；返回取消订阅的函数。 */
export const subscribeMotionPrefs = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export const readMotionPrefs = () => state

/** 简约主题、系统开关和调试模拟均可关闭装饰动效。 */
export const motionReducedActive = () =>
  !browser || state.reduced || document.documentElement.dataset.theme === 'minimal' ||
  (typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches)

/** 当前速度倍率：用于 JS 侧计时（如转场类清除定时器）。 */
export const motionSpeedValue = () => state.speed

function commit(next: MotionPrefs) {
  state = next
  apply(next)
  try {
    localStorage.setItem(SPEED_KEY, String(next.speed))
    localStorage.setItem(STRENGTH_KEY, next.strength)
    localStorage.setItem(REDUCED_KEY, next.reduced ? '1' : '0')
  } catch { /* 存储不可用时本次会话内生效。 */ }
  listeners.forEach(listener => listener())
}

export const setMotionSpeed = (speed: MotionSpeed) => commit({...state, speed})
export const setMotionStrength = (strength: MotionStrength) => commit({...state, strength})
export const setMotionReduced = (reduced: boolean) => commit({...state, reduced})
/** 恢复默认偏好：倍率 2（0.5×）、力度强、关闭减弱模拟。 */
export const resetMotionPrefs = () => commit({speed: 2, strength: 'strong', reduced: false})
