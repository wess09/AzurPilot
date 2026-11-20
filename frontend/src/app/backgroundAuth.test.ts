/**
 * @fileoverview 背景代理地址与 HTTP 能力令牌的领取、缓存与重领行为。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { applyGalleryEntry, disableBackground, getBackground, reconcileGallery, readBackgroundPreference, setBackgroundUrls, uploadBackgroundFile } from './background'
import { getThemePreference } from './theme'

vi.mock('../api/client', () => ({api: {request: vi.fn()}}))

// 背景模块维护模块级快照与图库状态，每例先关闭背景复位，防止用例间串扰。
beforeEach(() => {
  vi.resetAllMocks()
  vi.stubGlobal('localStorage', {getItem: () => null, setItem: vi.fn()})
  disableBackground()
})
afterEach(() => vi.unstubAllGlobals())

describe('背景 HTTP 能力令牌', () => {
  it('上传在领取令牌后通过请求头发送，不把令牌放入 URL', async () => {
    vi.mocked(api.request).mockImplementation(async method => {
      if (method === 'background.access') return {token: 'upload-token'}
      if (method === 'background.gallery.list') return []
      throw new Error(`非预期请求：${method}`)
    })
    const fetch = vi.fn().mockResolvedValue({ok: true, json: async () => ({entry: {id: 'sample'}})})
    vi.stubGlobal('fetch', fetch)
    const entry = await uploadBackgroundFile(new File(['image'], 'test.png', {type: 'image/png'}))
    expect(entry.id).toBe('sample')
    expect(fetch).toHaveBeenCalledWith('/api/v1/background/gallery', expect.objectContaining({
      method: 'POST', headers: {'x-azurpilot-background-token': 'upload-token'},
    }))
  })

  it('未授权会话领取失败时不会发送上传请求', async () => {
    vi.mocked(api.request).mockRejectedValue(new Error('请先登录'))
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    await expect(uploadBackgroundFile(new File(['image'], 'test.png', {type: 'image/png'}))).rejects.toThrow('请先登录')
    expect(fetch).not.toHaveBeenCalled()
  })
})

// 关闭背景只停铺图，已填地址在重读后仍在。
describe('背景关闭档保留已填地址', () => {
  const store = new Map<string, string>()

  beforeEach(() => {
    store.clear()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
    })
  })

  it('关闭后重新读取仍能拿回地址与类型', () => {
    setBackgroundUrls(['https://example.com/custom.png'], 'video')
    disableBackground()
    const restored = readBackgroundPreference(getThemePreference().material)
    expect(restored.source).toBe('off')
    expect(restored.urls).toEqual(['https://example.com/custom.png'])
    expect(restored.kind).toBe('video')
  })

  it('关闭前已存的旧记录同样在重读时还原', () => {
    store.set(`azurpilot.background${getThemePreference().material === 'plain' ? '.plain' : ''}`, JSON.stringify({
      source: 'off', kind: 'image', urls: ['https://example.com/kept.png'], active: 0,
    }))
    const restored = readBackgroundPreference(getThemePreference().material)
    expect(restored.source).toBe('off')
    expect(restored.urls).toEqual(['https://example.com/kept.png'])
  })

  it('关闭后重新读取仍能拿回图库条目', () => {
    store.set(`azurpilot.background${getThemePreference().material === 'plain' ? '.plain' : ''}`, JSON.stringify({
      source: 'off', kind: 'image', urls: [], active: 0, name: 'kept.png', entry: 'mock_bg',
    }))
    const restored = readBackgroundPreference(getThemePreference().material)
    expect(restored.source).toBe('off')
    expect(restored.entry).toBe('mock_bg')
    expect(restored.name).toBe('kept.png')
  })

  it('关闭背景时保留当前生效的图库条目', async () => {
    vi.mocked(api.request).mockImplementation(async method => {
      if (method === 'background.gallery.list') return [{id: 'mock_bg', name: 'kept.png', kind: 'image', size: 1024, added: 0}]
      throw new Error(`非预期请求：${method}`)
    })
    applyGalleryEntry({id: 'mock_bg', name: 'kept.png', kind: 'image', size: 1024, added: 0})
    disableBackground()
    const restored = readBackgroundPreference(getThemePreference().material)
    expect(restored.entry).toBe('mock_bg')
    expect(restored.name).toBe('kept.png')
  })
})

it('clears the selected wallpaper when the final gallery entry disappears', () => {
  applyGalleryEntry({id: 'last', name: 'last.png', kind: 'image', size: 1024, added: 0})
  reconcileGallery([])
  expect(getBackground().entry).toBeUndefined()
  expect(getBackground().assetUrl).toBe('')
  expect(getBackground().source).toBe('upload')
})
