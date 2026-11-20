// @vitest-environment jsdom
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { disableBackground, getBackground, setBackgroundUrls } from './background'
import { BackgroundUrlResolver } from './backgroundUrl'

vi.mock('../api/client', () => ({api: {request: vi.fn()}}))
const connection = vi.hoisted(() => ({value: 'ready'}))
vi.mock('./context', () => ({useConnection: () => connection.value}))

beforeEach(() => {
  localStorage.clear()
  disableBackground()
  vi.mocked(api.request).mockReset()
  connection.value = 'ready'
})
afterEach(cleanup)

it('waits for the authenticated connection and uses its current media token', async () => {
  connection.value = 'auth'
  const request = vi.mocked(api.request).mockImplementation(async method => {
    if (method === 'background.access') return {token: 'session-media-token'}
    if (method === 'background.resolve') return {content_type: 'image/png', final_url: 'https://example.com/final.png'}
    throw new Error('Unexpected API method')
  })
  setBackgroundUrls(['https://example.com/random'], 'image')
  const view = render(<BackgroundUrlResolver/>)
  expect(request).not.toHaveBeenCalled()
  connection.value = 'ready'
  view.rerender(<BackgroundUrlResolver/>)
  await waitFor(() => expect(getBackground().directUrl).toBe('https://example.com/final.png'))
  const media = new URL(getBackground().assetUrl, location.href)
  expect(media.pathname).toBe('/api/v1/background/media')
  expect(media.searchParams.get('token')).toBe('session-media-token')
  expect(media.searchParams.get('url')).toBe('https://example.com/final.png')
  const saved = Object.keys(localStorage).filter(key => key.startsWith('azurpilot.background')).map(key => localStorage.getItem(key)).join('')
  expect(saved).toContain('https://example.com/random')
  expect(saved).not.toContain('session-media-token')
})

it('keeps the latest result when the same wallpaper URL is reapplied', async () => {
  let completeOld!: (result: {final_url: string; content_type: string}) => void
  const old = new Promise<{final_url: string; content_type: string}>(resolve => {completeOld = resolve})
  let resolutions = 0
  vi.mocked(api.request).mockImplementation(async method => {
    if (method === 'background.access') return {token: 'session-media-token'}
    if (method === 'background.resolve') {
      if (++resolutions === 1) return old
      return {content_type: 'image/png', final_url: 'https://example.com/latest.png'}
    }
    throw new Error('Unexpected API method')
  })
  const urls = ['https://example.com/random']
  setBackgroundUrls(urls, 'image')
  render(<BackgroundUrlResolver/>)
  await waitFor(() => expect(resolutions).toBe(1))
  act(() => setBackgroundUrls(urls, 'image'))
  await waitFor(() => expect(getBackground().directUrl).toBe('https://example.com/latest.png'))
  await act(async () => completeOld({content_type: 'image/png', final_url: 'https://example.com/stale.png'}))
  expect(getBackground().directUrl).toBe('https://example.com/latest.png')
})
