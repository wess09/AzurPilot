import {describe, expect, it} from 'vitest'
import {editableShip, highestShips, type CatalogShip, type MindShip} from './types'

const catalog: CatalogShip[] = [
  {name: '卡辛', base_name: '卡辛', rarity: 'N', base_rarity: 'N', group: '', type: '驱逐', group_type: 10103},
  {name: '卡辛.改', base_name: '卡辛', rarity: 'R', base_rarity: 'N', group: '改造', type: '驱逐', group_type: 10103},
  {name: '约克城', base_name: '约克城', rarity: 'SR', base_rarity: 'SR', group: '', type: '航母', group_type: 10705},
  {name: '约克城II', base_name: '约克城II', rarity: 'UR', base_rarity: 'UR', group: '', type: '航母', group_type: 10710},
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
  it('保留等级未知及同名的独立核对卡位，不覆盖已确认舰船', () => {
    const rows = [ship('卡辛'), {...ship('卡辛', 0), review: true}, {...ship('卡辛', 120), review: true},
      {...ship('读错名称'), review: true}, {...ship('读错名称'), review: true}]
    expect(highestShips(rows, catalog)).toEqual(rows)
  })
  it('重名不同群组分别取最高等级，白名单及草稿往返保留身份', () => {
    const duplicates: CatalogShip[] = [30507, 30702].map((group_type, i) => ({name: '加贺', base_name: '加贺',
      rarity: 'SSR', base_rarity: 'SSR', group: '', type: i ? '正航' : '战列', group_type}))
    const rows = [{name: '加贺', group_type: 30507, level: 120}, {name: '加贺', group_type: 30702, level: 100}]
    expect(highestShips([...rows, {...rows[0], level: 105}], duplicates)).toEqual(rows)
    const draft = rows.map(editableShip)
    expect(JSON.parse(JSON.stringify(draft)).map(editableShip)).toEqual(draft)
    expect(highestShips([{name: '加贺', level: 100}, {name: '加贺', level: 120}], duplicates)).toHaveLength(2)
    const review = editableShip({name: '约克', level: 0, review: true, candidates: [20307, 40311]})
    expect(review.candidates).toEqual([20307, 40311])
    expect(review.group_type).toBeNull()
  })
})
