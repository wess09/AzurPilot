/**
 * @fileoverview 仪表盘资源（石油、物资、魔方等）统计卡片组件。
 */

import { Fragment, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import { Box, GripVertical, Plus, X } from 'lucide-react'
import type { Resource } from '../api/types'
import { useApp } from '../app/context'
import { readDashboardPrefs, subscribeDashboardPrefs } from '../app/dashboardPrefs'
import type { UiKey } from '../i18n'

const resourceLabels: Record<string, UiKey> = {Oil: 'resource.Oil', Coin: 'resource.Coin', Gem: 'resource.Gem', Cube: 'resource.Cube', Pt: 'resource.Pt', ActionPoint: 'resource.ActionPoint', YellowCoin: 'resource.YellowCoin', PurpleCoin: 'resource.PurpleCoin', Core: 'resource.Core', Medal: 'resource.Medal', Merit: 'resource.Merit', GuildCoin: 'resource.GuildCoin', Chip: 'resource.Chip', Distance: 'resource.Distance', ActionAsset: 'resource.ActionAsset'}
const iconBase = import.meta.env.BASE_URL
const iconImages: Record<string, string> = {
  Oil: `${iconBase}oil.webp`,
  Coin: `${iconBase}gold.webp`,
  Gem: `${iconBase}diamond.webp`,
  Cube: `${iconBase}cube.webp`,
  Pt: `${iconBase}pt.webp`,
  ActionPoint: `${iconBase}guild_coin.webp`,
  YellowCoin: `${iconBase}supply_token.webp`,
  PurpleCoin: `${iconBase}special_token.webp`,
  Core: `${iconBase}core_data.webp`,
  Medal: `${iconBase}honor_medal.webp`,
  Merit: `${iconBase}merit.webp`,
  GuildCoin: `${iconBase}stamina.webp`,
  Chip: `${iconBase}cognitive_chips.webp`,
  Distance: `${iconBase}nautical_miles.webp`,
  ActionAsset: `${iconBase}action_asset.webp`,
}

// 行动力越高换越大的狗图，四档从高到低取第一张命中的；未达第一档不换图。
const dogIconTiers = [
  {threshold: 12000, icon: `${iconBase}dog_king.webp`},
  {threshold: 10000, icon: `${iconBase}dog_large.webp`},
  {threshold: 8000, icon: `${iconBase}dog_medium.webp`},
  {threshold: 6000, icon: `${iconBase}dog_small.webp`},
]

/**
 * 行动力卡片的狗头图：总行动力过档才给图标，档位从高到低取第一张命中的。
 * record 为 2020-01-01 占位时间戳表示尚未真正同步过，此时不换图。
 */
export function actionPointDogIcon(resource?: Resource): string | undefined {
  if (!resource || resource.name !== 'ActionPoint') return undefined
  if (resource.record?.startsWith('2020-01-01')) return undefined
  const value = typeof resource.value === 'number' && Number.isFinite(resource.value) ? resource.value : 0
  const total = typeof resource.total === 'number' && Number.isFinite(resource.total) && resource.total >= value
    ? resource.total
    : value
  return dogIconTiers.find(tier => total > tier.threshold)?.icon
}

function ResourceIcon({resourceKey, size = 32, src}: {resourceKey: string; size?: number; src?: string}) {
  const imageSrc = src ?? iconImages[resourceKey]
  return imageSrc ? <img className="resource-icon-image" src={imageSrc} alt="" width={size} height={size} draggable={false}/> : <Box size={Math.round(size * .62)}/>
}
/** 仪表盘卡片的默认选择；「恢复默认」按钮写回的就是这份清单。 */
export const defaultResourceKeys = ['Oil', 'Coin', 'Gem', 'Cube', 'Distance', 'ActionAsset']

/** 返回把 fromKey 移到 toKey 原所在位置后的新顺序数组；两个键相同或任一不存在时原样返回。 */
export function moveResourceKey(keys: string[], fromKey: string, toKey: string): string[] {
  if (fromKey === toKey) return keys
  const from = keys.indexOf(fromKey)
  const to = keys.indexOf(toKey)
  if (from < 0 || to < 0) return keys
  const next = [...keys]
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved)
  return next
}

