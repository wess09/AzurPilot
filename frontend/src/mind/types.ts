import type { Parameters } from '../api/generated'

export type MindShip = Parameters['mind.save']['ships'][number]
export type Rarity = 'N' | 'R' | 'SR' | 'SSR' | 'UR'
export interface CatalogShip {name: string; rarity: Rarity; base_rarity: Rarity; base_name: string; group: string; type: string}
export interface MindCatalog {updated_at: string; ships: CatalogShip[]}
export interface MindRow extends MindShip {rarity: Rarity | ''; base_rarity: Rarity | ''; group: string; base_name: string; status: 'included' | 'merged' | 'review' | 'excluded'; automatic_excluded: boolean; mind: number; gold: number}
export interface MindSummary {rarity: Rarity; stages: number[]; stage_mind: number[]; count: number; mind: number; gold: number}
export interface MindCalculation {ships: MindRow[]; summary: MindSummary[]; mind: number; gold: number; included: number; merged: number; excluded: number; review: number}
export interface MindReport extends MindCalculation {instance: string; revision: string; updated_at: string; min_level?: number; max_level?: number}

export function highestShips(ships: MindShip[], catalog: CatalogShip[] = []): MindShip[] {
  const normalize = (name: string) => name.normalize('NFKC').replace(/[\s.·・．。]/g, '').toLocaleLowerCase()
  const known = new Map(catalog.map(info => [normalize(info.name), info]))
  const output = new Map<string, MindShip>()
  for (const [index, ship] of ships.entries()) {
    if (ship.level < 1 || ship.level > 125) continue
    const info = known.get(normalize(ship.name))
    const name = info && info.group !== 'META' && !normalize(ship.name).includes('meta') ? info.base_name : ship.name
    const key = ship.name.startsWith('未识别舰船') ? `unknown:${index}` : normalize(name)
    const previous = output.get(key)
    const preferRetrofit = previous && previous.level === ship.level && info?.group === '改造' && known.get(normalize(previous.name))?.group !== '改造'
    if (!previous || previous.level < ship.level || preferRetrofit) output.set(key, ship)
  }
  return [...output.values()]
}

export function editableShip(ship: MindShip): MindShip {
  return {name: ship.name, level: ship.level, rarity: ship.rarity ?? '', base_rarity: ship.base_rarity ?? '',
    excluded: ship.excluded ?? false, review: ship.review ?? false, source: ship.source ?? ''}
}
