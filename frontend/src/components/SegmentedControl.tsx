/**
 * @fileoverview 分段选择器控件组件。
 */

import { useRef, type ReactNode } from 'react'

type Option<T extends string> = {value: T; label: ReactNode}

/** 共用监控页的分段样式，支持方向键切换条目。 */
export function SegmentedControl<T extends string>({label, value, options, onChange, onItemContextMenu, onItemMove, itemClassName, className = '', trailing}: {
  label: string
  value: T
  options: Option<T>[]
  onChange: (value: T) => void
  className?: string
  /** 逐项的右键回调。 */
  onItemContextMenu?: (value: T) => void
  /** 逐项的方向键移动回调，方向键配合 Alt 时触发。 */
  onItemMove?: (value: T, delta: number) => void
  /** 逐项的附加类名，用于标记禁用这类状态。 */
  itemClassName?: (value: T) => string
  /** 固定排在条目之后的附加控件，不参与逐项回调与键盘导航。 */
  trailing?: ReactNode
}) {
  const ref = useRef<HTMLDivElement>(null)
  return <div ref={ref} className={`monitor-segmented ${className}`.trim()} role="tablist" aria-label={label}>
    {options.map((option, index) => <button type="button" key={option.value} role="tab" className={itemClassName?.(option.value)} onContextMenu={onItemContextMenu ? event => {event.preventDefault(); onItemContextMenu(option.value)} : undefined} aria-selected={value === option.value} tabIndex={value === option.value ? 0 : -1} onClick={() => onChange(option.value)} onKeyDown={event => {
      if (event.altKey && onItemMove && (event.key === 'ArrowRight' || event.key === 'ArrowLeft')) {
        event.preventDefault()
        onItemMove(option.value, event.key === 'ArrowRight' ? 1 : -1)
        return
      }
      const next = event.key === 'ArrowRight' ? (index + 1) % options.length : event.key === 'ArrowLeft' ? (index - 1 + options.length) % options.length : event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : -1
      if (next < 0) return
      event.preventDefault()
      onChange(options[next].value)
      const button = ref.current?.querySelectorAll<HTMLButtonElement>('button')[next]
      button?.focus({preventScroll: true})
      button?.scrollIntoView({block: 'nearest', inline: 'nearest'})
    }}>{option.label}</button>)}
  {trailing}
  </div>
}
