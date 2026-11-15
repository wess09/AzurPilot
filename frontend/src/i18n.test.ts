import { describe, expect, it } from 'vitest'
import { detectLanguage, translateUi } from './i18n'

describe('WebUI i18n', () => {
  it('detects supported browser locales', () => {
    expect(detectLanguage(['zh-HK'])).toBe('zh-TW')
    expect(detectLanguage(['ja'])).toBe('ja-JP')
    expect(detectLanguage(['en-GB'])).toBe('en-US')
    expect(detectLanguage(['fr-FR'])).toBe('zh-CN')
  })

  it('interpolates translated values', () => {
    expect(translateUi('en-US', 'instance.deletePrompt', {name: 'alas-main'})).toBe('Delete alas-main? Its configuration will remain in backup.')
  })

  it('translates the config page instance count summary', () => {
    expect(translateUi('zh-CN', 'config.count', {count: 2})).toBe('共 2 个实例')
    expect(translateUi('zh-TW', 'config.count', {count: 2})).toBe('共 2 個實例')
    expect(translateUi('en-US', 'config.count', {count: 2})).toBe('Instances: 2')
    expect(translateUi('ja-JP', 'config.count', {count: 2})).toBe('インスタンス: 2件')
  })

  it('offers a different delete-instance warning at each of the three confirmations', () => {
    const prompts = ['instance.deletePrompt', 'instance.deletePrompt2', 'instance.deletePrompt3'] as const
    for (const language of ['zh-CN', 'zh-TW', 'en-US', 'ja-JP'] as const) {
      const texts = prompts.map(key => translateUi(language, key, {name: 'alas-main'}))
      expect(new Set(texts).size).toBe(prompts.length)
      // 键不存在时 translateUi 会把键名原样返回，那样三条也「互不相同」，所以这里必须排除。
      expect(texts.some(text => text.includes('instance.deletePrompt'))).toBe(false)
    }
  })

  it('keeps Japanese and Traditional Chinese dictionaries complete for formerly missing UI keys', () => {
    expect(translateUi('ja-JP', 'log.search')).toBe('ログを検索')
    expect(translateUi('ja-JP', 'resource.Oil')).toBe('燃料')
    expect(translateUi('zh-TW', 'fleet.vanguard')).toBe('先鋒艦隊')
    expect(translateUi('zh-TW', 'stats.toolboxSave')).toBe('儲存圖表')
    expect(translateUi('zh-TW', 'stats.axisMode')).toBe('座標軸')
    expect(translateUi('ja-JP', 'stats.axisMode')).toBe('軸モード')
    expect(translateUi('en-US', 'stats.axisMode')).toBe('Axis mode')
    expect(translateUi('zh-CN', 'stats.axisMode')).toBe('坐标轴')
    expect(translateUi('zh-TW', 'stats.candlestickOverlay')).toBe('K 線 + 折線疊加')
    expect(translateUi('ja-JP', 'stats.candlestickOverlay')).toBe('ローソク足 + 折れ線')
    expect(translateUi('en-US', 'stats.candlestickOverlay')).toBe('Candlestick + line overlay')
    expect(translateUi('zh-CN', 'stats.candlestickOverlay')).toBe('K 线 + 折线叠加')
  })
})
