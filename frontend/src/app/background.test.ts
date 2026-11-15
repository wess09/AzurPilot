/**
 * @fileoverview 背景图偏好读取的回归测试：地址校验、旧记录折算与按材质回落。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_BACKGROUND_URLS, normalizeBackgroundUrl, readBackgroundPreference } from './background'

describe('背景地址校验', () => {
  it('接受 HTTP 与 HTTPS 地址并清理首尾空白', () => {
    expect(normalizeBackgroundUrl(' https://example.com/a.jpg ')).toBe('https://example.com/a.jpg')
    expect(normalizeBackgroundUrl('http://example.com/video.mp4')).toBe('http://example.com/video.mp4')
  })

  it('拒绝空值、无效地址和非网络协议', () => {
    expect(() => normalizeBackgroundUrl('')).toThrow()
    expect(() => normalizeBackgroundUrl('not-a-url')).toThrow()
    expect(() => normalizeBackgroundUrl('javascript:alert(1)')).toThrow()
    expect(() => normalizeBackgroundUrl('file:///tmp/background.jpg')).toThrow()
  })
})

describe('背景记录按材质读回', () => {
  // 每个用例注入独立的 localStorage 假实现：读回逻辑只看到测试自己写入的记录，不落真实存储。
  const store = (data: Record<string, string>) => {
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => data[key] ?? null,
      setItem: (key: string, value: string) => { data[key] = value },
      removeItem: (key: string) => { delete data[key] },
    })
    return data
  }
  afterEach(() => vi.unstubAllGlobals())

  // 回归：普通材质的默认档是「关闭」，漏判 default 就会把用户选的随机图读成关闭（刷新即被重置）。
  it('普通材质下「默认随机图」读回来还是随机图（旧 default 记录折成 URL 模式的内置 API）', () => {
    store({'azurpilot.background.plain': JSON.stringify({source: 'default', kind: 'image', url: '', name: ''})})
    const preference = readBackgroundPreference('plain')
    expect(preference.source).toBe('url')
    expect(preference.urls).toEqual(DEFAULT_BACKGROUND_URLS)
  })

  it('没有记录时：玻璃默认用内置随机图 API，普通默认关闭', () => {
    store({})
    const glass = readBackgroundPreference('glass')
    expect(glass.source).toBe('url')
    expect(glass.urls).toEqual(DEFAULT_BACKGROUND_URLS)
    expect(readBackgroundPreference('plain').source).toBe('off')
  })

  it('旧单条 url 记录折成一行，新多行记录原样读回', () => {
    store({'azurpilot.background': JSON.stringify({source: 'url', kind: 'image', url: 'https://example.com/old.jpg', name: ''})})
    expect(readBackgroundPreference('glass').urls).toEqual(['https://example.com/old.jpg'])
    store({'azurpilot.background': JSON.stringify({source: 'url', kind: 'image', urls: ['https://a.test/1', 'https://b.test/2'], active: 1, name: ''})})
    const next = readBackgroundPreference('glass')
    expect(next.urls).toHaveLength(2)
    expect(next.active).toBe(1)
  })

  it('一行一条：空行与重复地址都被去掉', () => {
    store({'azurpilot.background': JSON.stringify({source: 'url', kind: 'image', urls: ['https://a.test/1', '  ', 'https://a.test/1', 'https://b.test/2'], active: 0, name: ''})})
    expect(readBackgroundPreference('glass').urls).toEqual(['https://a.test/1', 'https://b.test/2'])
  })

  it('两个材质各读各的键，互不影响', () => {
    store({
      'azurpilot.background': JSON.stringify({source: 'off', kind: 'image', urls: [], active: 0, name: ''}),
      'azurpilot.background.plain': JSON.stringify({source: 'url', kind: 'image', urls: ['https://example.com/a.jpg'], active: 0, name: ''}),
    })
    expect(readBackgroundPreference('glass').source).toBe('off')
    const plain = readBackgroundPreference('plain')
    expect(plain.source).toBe('url')
    expect(plain.urls[plain.active]).toBe('https://example.com/a.jpg')
  })

  it('损坏或空白的记录回落到该材质的默认档', () => {
    store({'azurpilot.background.plain': '{不是 JSON'})
    expect(readBackgroundPreference('plain').source).toBe('off')
  })
})
