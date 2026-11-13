import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from '../app/context'
import type { Resource } from '../api/types'
import { translateUi } from '../i18n'
import { setDashboardPref } from '../app/dashboardPrefs'
import { actionPointDogIcon, moveResourceKey, ResourceCards } from './ResourceCards'

function renderResources(resources: Resource[], selected = ['ActionPoint']) {
  return renderToStaticMarkup(
    <AppContext.Provider value={{ui: (key, params) => translateUi('zh-CN', key, params)} as AppContextValue}>
      <ResourceCards resources={resources} selected={selected}/>
    </AppContext.Provider>,
  )
}

describe('资源卡片', () => {
  it('按拖动目标重排卡片且不修改原数组', () => {
    const original = ['Oil', 'Coin', 'Gem', 'Cube']

    expect(moveResourceKey(original, 'Cube', 'Coin')).toEqual(['Oil', 'Cube', 'Coin', 'Gem'])
    expect(moveResourceKey(original, 'Oil', 'Cube')).toEqual(['Coin', 'Gem', 'Cube', 'Oil'])
    expect(moveResourceKey(original, 'Oil', 'Oil')).toBe(original)
    expect(original).toEqual(['Oil', 'Coin', 'Gem', 'Cube'])
  })

  it('记录时间当日只给时分秒，跨日给月日与小时', () => {
    const pad = (count: number) => String(count).padStart(2, '0')
    const stamp = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
    const now = new Date()
    const today = renderResources([{name: 'Oil', label: '石油', value: 1, record: stamp(now)}], ['Oil'])
    const earlier = renderResources([{name: 'Oil', label: '石油', value: 1, record: stamp(new Date(now.getTime() - 24 * 60 * 60 * 1000))}], ['Oil'])

    expect(today).toMatch(/class="resource-foot">\d{2}:\d{2}:\d{2}</)
    expect(earlier).toMatch(/class="resource-foot">\d{2}-\d{2}-\d{2}</)
  })

  it('记录时间超过一年只提示过久', () => {
    const long = new Date(Date.now() - 400 * 24 * 60 * 60 * 1000)
    const html = renderResources([{name: 'Oil', label: '石油', value: 1, record: long.toISOString()}], ['Oil'])

    expect(html).toContain('时间太久了啦…')
  })

  it('行动力与石油一致，以小字后缀显示总量', () => {
    const html = renderResources([{name: 'ActionPoint', label: '行动力', value: 101, total: 1301, record: '2026-09-16 12:00:00'}])

    expect(html).toContain('<span>行动力</span>')
    expect(html).toContain('<span>101</span><small>/ 1,301</small>')
  })

  it.each([101, 0])('总行动力与当前行动力相等时仍显示完整数值：%s', value => {
    const html = renderResources([{name: 'ActionPoint', label: '行动力', value, total: value, record: '2026-09-16 12:00:00'}])

    expect(html).toContain(`<span>${value}</span><small>/ ${value}</small>`)
  })

  it.each([undefined, 0, 100, NaN, Infinity])('总行动力缺失或异常时回退到当前行动力：%s', total => {
    const html = renderResources([{name: 'ActionPoint', label: '行动力', value: 101, total, record: '2026-09-16 12:00:00'}])

    expect(html).toContain('<span>行动力</span>')
    expect(html).toContain('<span>101</span>')
    expect(html).not.toContain('总行动力')
  })

  it.each([undefined, '2020-01-01 00:00:00'])('尚未同步时不展示总量和明细：%s', record => {
    const html = renderResources([{name: 'ActionPoint', label: '行动力', value: 101, total: 1301, record}])

    expect(html).toContain('<span>—</span>')
    expect(html).not.toContain('1,301')
    expect(html).not.toContain('<small>')
  })

  it('其他资源仍显示当前值和上限', () => {
    const html = renderResources([{name: 'Oil', label: '石油', value: 1000, limit: 16000, record: '2026-09-16 12:00:00'}], ['Oil'])

    expect(html).toContain('<span>1,000</span>')
    expect(html).toContain('<small>/ 16,000</small>')
  })

  it('总行动力优先时两个数字互换', () => {
    // 仪表盘偏好是模块级状态，改完必须在 finally 里还原，避免泄进后续用例。
    setDashboardPref('totalFirst', true)
    try {
      const html = renderResources([{name: 'ActionPoint', label: '行动力', value: 101, total: 1301, record: '2026-09-16 12:00:00'}])

      expect(html).toContain('<span>1,301</span><small>/ 101</small>')
    } finally {
      setDashboardPref('totalFirst', false)
    }
  })

  it('通用卡片把已选资源收进同一个容器', () => {
    setDashboardPref('merged', true)
    try {
      const html = renderResources([{name: 'Oil', label: '石油', value: 1000, record: '2026-09-16 12:00:00'}], ['Oil', 'Coin'])

      expect(html.match(/class="resource-card resource-merged"/g)).toHaveLength(1)
      expect(html.match(/resource-merged-item/g)).toHaveLength(2)
      expect(html.match(/class="resource-heading"/g)).toHaveLength(2)
      expect(html.match(/class="resource-value-content"/g)).toHaveLength(2)
    } finally {
      setDashboardPref('merged', false)
    }
  })

  it('大狗图标关闭时，行动力再高也用默认图标', () => {
    setDashboardPref('dogIcon', false)
    try {
      const html = renderResources([
        {name: 'ActionPoint', label: '行动力', value: 101, total: 12000, record: '2026-09-16 12:00:00'},
        {name: 'Oil', label: '石油', value: 1000, record: '2026-09-16 12:00:00'},
      ], ['ActionPoint', 'Oil'])
      expect(html).toContain('guild_coin.webp')
      expect(html).toContain('oil.webp')
      expect(html).not.toContain('dog_')
    } finally {
      setDashboardPref('dogIcon', true)
    }
  })

  it('行动力图标按四档换图，其余资源始终用自带图标', () => {
    setDashboardPref('dogIcon', true)
    const render = (total: number) => renderResources([
      {name: 'ActionPoint', label: '行动力', value: 101, total, record: '2026-09-16 12:00:00'},
      {name: 'Oil', label: '石油', value: 1000, record: '2026-09-16 12:00:00'},
    ], ['ActionPoint', 'Oil'])

    const tiers: Array<[number, string]> = [
      [6000, 'guild_coin.webp'],
      [6001, 'dog_small.webp'],
      [8000, 'dog_small.webp'],
      [8001, 'dog_medium.webp'],
      [10000, 'dog_medium.webp'],
      [10001, 'dog_large.webp'],
      [12000, 'dog_large.webp'],
      [12001, 'dog_king.webp'],
    ]
    for (const [total, icon] of tiers) {
      const html = render(total)
      expect(html, `总行动力 ${total} 应使用 ${icon}`).toContain(icon)
      expect(html, `总行动力 ${total} 时石油不该换图`).toContain('oil.webp')
    }
    expect(render(12001)).not.toContain('guild_coin.webp')
  })

  it('actionPointDogIcon 的档位边界与回退', () => {
    const ap = (total: number, extra: Partial<Resource> = {}) => ({name: 'ActionPoint', label: '行动力', value: 100, total, ...extra})
    expect(actionPointDogIcon(ap(6000))).toBeUndefined()
    expect(actionPointDogIcon(ap(6001))).toContain('dog_small.webp')
    expect(actionPointDogIcon(ap(8000))).toContain('dog_small.webp')
    expect(actionPointDogIcon(ap(8001))).toContain('dog_medium.webp')
    expect(actionPointDogIcon(ap(10001))).toContain('dog_large.webp')
    expect(actionPointDogIcon(ap(12001))).toContain('dog_king.webp')
    expect(actionPointDogIcon(ap(12001, {record: '2020-01-01 00:00:00'}))).toBeUndefined()
    expect(actionPointDogIcon({name: 'Oil', label: '石油', value: 100, total: 12001})).toBeUndefined()
    expect(actionPointDogIcon(undefined)).toBeUndefined()
    // total 小于 value 时退回 value：异常数据不该被当成低档。
    expect(actionPointDogIcon({name: 'ActionPoint', label: '行动力', value: 9000, total: 1})).toContain('dog_medium.webp')
  })
})
