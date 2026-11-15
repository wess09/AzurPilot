/**
 * @fileoverview 资源图标域：资源键 i18n 标签、内置图标映射、行动力狗头档位与键序工具。
 * 从 ResourceCards.tsx 原 12-71 行提取，纯搬迁未改动。
 */

import { Box } from 'lucide-react'
import type { Resource } from '../../api/types'
import type { UiKey } from '../../i18n'
/** 资源键 → i18n 标签键映射，卡片标题与选择网格共用。 */
export const resourceLabels: Record<string, UiKey> = {Oil: 'resource.Oil', Coin: 'resource.Coin', Gem: 'resource.Gem', Cube: 'resource.Cube', Pt: 'resource.Pt', ActionPoint: 'resource.ActionPoint', YellowCoin: 'resource.YellowCoin', PurpleCoin: 'resource.PurpleCoin', Core: 'resource.Core', Medal: 'resource.Medal', Merit: 'resource.Merit', GuildCoin: 'resource.GuildCoin', Chip: 'resource.Chip', Distance: 'resource.Distance', ActionAsset: 'resource.ActionAsset'}
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

/** 资源图标：优先内置图标图，缺失时回落到通用箱型图标。 */
export function ResourceIcon({resourceKey, size = 32, src}: {resourceKey: string; size?: number; src?: string}) {
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
  const moved = next.splice(from, 1)[0]
  if (moved !== undefined) next.splice(to, 0, moved)
  return next
}
