import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from '../app/context'
import { translateUi } from '../i18n'
import { StatisticsChart, bucketOptions } from './StatisticsChart'
import type { StatSeries } from '../api/types'

const context = {
  ui: (key: Parameters<AppContextValue['ui']>[0], params?: Parameters<AppContextValue['ui']>[1]) => translateUi('zh-CN', key, params),
  language: 'zh-CN',
  theme: 'default',
} as unknown as AppContextValue

describe('StatisticsChart 多数据源图表组件', () => {
  const mockSeries: StatSeries[] = [
    {
      key: 'oil',
      label: '石油',
      points: [
        {time: '2026-09-20 10:00:00', value: 15000, source: '出击'},
        {time: '2026-09-20 12:00:00', value: 14000, source: '出击'},
      ],
    },
    {
      key: 'coin',
      label: '物资',
      points: [
        {time: '2026-09-20 10:00:00', value: 80000, source: '出击'},
        {time: '2026-09-20 12:00:00', value: 85000, source: '出击'},
      ],
    },
    {
      key: 'cube',
      label: '心智魔方',
      points: [
        {time: '2026-09-20 10:00:00', value: 1200, source: '建造'},
      ],
    },
    {
      key: 'empty_res',
      label: '无记录项',
      points: [],
    },
  ]

  it('渲染所有可用指标的标签芯片（Chips），无记录项应被置灰', () => {
    const html = renderToStaticMarkup(
      <AppContext.Provider value={context}>
        <StatisticsChart series={mockSeries} onToggleExpanded={() => {}}/>
      </AppContext.Provider>,
    )

    expect(html).toContain('石油')
    expect(html).toContain('物资')
    expect(html).toContain('心智魔方')
    expect(html).toContain('无记录项')
    expect(html).toContain('（暂无记录）')
  })

  it('默认选中第一个有数据的指标，并展示单指标概览', () => {
    const html = renderToStaticMarkup(
      <AppContext.Provider value={context}>
        <StatisticsChart series={mockSeries} onToggleExpanded={() => {}}/>
      </AppContext.Provider>,
    )

    expect(html).toContain('最新值')
    expect(html).toContain('区间变化')
    expect(html).toContain('最高值')
    expect(html).toContain('最低值')
    expect(html).toContain('原始记录')
  })

  it('支持大世界多数据源（行动力、作战补给凭证、特别兑换凭证）并提供 K 线与折线模式', () => {
    const opsiSeries: StatSeries[] = [
      {key: 'ap', label: '行动力', points: [{time: '2026-09-20 10:00:00', value: 200}]},
      {key: 'yellow_coins', label: '作战补给凭证', points: [{time: '2026-09-20 10:00:00', value: 5000}]},
      {key: 'purple_coins', label: '特别兑换凭证', points: [{time: '2026-09-20 10:00:00', value: 400}]},
    ]
    const html = renderToStaticMarkup(
      <AppContext.Provider value={context}>
        <StatisticsChart series={opsiSeries} onToggleExpanded={() => {}}/>
      </AppContext.Provider>,
    )

    expect(html).toContain('行动力')
    expect(html).toContain('作战补给凭证')
    expect(html).toContain('特别兑换凭证')
    // Radix 在打开菜单后才挂载选项，静态渲染只检查入口；具体选项由浏览器测试覆盖。
    expect(html).toContain('aria-label="图表类型"')
  })

  it('折线图模式下，采样粒度应包含“每次记录”且选项不重复', () => {
    const labels = bucketOptions(false, context.ui).map(option => option.label)

    expect(labels).toContain('每次记录')
    expect(labels).toContain('5 分钟')
    expect(labels).toContain('每小时')
    expect(labels).toContain('每天')
    expect(labels.filter(label => label === '每小时')).toHaveLength(1)
  })

  it('K 线图模式下，采样粒度不应显示“每次记录”，且不应出现重复的“每小时”选项 (#1013)', () => {
    const labels = bucketOptions(true, context.ui).map(option => option.label)

    expect(labels).not.toContain('每次记录')
    expect(labels).toContain('5 分钟')
    expect(labels).toContain('每小时')
    expect(labels).toContain('每天')
    expect(labels.filter(label => label === '每小时')).toHaveLength(1)
  })

  it('读取持久化偏好中保存的指标选择与采样粒度 (#1043)', async () => {
    const { setSelectedKeysForCategory, updateStatisticsPrefs } = await import('../app/statisticsPrefs')
    setSelectedKeysForCategory('resources', ['cube'])
    updateStatisticsPrefs({ bucket: 60, chartMode: 'line' })

    const html = renderToStaticMarkup(
      <AppContext.Provider value={context}>
        <StatisticsChart series={mockSeries} category="resources" onToggleExpanded={() => {}}/>
      </AppContext.Provider>,
    )

    // 此时选中的是心智魔方，展示的芯片中心智魔方应处于 active 状态，而石油为非 active。
    expect(html).toContain('心智魔方 (已启用，双击仅看此项)')
    expect(html).toContain('石油 (未启用，双击仅看此项)')
  })
})

