/**
 * @fileoverview 调度器卡片外观映射的契约测试：专属图标、按分类回退与未知兜底、全量分类配色。
 */
import {describe, expect, it} from 'vitest'
import {Box, Coins, Cpu, Filter, Layers, Play, Settings2, Swords, Workflow} from 'lucide-react'
import {cardIcons, categoryColor, categoryColors, categoryIcons, getCardIcon} from './appearance'

describe('调度器卡片外观与图标映射', () => {
  it('为核心流程与任务卡片返回专属 Lucide 图标', () => {
    expect(getCardIcon('entry')).toBe(Play)
    expect(getCardIcon('execute')).toBe(Swords)
    expect(getCardIcon('resource')).toBe(Coins)
    expect(getCardIcon('filter')).toBe(Filter)
    expect(getCardIcon('original_settings')).toBe(Settings2)
    expect(getCardIcon('call')).toBe(Layers)
  })

  it('覆盖主要卡片类型的图标字典有效性', () => {
    for (const [type, icon] of Object.entries(cardIcons)) {
      expect(typeof icon).toBe('object')
      expect(getCardIcon(type)).toBe(icon)
    }
  })

  it('未知卡片类型能按分类回退或回退到 Box 兜底', () => {
    expect(getCardIcon('custom_flow_node', '流程')).toBe(Workflow)
    expect(getCardIcon('custom_logic_node', '逻辑')).toBe(Cpu)
    expect(getCardIcon('custom_unknown_node', '未知分类')).toBe(Box)
    expect(getCardIcon(undefined, undefined)).toBe(Box)
  })

  it('分类调色板为全量分类提供颜色映射', () => {
    const categories = ['流程', '逻辑', '变量', '时间', '资源', '任务', '列表', '调度', '组合']
    for (const cat of categories) {
      expect(categoryColors[cat]).toBeDefined()
      expect(categoryColor(cat)).toBe(categoryColors[cat])
      expect(categoryIcons[cat]).toBeDefined()
    }
    expect(categoryColor('未知')).toBe('#7b8b9e')
  })
})
