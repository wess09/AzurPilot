// @vitest-environment jsdom
import {act, renderHook, waitFor} from '@testing-library/react'
import {beforeEach, describe, expect, it, vi} from 'vitest'
import {BackgroundGalleryProvider, useBackgroundGallery} from './backgroundGallery'
import {api} from '../api/client'
import {applyGalleryEntry, captureBackgroundSelection, enterGallery, migrateStoredUpload, reconcileGallery, uploadBackgroundFile} from './background'

vi.mock('../api/client', () => ({api: {request: vi.fn()}}))
vi.mock('./context', () => ({useConnection: () => connection}))
vi.mock('./background', () => ({
  applyGalleryEntry: vi.fn(), captureBackgroundSelection: vi.fn(), enterGallery: vi.fn(),
  getBackground: () => background, subscribeBackground: () => () => {},
  migrateStoredUpload: vi.fn(), reconcileGallery: vi.fn(), removeGalleryEntry: vi.fn(),
  saveDirectUrlToGallery: vi.fn(), uploadBackgroundFile: vi.fn(),
}))
const background = {source: 'off', entry: undefined}
let connection = 'ready'
const first = {id: 'first', name: 'first.png', kind: 'image' as const, size: 1, added: 0}
const second = {id: 'second', name: 'second.png', kind: 'image' as const, size: 1, added: 0}

beforeEach(() => {
  vi.clearAllMocks()
  connection = 'ready'
  vi.mocked(migrateStoredUpload).mockResolvedValue()
  vi.mocked(captureBackgroundSelection).mockReturnValue(() => true)
})

describe('background gallery owner', () => {
  it('retries a failed read on reconnect and retains the error until then', async () => {
    vi.mocked(api.request).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce([first])
    const {result, rerender} = renderHook(() => useBackgroundGallery(), {wrapper: BackgroundGalleryProvider})
    await waitFor(() => expect(result.current.error).toBe('offline'))
    expect(result.current.ready).toBe(false)
    connection = 'offline'; rerender()
    connection = 'ready'; rerender()
    await waitFor(() => expect(result.current.entries).toEqual([first]))
    expect(result.current.error).toBe('')
    expect(migrateStoredUpload).toHaveBeenCalledTimes(2)
  })

  it('keeps the retained entry when entering upload mode before the first list arrives', async () => {
    let finish!: (entries: typeof first[]) => void
    vi.mocked(api.request).mockImplementationOnce(() => new Promise(resolve => {finish = resolve}))
    const {result} = renderHook(() => useBackgroundGallery(), {wrapper: BackgroundGalleryProvider})
    act(() => result.current.select(first.id))
    expect(enterGallery).toHaveBeenCalledWith(first.id)
    await waitFor(() => expect(finish).toBeTypeOf('function'))
    await act(async () => finish([first]))
    expect(result.current.entries).toEqual([first])
  })

  it('patches successful upload before refresh and selects the server entry', async () => {
    let finish!: (entries: typeof first[]) => void
    vi.mocked(api.request).mockResolvedValueOnce([first]).mockImplementationOnce(() => new Promise(resolve => {finish = resolve}))
    vi.mocked(uploadBackgroundFile).mockResolvedValue(second)
    const {result} = renderHook(() => useBackgroundGallery(), {wrapper: BackgroundGalleryProvider})
    await waitFor(() => expect(result.current.ready).toBe(true))
    await act(async () => result.current.upload([new File(['x'], 'second.png')]))
    expect(result.current.entries).toEqual([first, second])
    expect(applyGalleryEntry).toHaveBeenCalledWith(second)
    await act(async () => finish([first, second]))
    expect(reconcileGallery).toHaveBeenLastCalledWith([first, second])
  })
})


it('updates the gallery after a slow upload without replacing a newer background choice', async () => {
  let finish!: (entry: typeof second) => void
  let isCurrent = true
  vi.mocked(captureBackgroundSelection).mockReturnValue(() => isCurrent)
  vi.mocked(api.request).mockResolvedValueOnce([first]).mockResolvedValueOnce([first, second])
  vi.mocked(uploadBackgroundFile).mockImplementationOnce(() => new Promise(resolve => {finish = resolve}))
  const {result} = renderHook(() => useBackgroundGallery(), {wrapper: BackgroundGalleryProvider})
  await waitFor(() => expect(result.current.ready).toBe(true))
  const pending = result.current.upload([new File(['x'], 'second.png')])
  isCurrent = false
  await act(async () => {finish(second); await pending})
  expect(result.current.entries).toEqual([first, second])
  expect(applyGalleryEntry).not.toHaveBeenCalled()
})
