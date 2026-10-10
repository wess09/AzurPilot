import {describe, expect, it} from 'vitest'
import {highestShips, type CatalogShip, type MindShip} from './types'

const catalog: CatalogShip[] = [
  {name: '卡辛', base_name: '卡辛', rarity: 'N', base_rarity: 'N', group: '', type: '驱逐'},
  {name: '卡辛.改', base_name: '卡辛', rarity: 'R', base_rarity: 'N', group: '改造', type: '驱逐'},
  {name: '约克城', base_name: '约克城', rarity: 'SR', base_rarity: 'SR', group: '', type: '航母'},
  {name: '约克城II', base_name: '约克城II', rarity: 'UR', base_rarity: 'UR', group: '', type: '航母'},
]
const ship = (name: string, level = 100): MindShip => ({name, level})

describe('截图批量导入的舰船身份合并', () => {
  it('跨截图同级优先改造，输入顺序不影响结果', () => {
    for (const rows of [[ship('卡辛'), ship('卡辛.改')], [ship('卡辛.改'), ship('卡辛')]]) {
      expect(highestShips(rows, catalog)).toEqual([ship('卡辛.改')])
    }
  })
  it('等级优先于改造状态，后面的更高等级替换完整条目', () => {
    expect(highestShips([ship('卡辛', 105), ship('卡辛.改')], catalog)).toEqual([ship('卡辛', 105)])
    expect(highestShips([ship('卡辛'), ship('卡辛.改', 105)], catalog)).toEqual([ship('卡辛.改', 105)])
  })
  it('II型独立，不猜测陌生改造舰的身份，不合并未知占位卡片', () => {
    const rows = [ship('约克城'), ship('约克城II'), ship('未知舰'), ship('未知舰.改'), ship('未识别舰船'), ship('未识别舰船')]
    expect(highestShips(rows, catalog)).toEqual(rows)
    expect(highestShips([ship('错误', 0)], catalog)).toEqual([])
  })
})
