/**
 * @fileoverview 下拉选择器：由 shadcn/ui 的 Select 承载。
 *
 * 对外 API 与原生 `<select>` 保持一致（`value` + `onChange` + `<option>` 子节点），
 * 调用点不用改；键盘、类型检索、碰撞翻转、焦点管理与菜单结构全部交给组件。
 * Radix 不允许空字符串作为选项值，内部用哨兵映射，对外仍是空串。
 */

import { useId, useRef, useState, type ComponentProps, type ReactElement, type ReactNode } from 'react'
import { Select as ShadcnSelect, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from './ui/select'
import { useApp } from '../app/context'

const EMPTY = '\u0000empty'

/** 调用点用 `JSON.stringify` 传值，兜底显示时不要把引号带到界面上。 */
function plainValue(value: string) {
  if (value.length > 1 && value.startsWith('"') && value.endsWith('"')) {
    try {
      const parsed: unknown = JSON.parse(value)
      if (typeof parsed === 'string') return parsed
    } catch { /* 不是合法的 JSON 字符串就原样显示。 */ }
  }
  return value
}

type Item = {value: string; label: ReactNode; disabled: boolean}
type Group = {label: ReactNode; items: Item[]}

function isElement(node: ReactNode): node is ReactElement<{children?: ReactNode; value?: unknown; disabled?: boolean; label?: ReactNode}> {
  return typeof node === 'object' && node !== null && 'props' in node
}

/** 把 `<option>` / `<optgroup>` 子节点拆成可渲染的两级结构。
 *
 * `{cond && <option/>}` 会留下 false，`{options.map(...)}` 会留下**嵌套数组**；
 * 只遍历一层就会把整组映射出来的选项全丢掉 —— 触发器的 label 查不到，
 * 只能回退显示 `JSON.stringify` 过的原始值，屏幕上就是带引号的 `"normal"`。
 * 所以这里按数组递归摊平。 */
function parse(children: ReactNode) {
  const entries: Array<Item | Group> = []

  function collect(nodes: ReactNode): Item[] {
    const out: Item[] = []
    for (const node of Array.isArray(nodes) ? nodes : [nodes]) {
      if (Array.isArray(node)) { out.push(...collect(node)); continue }
      if (!isElement(node) || node.type === 'optgroup') continue
      out.push({value: String(node.props.value ?? ''), label: node.props.children, disabled: Boolean(node.props.disabled)})
    }
    return out
  }

  function walk(nodes: ReactNode) {
    for (const node of Array.isArray(nodes) ? nodes : [nodes]) {
      if (Array.isArray(node)) { walk(node); continue }
      if (!isElement(node)) continue
      if (node.type === 'optgroup') {
        entries.push({label: node.props.label, items: collect(node.props.children)})
        continue
      }
      entries.push({value: String(node.props.value ?? ''), label: node.props.children, disabled: Boolean(node.props.disabled)})
    }
  }

  walk(children)
  return {entries, items: entries.flatMap(entry => ('items' in entry ? entry.items : [entry]))}
}

export function Select({children, id, className, style, disabled, autoFocus, openOnFocus = false, ...props}: ComponentProps<'select'> & {openOnFocus?: boolean}) {
  const {ui} = useApp()
  const generatedId = useId()
  const controlId = id ?? generatedId
  const trigger = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  // 菜单渲染在触发器的顶层容器里：普通页面挂 body，
  // 对话框里必须挂进 dialog 本身（它处在 top layer，挂 body 会被压在遮罩后面）。
  const [container, setContainer] = useState<HTMLElement>()
  const toggleOpen = (next: boolean) => {
    if (next) setContainer((trigger.current?.closest('dialog') as HTMLElement | null) ?? document.body)
    setOpen(next)
  }
  // 指针从触发器移到菜单要跨一段间隙，立刻收起会让鼠标还没落上去就关掉。
  const hoverClose = useRef<number | undefined>(undefined)
  const cancelHoverClose = () => {if (hoverClose.current !== undefined) {window.clearTimeout(hoverClose.current); hoverClose.current = undefined}}
  const scheduleHoverClose = () => {
    if (!openOnFocus) return
    cancelHoverClose()
    hoverClose.current = window.setTimeout(() => toggleOpen(false), 180)
  }

  const {entries, items} = parse(children)
  const current = props.value === undefined || props.value === null ? '' : String(props.value)
  const label = current === '' ? undefined : items.find(item => item.value === current)?.label
  const placeholder = String(items[0]?.label ?? ui('common.select'))

  function change(next: string) {
    const value = next === EMPTY ? '' : next
    if (value === current) return
    // 调用点按原生 select 的事件形状取值，这里给出等价对象。
    props.onChange?.({target: {value}} as unknown as React.ChangeEvent<HTMLSelectElement>)
  }

  return <span className={`select-control ${className ?? ''}`} style={style}>
    <ShadcnSelect
      value={current === '' ? EMPTY : current}
      onValueChange={change}
      disabled={disabled}
      required={props.required}
      name={props.name}
      open={open}
      onOpenChange={toggleOpen}
    >
      <SelectTrigger
        id={controlId}
        ref={trigger}
        disabled={disabled}
        autoFocus={autoFocus}
        aria-label={props['aria-label']}
        aria-labelledby={props['aria-labelledby']}
        aria-describedby={props['aria-describedby']}
        aria-invalid={props['aria-invalid']}
        onFocus={event => {if (openOnFocus && event.currentTarget.matches(':focus-visible')) toggleOpen(true)}}
        onPointerEnter={() => {if (openOnFocus) {cancelHoverClose(); toggleOpen(true)}}}
        onPointerLeave={scheduleHoverClose}
      >
        <SelectValue placeholder={current === '' ? placeholder : undefined}>
          {typeof label === 'string' || typeof label === 'number' ? String(label) : plainValue(current)}
        </SelectValue>
      </SelectTrigger>
      <SelectContent
        position="popper"
        sideOffset={6}
        collisionPadding={8}
        container={container}
        onPointerEnter={cancelHoverClose}
        onPointerLeave={scheduleHoverClose}
      >
        {entries.map((entry, index) => 'items' in entry
          ? <SelectGroup key={`group-${index}`}>
              <SelectLabel>{entry.label}</SelectLabel>
              {entry.items.map(item => <Option key={item.value} item={item}/>)}
            </SelectGroup>
          : <Option key={entry.value} item={entry}/>)}
      </SelectContent>
    </ShadcnSelect>
  </span>
}

function Option({item}: {item: Item}) {
  return <SelectItem value={item.value === '' ? EMPTY : item.value} disabled={item.disabled}>
    {item.label}
  </SelectItem>
}