function ResourceValue({value, suffix}: {value: string; suffix?: string}) {
  return <div className="resource-value">
    <span className="resource-value-content"><span>{value}</span>{suffix && <small>/ {suffix}</small>}</span>
  </div>
}

// 记录时间：当日给时分秒，跨日给月日与小时；超过一年标记为过久。
const RECORD_STALE_MS = 365 * 24 * 60 * 60 * 1000

function recordText(value: string | undefined): {text: string; stale: boolean} {
  const at = value ? new Date(value) : null
  if (!at || Number.isNaN(at.getTime())) return {text: '', stale: false}
  if (Date.now() - at.getTime() > RECORD_STALE_MS) return {text: '', stale: true}
  const pad = (count: number) => String(count).padStart(2, '0')
  const now = new Date()
  const sameDay = at.getFullYear() === now.getFullYear() && at.getMonth() === now.getMonth() && at.getDate() === now.getDate()
  const text = sameDay ? `${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}` : `${pad(at.getMonth() + 1)}-${pad(at.getDate())}-${pad(at.getHours())}`
  return {text, stale: false}
}

/**
 * 仪表盘资源卡片网格：按用户选定顺序渲染资源卡，支持合并大卡、卡片/文字自适应等偏好。
 * @param resources 最近一次同步的资源快照；选定键里没有的按「等待同步」渲染。
 * @param selected 展示的资源键，顺序即卡片排列顺序。
 */
