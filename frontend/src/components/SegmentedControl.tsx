/**
 * @fileoverview 分段选择器控件组件。
 */

import { useRef, type ReactNode } from 'react'

type Option<T extends string> = {value: T; label: ReactNode}

/** 共用监控页的分段样式，支持方向键切换条目。 */
export function SegmentedControl<T extends string>({label, value, options, onChange, className = ''}: {
  label: string
  value: T
  options: Option<T>[]
  onChange: (value: T) => void
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  return <div ref={ref} className={`monitor-segmented ${className}`.trim()} role="tablist" aria-label={label}>
    {options.map((option, index) => <button type="button" key={option.value} role="tab" aria-selected={value === option.value} tabIndex={value === option.value ? 0 : -1} onClick={() => onChange(option.value)} onKeyDown={event => {
      const next = event.key === 'ArrowRight' ? (index + 1) % options.length : event.key === 'ArrowLeft' ? (index - 1 + options.length) % options.length : event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : -1
      if (next < 0) return
      event.preventDefault()
      onChange(options[next].value)
      const button = ref.current?.querySelectorAll<HTMLButtonElement>('button')[next]
      button?.focus({preventScroll: true})
      button?.scrollIntoView({block: 'nearest', inline: 'nearest'})
    }}>{option.label}</button>)}
  </div>
}
