import { describe, expect, it } from 'vitest'
import type { ResourceFlowReport, StatisticsReport } from '../api/types'
import { localizeFlowReport, localizeReport, translateStatText, withTranslatedKeys } from './statisticsText'

// 一-鿿 即 CJK 统一汉字区：断言翻译结果里不再有汉字残留。
const han = /[一-鿿]/

// 统计页在英文界面下实际出现过的后端中文（资源趋势、大世界、委托、舰船经验、掉落、仓库各页）。
const seen = [
  '石油', '物资', '钻石', '活动 PT', '心智魔方', '核心数据', '荣誉勋章', '功勋', '舰队币', '行动力', '行动力资产', '海里数',
  '作战补给凭证', '特别兑换凭证', '战斗次数', '出击轮数', '出击消耗', '明石遭遇', '明石遭遇率', '塞壬研究装置', '装置获取率',
  '购买行动力', '平均每次购买', '净行动力', '循环效率', '平均战斗时长', '预估经验效率', '今日战斗', '今日经验', '今日运行',
  '短猫运行统计', '侵蚀等级', '有效轮数', '平均战斗秒数', '平均每轮秒数', '研究装置', '获取率（%）', '统计来源', '暂无记录',
  '完成委托', '心智单元', '委托收益明细', '资源', '总收益', '掉落记录数', '平均每次掉落', '委托结算记录', '时间', '委托数量', '魔方',
  '目标等级', '平均每轮时长', '短猫平均战斗时长', '每日经验', '每日战斗', '每日运行秒数', '舰船升级进度', '上次检测：尚未检测；舰队：—。',
  '位置', '等级', '当前经验', '累计经验', '目标经验', '检测后战斗数', '还需经验', '还需战斗', '预估用时',
  '大世界掉落明细', '图标', '物品', '稀有度', '短猫掉落收益', '上次记录时间', '有效战斗轮数', '平均黄币/轮', '平均金菜/轮', '平均深渊/轮', '平均隐秘/轮',
  '第 9 期收获明细', '还没有科研掉落记录。统计在领奖时自动完成：把「科研截图」设为「保存」或「上传」即可（两者都会统计，区别只是要不要把截图落盘）。',
  '仓库物品', '分类', '数量', '状态', '未扫描', '突破部件', '装备研发图纸', '实验计划', '强化部件', '兵装研发材料', '心智单元II', '试作型突破部件',
  '尚未运行仓库统计任务。运行并完成完整扫描后才会更新物品数量。 刷新只读取已有快照；未发现的物品显示“未发现”，不把无法确认的数量当成 0。',
  '统计金菜（部件T4）、装备研发图纸SSR/UR型、六种金色研发材料、机密/绝密实验计划及特装型突破部件；其他物品照常入库，只是不在这里展示。统计在任务跑完解析掉落时完成：把该任务的「掉落截图」设为保存或上传均可（两者都统计，区别只是要不要把截图落盘）。 这段时间里没有掉落记录——「汇总周期」选今天/本周时窗口很短，改成「选定月份」能看得更多。',
  '任务内库存变化', '奖励领取', '跨任务或离线变化', '场', '轮', '次', '个', '秒', '/小时', '分钟', '项', '1小时30分钟', '45分钟',
]

describe('统计页后端文本翻译', () => {
  it('英文界面不再残留已知的中文文本', () => {
    for (const text of seen) expect(translateStatText('en-US', text), text).not.toMatch(han)
  })

  it('繁体与日文也覆盖同一批文本，简体保持原文', () => {
    for (const text of seen) {
      expect(translateStatText('zh-TW', text), text).not.toBe('')
      expect(translateStatText('ja-JP', text), text).not.toBe('')
    }
    expect(translateStatText('zh-TW', '委托结算记录')).toBe('委託結算記錄')
    expect(translateStatText('zh-CN', '委托结算记录')).toBe('委托结算记录')
  })

  it('物品名、任务名使用后端对照表，掉落清单逐项翻译', () => {
    const glossary = {'钛合金': {'en-US': 'Corrosion-Resistant Alloys'}, 'HBX炸药': {'en-US': 'HBX Blend Gunpowder'}}
    expect(translateStatText('en-US', '钛合金 x2、HBX炸药 x1', glossary)).toBe('Corrosion-Resistant Alloys x2, HBX Blend Gunpowder x1')
    expect(translateStatText('ja-JP', '钛合金', glossary)).toBe('钛合金')
    expect(translateStatText('en-US', '要塞海域 East Continental Shelf E（侵蚀3）')).toBe('Stronghold zone East Continental Shelf E (hazard 3)')
    expect(translateStatText('en-US', '第 9 期在统计区间内没有记录；有记录的期数：第 7 期、第 8 期（可把「汇总周期」改成选定月份再看）'))
      .toBe('No records for series 9 in this period. Series with records: 7, 8 (try “Selected month” under “Summary period”).')
  })

  it('不认识的文本与模板图标值原样保留', () => {
    expect(translateStatText('en-US', 'East Continental Shelf')).toBe('East Continental Shelf')
    const report: StatisticsReport = {
      instance: 'test', category: 'research', month: '2026-10', notes: [], series: [],
      metrics: [{label: '战斗次数', value: 3, unit: '场'}, {label: '获取率', value: 1, unit: '%'}],
      tables: [{title: '仓库物品', columns: ['图标', '物品'], rows: [['research:CognitiveChips', '心智单元', 2]]}],
    }
    const shown = localizeReport(report, 'en-US')
    expect(shown.metrics[0]).toMatchObject({label: 'Battles', unit: ' battles'})
    expect(shown.metrics[1].unit).toBe('%')
    expect(shown.tables[0].rows[0]).toEqual(['research:CognitiveChips', 'Cognitive chips', 2])
    expect(localizeReport(report, 'zh-CN')).toBe(report)
  })

  it('资源管理的物品名、分组与用途随语言显示', () => {
    const report = {
      instance: 'test', start: '', end: '', offset: 0, limit: 100, total: 1, throughId: 1, tasks: [], oilControl: {enable: true, target: 24000},
      resources: [{key: 'Oil', label: '石油', group: '货币', current: 1, observedAt: null, income: 0, expense: 0, adjustment: 0, count: 0}],
      flows: [{resource: 'Oil', task: 'Commission', operation: '奖励领取', evidence: 'recognition', income: 1, expense: 0, count: 1}],
      entries: [{id: 1, ts: '', resource: 'Oil', amount: 1, task: 'Commission', operation: '跨任务或离线变化', evidence: 'adjustment', run_id: null}],
    } as unknown as ResourceFlowReport
    const shown = localizeFlowReport(report, 'en-US')
    expect(shown.resources[0]).toMatchObject({label: 'Oil', group: 'Currency'})
    expect(shown.flows[0].operation).toBe('Reward collected')
    expect(shown.entries[0].operation).toBe('Change between tasks or offline')
  })

  it('图标表补上译名后，翻译后的标签仍能找到图标', () => {
    const icons = withTranslatedKeys({'石油': 'oil.webp'})
    expect(icons['Oil']).toBe('oil.webp')
    expect(icons['燃料']).toBe('oil.webp')
    expect(icons['石油']).toBe('oil.webp')
  })
})
