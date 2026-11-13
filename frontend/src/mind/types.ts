import type { Parameters } from '../api/generated'

export type MindShip = Parameters['dock.stageImport']['ships'][number]
type Rarity = 'N' | 'R' | 'SR' | 'SSR' | 'UR'
/** 养成计算的舰船目录条目；船坞台账也用它确认舰船身份。 */
export interface CatalogShip {nationality?: number; nation?: string; name: string; raw_name?: string; group_type?: number; code?: number | null; rarity: Rarity; base_rarity: Rarity; base_name: string; group: string; type: string}
/** 舰船目录快照：目录更新时间与全部条目。 */
export interface MindCatalog {updated_at: string; ships: CatalogShip[]}