export function ResourceCards({resources, selected}: {resources: Resource[]; selected: string[]}) {
  const {ui} = useApp()
  const prefs = useSyncExternalStore(subscribeDashboardPrefs, readDashboardPrefs, readDashboardPrefs)
  const gridRef = useRef<HTMLDivElement>(null)
  const mergedRef = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const grid = gridRef.current
    if (!grid) return
    const contents = [...grid.querySelectorAll<HTMLElement>('.resource-value-content')]
    const fit = () => {
      // 整组先读宽度、恢复主题字号，再量自然宽度并写入结果，避免逐卡触发同步布局。
      const widths = contents.map(content => content.parentElement?.clientWidth ?? 0)
      for (const content of contents) content.style.removeProperty('font-size')
      const natural = contents.map(content => content.getBoundingClientRect().width)
      const shrunk = contents.flatMap((content, index) => {
        const width = widths[index]
        if (width <= 0 || natural[index] <= width) return []
        const scale = Math.max(0, width - 4) / natural[index]
        content.style.fontSize = `${scale}em`
        return [{content, width, scale}]
      })
      // 字形栅格化会使缩放后的字宽与比例估算有偏差，只对仍溢出的数值修正一次。
      const rendered = shrunk.map(({content}) => content.getBoundingClientRect().width)
      shrunk.forEach(({content, width, scale}, index) => {
        if (rendered[index] > width) content.style.fontSize = `${scale * Math.max(0, width - 4) / rendered[index]}em`
      })
    }
    fit()
    let frame: number | undefined
    const observer = new ResizeObserver(() => {
      if (frame !== undefined) return
      frame = requestAnimationFrame(() => {
        frame = undefined
        fit()
      })
    })
    for (const content of contents) {
      observer.observe(content)
      if (content.parentElement) observer.observe(content.parentElement)
    }
    return () => {
      observer.disconnect()
      if (frame !== undefined) cancelAnimationFrame(frame)
    }
  }, [selected, prefs.merged])

  // 卡片适应：按容器宽度算一行放得下几张，列数即「卡片数与一排容量」的较小者 ——
  // 溢出到第二排以后时末排沿用第一排尺寸，总数不足一排时列数就等于卡片数因而仍均分。
  useLayoutEffect(() => {
    const grid = gridRef.current
    // 通用卡片把卡片包成一张大卡，列数要算在真正装卡片的那一层上。
    const target = prefs.merged ? mergedRef.current : grid
    if (!grid || !target || !(prefs.fitCards || prefs.merged)) return
    const fit = () => {
      const style = getComputedStyle(target)
      const gap = parseFloat(style.columnGap) || 0
      const min = parseFloat(style.getPropertyValue('--resource-card-min')) || 0
      if (!target.clientWidth || !min) return
      const perRow = Math.max(1, Math.floor((target.clientWidth + gap) / (min + gap)))
      target.style.gridTemplateColumns = `repeat(${Math.min(selected.length, perRow)}, minmax(0, 1fr))`
    }
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(target)
    return () => { observer.disconnect(); target.style.gridTemplateColumns = '' }
  }, [prefs.fitCards, prefs.merged, selected.length])

  const entries = selected.map((key, index) => {
    const resource = resources.find(item => item.name === key)
    // record 为 2020-01-01 占位时间戳表示尚未真正同步过，按无记录处理。
    const recorded = resource?.record && !resource.record.startsWith('2020-01-01')
    const labelKey = resourceLabels[key]
    const label = labelKey ? ui(labelKey) : resource?.label ?? key
    const limit = resource?.limit
    const total = resource?.total
    const showLimit = typeof limit === 'number' && limit > 0
    const showTotal = !!recorded && !showLimit && resource?.name === 'ActionPoint' && typeof resource.value === 'number' && typeof total === 'number' && Number.isFinite(total) && total >= resource.value
    const value = resource?.value
    const currentText = recorded && value != null ? value.toLocaleString() : '—'
    const totalText = showTotal ? (total as number).toLocaleString() : undefined
    // 总行动力优先时总量与当前值互换；行动力以外的字段不受影响。
    const displayValue = prefs.totalFirst && totalText ? totalText : currentText
    const suffix = prefs.totalFirst && totalText ? currentText : recorded && showLimit ? limit.toLocaleString() : totalText
    const record = recordText(resource?.record)
    const foot = recorded ? (record.stale ? ui('resource.recordedTooOld') : record.text) : ui('resource.waitingSync')
    const iconSrc = prefs.dogIcon ? actionPointDogIcon(resource) : undefined
    return {key, index, label, displayValue, suffix, foot, iconSrc}
  })

  const className = ['resource-grid',
    (prefs.fitCards || prefs.merged) && 'resource-fit',
    prefs.fitText && 'resource-fit-text',
    prefs.dense && 'resource-dense'].filter(Boolean).join(' ')

  // 两种排法共用同一段卡片内部渲染，也都套在 .resource-card-body 里——那张二级面。
  const cardBody = (entry: typeof entries[number]) => <>
    <div className="resource-heading"><span>{entry.label}</span><div className="resource-image-wrap"><ResourceIcon resourceKey={entry.key} size={32} src={entry.iconSrc}/></div></div>
    <ResourceValue value={entry.displayValue} suffix={entry.suffix}/>
    <div className="resource-foot">{entry.foot}</div>
  </>

  return <div className={className} ref={gridRef}>{prefs.merged
    ? <section className="resource-card resource-merged">
      <div className="resource-card-body" ref={mergedRef}>{entries.map(entry => <section key={entry.key} className={`resource-merged-item resource-${entry.index % 4}`}>{cardBody(entry)}</section>)}</div>
    </section>
    : entries.map(entry => <section key={entry.key} className={`resource-card resource-${entry.index % 4}`}>
      <div className="resource-card-body">{cardBody(entry)}</div>
    </section>)}</div>
}
/**
 * 仪表盘卡片的编辑面板：上半是已选卡片的拖拽排序/移除列表，「添加」展开未展示资源的选择网格。
 * 两个区可跨区拖动：拖进编辑区即加卡，拖出编辑区即移除。
 */
