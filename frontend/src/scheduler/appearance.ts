/**
 * @fileoverview 卡片类别和端口类型共用的调色板与图标映射，连线与来源端口保持同色。
 */

import type {LucideIcon} from 'lucide-react'
import {
  AlarmClock,
  ArrowDownToDot,
  ArrowRightFromLine,
  ArrowRightToLine,
  ArrowUpDown,
  ArrowUpWideNarrow,
  Binary,
  BookmarkPlus,
  Box,
  Braces,
  Bug,
  Calculator,
  CalendarClock,
  CalendarDays,
  CalendarRange,
  CheckSquare,
  CircleSlash,
  CircleStop,
  Clock,
  Clock3,
  Coins,
  Compass,
  CornerDownLeft,
  Cpu,
  Filter,
  Gauge,
  GitBranch,
  Hash,
  History,
  Hourglass,
  Layers,
  ListFilter,
  ListTodo,
  PenTool,
  Play,
  Radio,
  RefreshCw,
  Repeat,
  Repeat1,
  Scale,
  Settings2,
  Shuffle,
  Snowflake,
  Sparkles,
  StepForward,
  Sunrise,
  Swords,
  ToggleLeft,
  Variable,
  Workflow,
} from 'lucide-react'
import type {PortType} from './types'

/** 卡片类别 → 主题色。 */
export const categoryColors: Record<string, string> = {
  '流程': '#6385d6', '逻辑': '#9970d1', '变量': '#329caa', '时间': '#c58a27',
  '资源': '#289a77', '任务': '#d45982', '列表': '#358dcc', '调度': '#c3733f', '组合': '#7963d3',
}
/** 取类别颜色，未知类别回落到中性灰。 */
export const categoryColor = (category: string) => categoryColors[category] ?? '#7b8b9e'

/** 卡片类别 → 图标。 */
export const categoryIcons: Record<string, LucideIcon> = {
  '流程': Workflow,
  '逻辑': Cpu,
  '变量': Variable,
  '时间': Clock,
  '资源': Coins,
  '任务': ListTodo,
  '列表': ListFilter,
  '调度': CalendarClock,
  '组合': Layers,
}

/** 卡片类型 → 图标，分组与类别一致。 */
export const cardIcons: Record<string, LucideIcon> = {
  // 流程类：
  entry: Play,
  end: CircleStop,
  loop: Repeat,
  foreach: Repeat1,
  loop_end: StepForward,
  call: Layers,
  input: ArrowRightToLine,
  output: ArrowRightFromLine,
  return: CornerDownLeft,
  debug: Bug,
  // 逻辑类：
  literal: Hash,
  compare: Scale,
  logic: Binary,
  math: Calculator,
  select: ToggleLeft,
  branch: GitBranch,
  field: Braces,
  // 变量类：
  get_variable: Variable,
  set_variable: PenTool,
  // 时间类：
  now: Clock,
  weekday: CalendarDays,
  time_window: CalendarRange,
  server_day: Sunrise,
  wait: Hourglass,
  wait_until: AlarmClock,
  // 资源类：
  resource: Coins,
  resource_fresh: Sparkles,
  refresh: RefreshCw,
  // 任务类：
  tasks: ListTodo,
  task: CheckSquare,
  last_result: History,
  requests: Radio,
  execute: Swords,
  // 列表类：
  filter: Filter,
  sort: ArrowUpDown,
  first: ArrowDownToDot,
  empty: CircleSlash,
  // 调度类：
  original_plan: Compass,
  original_settings: Settings2,
  priority: ArrowUpWideNarrow,
  oldest: Clock3,
  round_robin: Shuffle,
  cooldown: Snowflake,
  quota: Gauge,
  record: BookmarkPlus,
}

/** 取卡片图标：先按卡片类型查，再按类别兜底，最后落到通用方块图标。 */
export function getCardIcon(type?: unknown, category?: string): LucideIcon {
  const key = typeof type === 'string' ? type : ''
  return cardIcons[key] ?? (category ? categoryIcons[category] : undefined) ?? Box
}
/** 控制流端口与连线的颜色，区别于数据端口。 */
export const controlColor = '#64748b'
/** 端口同族归并：duration 视作 number，tasks 视作 list，resource 视作 object。 */
const portFamily = (type: PortType) => ({duration:'number', tasks:'list', resource:'object'} as Partial<Record<PortType,PortType>>)[type] ?? type
/** 判断两端口能否连线：any 通配，或同族。 */
export const compatiblePorts = (source: PortType, target: PortType) => source === 'any' || target === 'any' || portFamily(source) === portFamily(target)
/** 端口类型 → 颜色；取值刻意复用类别色板（数值=变量蓝、布尔=逻辑紫、任务=任务红等）。 */
export const portColors: Record<PortType, string> = {
  any: '#8191a5', number: '#329caa', boolean: '#9970d1', string: '#63a04a',
  time: '#c58a27', duration: '#329caa', resource: '#289a77', task: '#d45982',
  tasks: '#358dcc', result: '#c3733f', list: '#358dcc', object: '#289a77',
}
/** any 通配端口的彩环背景，轮播各类别色。 */
export const wildcardBackground = 'conic-gradient(#329caa, #9970d1, #63a04a, #c58a27, #289a77, #d45982, #358dcc, #329caa)'

/** 端口类型的界面文案。 */
export const typeLabels: Record<PortType, string> = {
  any: '任意值',
  number: '数值',
  boolean: '布尔',
  string: '文本',
  time: '时间',
  duration: '时长（秒）',
  resource: '资源记录',
  task: '任务',
  tasks: '任务列表',
  result: '任务结果',
  list: '列表',
  object: '对象',
}

/** 卡片参数键 → 界面文案。 */
export const paramLabels: Record<string, string> = {
  name: '名称',
  value: '值',
  operator: '运算符',
  a: '输入 A',
  b: '输入 B',
  condition: '条件',
  yes: '满足时的值',
  no: '不满足时的值',
  seconds: '时长（秒）',
  time: '目标时间',
  start: '开始时刻',
  end: '结束时刻',
  weekdays: '星期（1～7）',
  field: '字段',
  maxAge: '有效期（秒）',
  autoRefresh: '过期时自动刷新',
  task: '任务',
  rule: '筛选规则',
  descending: '降序',
  count: '循环次数（-1 为持续）',
  loop: '所属循环',
  graph: '组合卡片',
  guard: '继续条件',
  key: '记录标识',
  kind: '记录类型',
  reset: '刷新时刻',
  limit: '每日上限',
  valueType: '数据类型',
  order: '当前优先级顺序',
  dueBefore: '到期截止时间',
  deadline: '最近计划时间',
  idleMode: '空闲策略',
  before: '到期截止时间',
  strict: '截止之前才视为到期',
  items: '数据列表',
  object: '目标对象',
  scores: '评分权重',
  index: '当前索引',
  item: '当前元素',
}
