/**
 * 从 Statistics.tsx 原 65-118、137-145 行提取，纯搬迁未改动。
 * 收获指标卡片的图标解析：内置图标、本地 webp 与自定义图标。
 */
import {
  Award,
  Calculator,
  Cat,
  CheckCircle2,
  Clock,
  Coins,
  Cpu,
  Crosshair,
  Flame,
  Fuel,
  Gem,
  Hourglass,
  Package,
  Percent,
  RotateCw,
  ShoppingCart,
  Sparkles,
  Swords,
  Timer,
  TrendingUp,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import {resolveIcon} from '../../components/StatisticsTable'
import {withTranslatedKeys} from '../../components/statisticsText'

/* 图标表的键为中文名；withTranslatedKeys 补上译名，翻译后的指标名仍能找到图标。 */
const metricIcons: Record<string, LucideIcon> = withTranslatedKeys({
  '战斗次数': Swords,
  '出击轮数': RotateCw,
  '出击消耗': Flame,
  '明石遭遇': Cat,
  '明石遭遇率': Percent,
  '塞壬研究装置': Cpu,
  '装置获取率': Crosshair,
  '购买行动力': ShoppingCart,
  '平均每次购买': Calculator,
  '净行动力': Zap,
  '循环效率': TrendingUp,
  '完成委托': CheckCircle2,
  '钻石': Gem,
  '心智魔方': Package,
  '心智单元': Cpu,
  '石油': Fuel,
  '物资': Coins,
  '目标等级': Award,
  '预估经验效率': TrendingUp,
  '平均战斗时长': Clock,
  '平均每轮时长': Hourglass,
  '短猫平均战斗时长': Cat,
  '今日战斗': Swords,
  '今日经验': Sparkles,
  '今日运行': Timer,
})

const iconBase = import.meta.env.BASE_URL
const metricWebpIcons: Record<string, string> = withTranslatedKeys({
  '完成委托': `${iconBase}honor_medal.webp`,
  '钻石': `${iconBase}diamond.webp`,
  '心智魔方': `${iconBase}cube.webp`,
  '心智单元': `${iconBase}cognitive_chips.webp`,
  '石油': `${iconBase}oil.webp`,
  '物资': `${iconBase}gold.webp`,
})

function getMetricWebp(label: string): string | undefined {
  if (metricWebpIcons[label]) return metricWebpIcons[label]
  for (const [key, src] of Object.entries(metricWebpIcons)) {
    if (label.includes(key) || key.includes(label)) return src
  }
  return undefined
}

function getMetricIcon(label: string): LucideIcon | undefined {
  if (metricIcons[label]) return metricIcons[label]
  for (const [key, icon] of Object.entries(metricIcons)) {
    if (label.includes(key) || key.includes(label)) return icon
  }
  return undefined
}

/* 收获指标图标：自定义图标优先，其次本地 webp，再次内置图标。 */
export function metricIcon(item: {label: string; icon?: string}) {
  const custom = item.icon ? resolveIcon(item.icon) : undefined
  const webp = custom?.src ?? getMetricWebp(item.label)
  const Icon = !webp ? getMetricIcon(item.label) : undefined
  if (webp) return <span className="summary-metric-icon summary-metric-icon-webp" aria-hidden="true"><img src={webp} alt="" width={48} height={48} draggable={false}/></span>
  if (Icon) return <span className="summary-metric-icon" aria-hidden="true"><Icon size={18} strokeWidth={1.8}/></span>
  return null
}