export function ResourceSettings({resources, selected, onChange}: {resources: Resource[]; selected: string[]; onChange: (keys: string[]) => void}) {
  const {ui} = useApp()
  const prefs = useSyncExternalStore(subscribeDashboardPrefs, readDashboardPrefs, readDashboardPrefs)
  const ap = resources.find(item => item.name === 'ActionPoint')
  const dogIcon = (name: string, item?: Resource) => name === 'ActionPoint' && prefs.dogIcon
    ? actionPointDogIcon(item ?? ap)
    : undefined
  const [pickerOpen, setPickerOpen] = useState(false)
  const [draggingKey, setDraggingKey] = useState<string | null>(null)
  const [dragOrder, setDragOrder] = useState<string[] | null>(null)
  const editorRef = useRef<HTMLDivElement>(null)
  const editorFrameRef = useRef<HTMLDivElement | null>(null)
  const dragOrderRef = useRef<string[] | null>(null)
  const dragPointerRef = useRef<number | null>(null)
  const dragKeyRef = useRef<string | null>(null)
  const dragAnchorRef = useRef<{key: string; card: HTMLElement; pointerX: number; pointerY: number; movedX: number; movedY: number; left: number; top: number} | null>(null)
  const releasedKeyRef = useRef<string | null>(null)
  const pickerDragRef = useRef<string | null>(null)
  const pickerStartRef = useRef<{card: HTMLButtonElement; pointerId: number; x: number; y: number; movedX: number; movedY: number; left: number; top: number} | null>(null)
  const pickerGridRef = useRef<HTMLDivElement | null>(null)
  const pickerFrameRef = useRef<HTMLDivElement | null>(null)
  const pickerEditorRef = useRef<{left: number; top: number; right: number; bottom: number}[] | null>(null)
  const pickerTargetsRef = useRef<{left: number; top: number; right: number; bottom: number}[] | null>(null)
  const pickerSlotsRef = useRef<{key: string; left: number; top: number; right: number; bottom: number}[]>([])
  const pickerRectsRef = useRef<Map<string, {left: number; top: number}>>(new Map())
  const pickerFramesRef = useRef<number[]>([])
  const pickerOrderRef = useRef<string[] | null>(null)
  const [pickerOrder, setPickerOrder] = useState<string[] | null>(null)
  const [editorDropIndex, setEditorDropIndex] = useState<number | null>(null)
  const [pickerDropIndex, setPickerDropIndex] = useState<number | null>(null)
  const slotsRef = useRef<{key: string; left: number; top: number; right: number; bottom: number}[]>([])
  const rectsRef = useRef<Map<string, {left: number; top: number}>>(new Map())
  const framesRef = useRef<number[]>([])
  const available = resources.filter(resource => !selected.includes(resource.name))
  const displayed = dragOrder ?? selected
  const pickerSequence = pickerOrder ?? available.map(item => item.name)
  const pickerShown = pickerSequence.filter(key => available.some(item => item.name === key))

  function captureRects() {
    const rects = new Map<string, DOMRect>()
    editorRef.current?.querySelectorAll<HTMLElement>('[data-resource-key]').forEach(card => rects.set(card.dataset.resourceKey ?? '', card.getBoundingClientRect()))
    return rects
  }

  // 换位动画的基准取布局位置：卡片身上的位移属于绘制结果，不是布局。
  function captureLayout() {
    const positions = new Map<string, {left: number; top: number}>()
    editorRef.current?.querySelectorAll<HTMLElement>('[data-resource-key]').forEach(card => positions.set(card.dataset.resourceKey ?? '', {left: card.offsetLeft, top: card.offsetTop}))
    return positions
  }

  // 空位插进某一区会让它增减行、把另一区整块推移：这类变化不经过指针，布局一提交就要重算跟手。
  useLayoutEffect(() => {
    if (pickerDragRef.current) followPickerPointer()
    if (dragAnchorRef.current) followPointer()
  }, [editorDropIndex, pickerDropIndex])

  // 跟手：卡片停在按下时的位置加指针位移处。减去卡片当前布局位置时要带上容器的视口原点——
  // 跨区拖动会让容器增减行，未展示区随之整体位移，省掉这一段卡片就会错开一行。
  function moveCardTo(card: HTMLElement, viewportX: number, viewportY: number) {
    const origin = card.offsetParent instanceof HTMLElement ? card.offsetParent.getBoundingClientRect() : {left: 0, top: 0}
    card.style.transition = 'none'
    card.style.translate = `${viewportX - origin.left - card.offsetLeft}px ${viewportY - origin.top - card.offsetTop}px`
  }

  function followPointer() {
    const anchor = dragAnchorRef.current
    if (!anchor) return
    moveCardTo(anchor.card, anchor.left + anchor.movedX - anchor.pointerX, anchor.top + anchor.movedY - anchor.pointerY)
  }

  function followPickerPointer() {
    const start = pickerStartRef.current
    if (!start) return
    moveCardTo(start.card, start.left + start.movedX - start.x, start.top + start.movedY - start.y)
  }

  // 落点虚框钉在被拖卡片的格子上：卡片跟着指针走，虚框标出它会落在哪一格。
  function markDropFrame(frame: HTMLDivElement | null, card?: HTMLElement) {
    if (!frame) return
    if (!card) {frame.style.display = 'none'; return}
    frame.style.display = 'block'
    frame.style.left = `${card.offsetLeft}px`
    frame.style.top = `${card.offsetTop}px`
    frame.style.width = `${card.offsetWidth}px`
    frame.style.height = `${card.offsetHeight}px`
  }

  // 换位用 FLIP：重排后先把卡片移回原位，下一帧再放开，位移走独立的 translate 属性，
  // 与拖起态的缩放互不覆盖；过渡结束后清掉内联值，落定不留痕迹。
  useLayoutEffect(() => {
    const before = rectsRef.current
    const moved: HTMLElement[] = []
    editorRef.current?.querySelectorAll<HTMLElement>('[data-resource-key]').forEach(card => {
      // 被拖动的卡片不参与换位动画，改为按新布局重算跟手位移并重新捕获指针；
      // 刚松手的那张只跳过动画。
      if (card.dataset.resourceKey === dragKeyRef.current) {
        followPointer()
        markDropFrame(editorFrameRef.current, card)
        const pointerId = dragPointerRef.current
        if (pointerId !== null && !card.hasPointerCapture(pointerId)) card.setPointerCapture(pointerId)
        return
      }
      if (card.dataset.resourceKey === releasedKeyRef.current) return
      const previous = before.get(card.dataset.resourceKey ?? '')
      if (!previous) return
      const dx = previous.left - card.offsetLeft
      const dy = previous.top - card.offsetTop
      if (!dx && !dy) return
      // 起点值瞬时到位，随后的放开才由过渡接管。
      card.style.transition = 'none'
      card.style.translate = `${dx}px ${dy}px`
      moved.push(card)
    })
    rectsRef.current = captureLayout()
    releasedKeyRef.current = null
    if (!moved.length) return
    // 放开落在下一帧：中间隔着一次样式更新，过渡才会成立。
    framesRef.current.push(requestAnimationFrame(() => {
      framesRef.current.push(requestAnimationFrame(() => {
        moved.forEach(card => {
          card.style.transition = ''
          card.style.translate = 'none'
          card.addEventListener('transitionend', event => {
            if (event.propertyName === 'translate' && card.style.translate === 'none') card.style.translate = ''
          }, {once: true})
        })
      }))
    }))
  }, [dragOrder, editorDropIndex])

  // 换位用 FLIP：重排后先把卡片移回原位，下一帧再放开，位移走独立的 translate 属性。
  // 被拖动的卡片不参与换位动画，跟手位移由指针直接驱动。
  useLayoutEffect(() => {
    const before = pickerRectsRef.current
    const moved: HTMLElement[] = []
    pickerGridRef.current?.querySelectorAll<HTMLElement>('[data-resource-key]').forEach(card => {
      // 被拖动的卡片不参与换位动画，改为按新布局重算跟手位移并重新捕获指针；
      // 换位会移动这张卡的 DOM 节点，指针捕获随之丢失。
      if (card.dataset.resourceKey === pickerDragRef.current) {
        followPickerPointer()
        markDropFrame(pickerFrameRef.current, card)
        const start = pickerStartRef.current
        if (start && !card.hasPointerCapture(start.pointerId)) card.setPointerCapture(start.pointerId)
        return
      }
      const previous = before.get(card.dataset.resourceKey ?? '')
      if (!previous) return
      const dx = previous.left - card.offsetLeft
      const dy = previous.top - card.offsetTop
      if (!dx && !dy) return
      card.style.transition = 'none'
      card.style.translate = `${dx}px ${dy}px`
      moved.push(card)
    })
    pickerRectsRef.current = capturePickerLayout()
    if (!moved.length) return
    pickerFramesRef.current.push(requestAnimationFrame(() => {
      pickerFramesRef.current.push(requestAnimationFrame(() => {
        moved.forEach(card => {
          card.style.transition = ''
          card.style.translate = 'none'
          card.addEventListener('transitionend', event => {
            if (event.propertyName === 'translate' && card.style.translate === 'none') card.style.translate = ''
          }, {once: true})
        })
      }))
    }))
  }, [pickerOrder, pickerDropIndex])

  useEffect(() => () => {
    pickerFramesRef.current.forEach(cancelAnimationFrame)
    pickerFramesRef.current = []
    framesRef.current.forEach(cancelAnimationFrame)
    framesRef.current = []
  }, [])

  // 上层把顺序写回同序后交还显示权：此时两边一致，DOM 不再变化。
  useEffect(() => {
    if (dragOrder && dragOrder.length === selected.length && dragOrder.every((key, index) => key === selected[index])) setDragOrder(null)
  }, [dragOrder, selected])

  // 未展示区与显示区同构：按下量一次布局与槽位，重排后按同一份快照算反向位移。
  function capturePickerLayout() {
    const layout = new Map<string, {left: number; top: number}>()
    pickerGridRef.current?.querySelectorAll<HTMLElement>('[data-resource-key]').forEach(card => {
      layout.set(card.dataset.resourceKey ?? '', {left: card.offsetLeft, top: card.offsetTop})
    })
    return layout
  }
  function capturePickerSlots() {
    return [...pickerGridRef.current?.querySelectorAll<HTMLElement>('[data-resource-key]') ?? []].map(card => {
      const rect = card.getBoundingClientRect()
      return {key: card.dataset.resourceKey ?? '', left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom}
    })
  }

  // 加入显示区：给了落点就插到该位置，否则排到最后。
  function add(key: string, index: number | null = null) {
    if (selected.includes(key)) return
    const next = [...selected]
    next.splice(index ?? next.length, 0, key)
    onChange(next)
  }
  function remove(key: string) {
    onChange(selected.filter(item => item !== key))
  }
  function boxOf(element: Element): {left: number; top: number; right: number; bottom: number} {
    const rect = element.getBoundingClientRect()
    return {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom}
  }

  function inside(box: {left: number; top: number; right: number; bottom: number}, x: number, y: number) {
    return x >= box.left && x <= box.right && y >= box.top && y <= box.bottom
  }

  // 是否落在容器内：容器在拖动期间会增减行而移动，这里按当前位置判，不用快照。
  function inArea(element: Element | null | undefined, x: number, y: number) {
    return !!element && inside(boxOf(element), x, y)
  }

  // 跨区落点一律用按下时的快照：空位插进容器会让容器多一行，用实时位置判定会自己追自己。
  function captureEditorTargets() {
    const editor = editorRef.current
    return editor ? [...editor.querySelectorAll<HTMLElement>('[data-resource-key]')].map(boxOf) : null
  }

  // 落点：指针压在哪张卡上就插到它的位置，压在空白处则排到最后。
  function editorDropTarget(x: number, y: number) {
    return pickerEditorRef.current ? dropIndexAt(pickerEditorRef.current, x, y) : displayed.length
  }

  function pickerDropTarget(x: number, y: number) {
    return pickerTargetsRef.current ? dropIndexAt(pickerTargetsRef.current, x, y) : pickerShown.length
  }

  // 落点：取最近的那个格子，指针在它下半（同行在右半）时插到它后面；间隙按最近格子算，序号不会在格子与末尾之间来回跳。
  function dropIndexAt(boxes: {left: number; top: number; right: number; bottom: number}[], x: number, y: number) {
    if (!boxes.length) return 0
    let best = 0
    let bestDist = Infinity
    boxes.forEach((box, index) => {
      const dx = x - (box.left + box.right) / 2
      const dy = y - (box.top + box.bottom) / 2
      const dist = dx * dx + dy * dy
      if (dist < bestDist) {bestDist = dist; best = index}
    })
    const box = boxes[best]
    const inRow = y >= box.top && y <= box.bottom
    return y > (box.top + box.bottom) / 2 || (inRow && x > (box.left + box.right) / 2) ? best + 1 : best
  }

  function finishDrag(pointerId: number, apply: boolean) {
    if (dragPointerRef.current !== pointerId) return
    const next = dragOrderRef.current
    // 松手结算：跟手的位移交回过渡，卡片滑入所在格子。
    const anchor = dragAnchorRef.current
    if (anchor) {
      releasedKeyRef.current = anchor.key
      anchor.card.style.transition = ''
      anchor.card.style.translate = 'none'
      anchor.card.addEventListener('transitionend', event => {
        if (event.propertyName === 'translate' && anchor.card.style.translate === 'none') anchor.card.style.translate = ''
      }, {once: true})
    }
    dragAnchorRef.current = null
    dragPointerRef.current = null
    dragOrderRef.current = null
    dragKeyRef.current = null
    slotsRef.current = []
    setDraggingKey(null)
    setPickerDropIndex(null)
    markDropFrame(editorFrameRef.current)
    if (apply) {
      // 松手落在未展示区，这张卡就此移出仪表盘；其余情况按拖动后的顺序提交。
      const picker = editorRef.current?.parentElement?.querySelector('.resource-picker')
      const dropped = !!(anchor && inArea(picker, anchor.movedX, anchor.movedY))
      if (dropped) {
        const order = pickerShown
        const index = pickerDropIndex ?? order.length
        setPickerOrder([...order.slice(0, index), anchor.key, ...order.slice(index)])
        remove(anchor.key)
        setDragOrder(null)
      }
      else if (next && next.some((key, index) => key !== selected[index])) onChange(next)
    } else setDragOrder(null)
  }

  return <div className="resource-settings">
    <div className="resource-settings-heading"><div><strong>{ui('resource.cards')}</strong><span>{ui('resource.cardsHint')}</span></div><button type="button" className="button" onClick={() => onChange(defaultResourceKeys)}>{ui('resource.restoreDefault')}</button></div>
    <div className="resource-card-editor" ref={editorRef}>
      {displayed.map((key, index) => {
        const resource = resources.find(item => item.name === key)
          const labelKey = resourceLabels[key]
          const label = labelKey ? ui(labelKey) : resource?.label ?? key
        return <Fragment key={key}>{editorDropIndex === index && <div className="resource-editor-card resource-drop-slot" aria-hidden="true"/>}
          <div data-resource-key={key} className={`resource-editor-card${draggingKey === key ? ' dragging' : ''}`}
          onPointerDown={event => {
            if (event.button !== 0 || (event.target as HTMLElement).closest('button')) return
            event.preventDefault()
            event.currentTarget.setPointerCapture(event.pointerId)
            dragPointerRef.current = event.pointerId
            dragKeyRef.current = key
            dragOrderRef.current = [...selected]
            // 格子位置与各卡矩形都在按下时量一次：拖动期间卡片会重排，实时量会取到滞后一帧的 DOM。
            const rects = captureRects()
            const cardBox = event.currentTarget.getBoundingClientRect()
            dragAnchorRef.current = {key, card: event.currentTarget, pointerX: event.clientX, pointerY: event.clientY, movedX: event.clientX, movedY: event.clientY, left: cardBox.left, top: cardBox.top}
            rectsRef.current = captureLayout()
            slotsRef.current = [...rects].map(([slotKey, rect]) => ({key: slotKey, left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom}))
            pickerTargetsRef.current = capturePickerSlots()
            setDragOrder([...selected])
            setDraggingKey(key)
          }}
          onPointerMove={event => {
            const sourceKey = dragKeyRef.current
            const order = dragOrderRef.current
            const anchor = dragAnchorRef.current
            if (dragPointerRef.current !== event.pointerId || !sourceKey || !order || !anchor) return
            anchor.movedX = event.clientX
            anchor.movedY = event.clientY
            followPointer()
            const picker = editorRef.current?.parentElement?.querySelector('.resource-picker')
            setPickerDropIndex(inArea(picker, event.clientX, event.clientY) ? pickerDropTarget(event.clientX, event.clientY) : null)
            const index = slotsRef.current.findIndex(slot => event.clientX >= slot.left && event.clientX <= slot.right && event.clientY >= slot.top && event.clientY <= slot.bottom)
            const target = index < 0 ? undefined : order[index]
            if (!target) return
            const next = moveResourceKey(order, sourceKey, target)
            if (next === order) return
            dragOrderRef.current = next
            setDragOrder(next)
          }}
          onPointerUp={event => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
            finishDrag(event.pointerId, true)
          }}
          onPointerCancel={event => finishDrag(event.pointerId, false)}>
          <span className="resource-editor-grip" aria-hidden="true"><GripVertical size={16}/></span>
          <span className="resource-editor-icon resource-editor-icon-image"><ResourceIcon resourceKey={key} size={30} src={dogIcon(key, resource)}/></span>
          <span className="resource-editor-label">{label}</span>
          <button type="button" className="resource-editor-remove" aria-label={ui('resource.remove', {label})} title={ui('resource.remove', {label})} onClick={() => remove(key)}><X size={15}/></button>
        </div>
      </Fragment>})}
      {editorDropIndex === displayed.length && <div className="resource-editor-card resource-drop-slot" aria-hidden="true"/>}
      <button type="button" className={`resource-editor-card resource-editor-add${pickerOpen ? ' open' : ''}`} onClick={() => setPickerOpen(open => !open)}><span className="resource-editor-add-icon"><Plus size={18}/></span><span>{ui('resource.addCard')}</span></button>
      <div className="resource-editor-card resource-drop-slot resource-drop-frame" ref={editorFrameRef} aria-hidden="true"/>
    </div>
    {pickerOpen && <div className="resource-picker">{available.length ? <div className="resource-picker-grid" ref={pickerGridRef}>{pickerSequence.map(key => { const resource = available.find(item => item.name === key); if (!resource) return null
      const labelKey = resourceLabels[resource.name]
      const label = labelKey ? ui(labelKey) : resource.label ?? resource.name
      return <Fragment key={resource.name}>{pickerDropIndex !== null && pickerShown[pickerDropIndex] === resource.name && <div className="resource-editor-card resource-drop-slot" aria-hidden="true"/>}
      <button type="button" className="resource-editor-card resource-picker-card" data-resource-key={resource.name} onPointerDown={event => { if (event.button !== 0) return
          event.currentTarget.setPointerCapture(event.pointerId)
          pickerDragRef.current = resource.name
          const cardBox = event.currentTarget.getBoundingClientRect()
          pickerStartRef.current = {card: event.currentTarget, pointerId: event.pointerId, x: event.clientX, y: event.clientY, movedX: event.clientX, movedY: event.clientY, left: cardBox.left, top: cardBox.top}
          pickerRectsRef.current = capturePickerLayout()
          pickerSlotsRef.current = capturePickerSlots()
          const order = pickerSlotsRef.current.map(slot => slot.key)
          pickerEditorRef.current = captureEditorTargets()
          pickerOrderRef.current = order
          setPickerOrder(order) }}
          onPointerMove={event => { const start = pickerStartRef.current
            if (!start || pickerDragRef.current !== resource.name) return
            start.movedX = event.clientX
            start.movedY = event.clientY
            followPickerPointer()
            const editor = editorRef.current
            setEditorDropIndex(inArea(editor, event.clientX, event.clientY) ? editorDropTarget(event.clientX, event.clientY) : null)
            const order = pickerOrderRef.current
            const index = pickerSlotsRef.current.findIndex(slot => event.clientX >= slot.left && event.clientX <= slot.right && event.clientY >= slot.top && event.clientY <= slot.bottom)
            const target = index < 0 || !order ? undefined : order[index]
            if (!order || !target) return
            const next = moveResourceKey(order, resource.name, target)
            if (next === order) return
            pickerOrderRef.current = next
            setPickerOrder(next) }}
          /* 从「未展示」拖进已展示区，等于把这张卡加回来。 */
          onPointerUp={event => { const start = pickerStartRef.current
            const key = pickerDragRef.current
            pickerDragRef.current = null
            pickerStartRef.current = null
            // 交回过渡，卡片滑回原位。
            if (start) {start.card.style.transition = ''; start.card.style.translate = ''}
            pickerSlotsRef.current = []
            const editor = editorRef.current
            if (key && inArea(editor, event.clientX, event.clientY)) {
              add(key, editorDropIndex)
              setPickerOrder(pickerShown.filter(item => item !== key))
            }
            pickerEditorRef.current = null
            markDropFrame(pickerFrameRef.current)
            setEditorDropIndex(null) }}
          onClick={() => add(resource.name)}><span className="resource-editor-icon resource-editor-icon-image"><ResourceIcon resourceKey={resource.name} size={28} src={dogIcon(resource.name, resource)}/></span><span>{label}</span><Plus size={15}/></button></Fragment>
    })}<div className="resource-editor-card resource-drop-slot resource-drop-frame" ref={pickerFrameRef} aria-hidden="true"/>{pickerDropIndex !== null && pickerDropIndex >= pickerShown.length && <div className="resource-editor-card resource-drop-slot" aria-hidden="true"/>}</div> : <div className="resource-picker-empty">{ui('resource.allAdded')}</div>}</div>}
  </div>
}
