import {afterEach, expect, it, vi} from 'vitest'

vi.mock('../api/client', () => ({api: {request: vi.fn(async () => ({token: 'token'}))}}))
const theme = vi.hoisted(() => ({material: 'glass' as 'glass' | 'plain', listeners: [] as Array<() => void>}))
vi.mock('./theme', () => ({getThemePreference: () => ({theme: 'classic', material: theme.material}), subscribeTheme: (listener: () => void) => { theme.listeners.push(listener) }}))

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); theme.material = 'glass'; theme.listeners = [] })

function setup() {
  const values = new Map<string, string>()
  const storage = {getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }}
  vi.stubGlobal('localStorage', storage)
  let blob: Blob | undefined = new Blob(['legacy'], {type: 'image/png'})
  let readFails = false
  const indexedDB = {open: () => {
    const request: any = {}
    const db = {close: () => {}, transaction: () => {
      const transaction: any = {}
      transaction.objectStore = () => ({get: () => {
        const op: any = {}
        queueMicrotask(() => { if (readFails) { op.error = new Error('read failed'); op.onerror?.(); return } op.result = blob; op.onsuccess?.(); transaction.oncomplete?.() })
        return op
      }, delete: () => {
        const op: any = {}
        queueMicrotask(() => { blob = undefined; transaction.oncomplete?.() })
        return op
      }})
      return transaction
    }}
    queueMicrotask(() => { request.result = db; request.onsuccess?.() })
    return request
  }}
  vi.stubGlobal('indexedDB', indexedDB)
  return {values, storage, blob: () => blob, setFile: (value: Blob | undefined) => { blob = value }, failRead: (value: boolean) => { readFails = value }}
}

it('retains the browser file on failed upload and imports both material references on retry', async () => {
  const {values, blob} = setup()
  values.set('azurpilot.background', JSON.stringify({source: 'off', kind: 'image', name: 'old', urls: [], active: 0}))
  values.set('azurpilot.background.plain', JSON.stringify({source: 'upload', kind: 'image', name: 'old', urls: [], active: 0}))
  const fetch = vi.fn().mockResolvedValueOnce({ok: false, json: async () => ({error: 'failed'})}).mockResolvedValueOnce({ok: true, json: async () => ({entry: {id: 'legacy-id', kind: 'image', name: 'old.png'}})})
  vi.stubGlobal('fetch', fetch)
  const background = await import('./background')
  await background.migrateStoredUpload()
  expect(blob()).toBeDefined()
  await background.migrateStoredUpload()
  expect(blob()).toBeUndefined()
  expect(JSON.parse(values.get('azurpilot.background')!).entry).toBe('legacy-id')
  expect(JSON.parse(values.get('azurpilot.background.plain')!).entry).toBe('legacy-id')
  const form = fetch.mock.calls[1]![1]!.body as FormData
  expect(form.get('legacy')).toBe('1')
  expect((form.get('file') as File).name).toBe('old.png')
})

it('preserves a newer background selection while the upload is in flight', async () => {
  const {values} = setup()
  values.set('azurpilot.background', JSON.stringify({source: 'upload', kind: 'image', name: 'old.png', urls: [], active: 0}))
  let resolve!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise(done => { resolve = done })))
  const background = await import('./background')
  const pending = background.migrateStoredUpload()
  while (!resolve) await new Promise(done => setTimeout(done, 0))
  background.applyGalleryEntry({id: 'new', name: 'new.png', kind: 'image', size: 1, added: 0})
  resolve({ok: true, json: async () => ({entry: {id: 'legacy-id', kind: 'image', name: 'old.png'}})})
  await pending
  expect(background.getBackground().entry).toBe('new')
  expect(JSON.parse(values.get('azurpilot.background')!).entry).toBe('new')
})

it('reuses the saved import after preference persistence fails', async () => {
  const {values, blob, storage} = setup()
  values.set('azurpilot.background', JSON.stringify({source: 'off', kind: 'image', name: 'old.png', urls: [], active: 0}))
  values.set('azurpilot.background.plain', JSON.stringify({source: 'off', kind: 'image', name: 'old.png', urls: [], active: 0}))
  const set = storage.setItem.bind(storage)
  let fail = true
  vi.spyOn(storage, 'setItem').mockImplementation((key, value) => {
    if (key === 'azurpilot.background.plain' && fail) { fail = false; throw new Error('storage unavailable') }
    set(key, value)
  })
  const fetch = vi.fn().mockResolvedValue({ok: true, json: async () => ({entry: {id: 'legacy-id', kind: 'image', name: 'old.png'}})})
  vi.stubGlobal('fetch', fetch)
  const background = await import('./background')
  await background.migrateStoredUpload()
  expect(blob()).toBeDefined()
  await background.migrateStoredUpload()
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(JSON.parse(values.get('azurpilot.background.plain')!).entry).toBe('legacy-id')
  expect(blob()).toBeUndefined()
})

it('keeps the legacy selection when a gallery read follows a failed import', async () => {
  const {values} = setup()
  values.set('azurpilot.background', JSON.stringify({source: 'upload', kind: 'image', name: 'old.png', urls: [], active: 0}))
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
  const background = await import('./background')
  await background.migrateStoredUpload()
  background.reconcileGallery([{id: 'other', name: 'other.png', kind: 'image', size: 1, added: 0}])
  expect(background.getBackground().name).toBe('old.png')
  expect(background.getBackground().entry).toBeUndefined()
})

it('distinguishes a missing file from an IndexedDB read failure', async () => {
  const {values, setFile, failRead} = setup()
  values.set('azurpilot.background', JSON.stringify({source: 'upload', kind: 'image', name: 'old.png', urls: [], active: 0}))
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  const background = await import('./background')
  failRead(true)
  await background.migrateStoredUpload()
  expect(values.has('azurpilot.background.migrated')).toBe(false)
  expect(background.getBackground().legacy).toBe(true)
  failRead(false)
  setFile(undefined)
  await background.migrateStoredUpload()
  expect(values.get('azurpilot.background.migrated')).toBe('1')
  expect(background.getBackground().legacy).toBe(false)
  expect(fetch).not.toHaveBeenCalled()
})

it('migrates the latest legacy reference for each material even when its name changed', async () => {
  const {values} = setup()
  values.set('azurpilot.background', JSON.stringify({source: 'upload', kind: 'image', name: 'old.png', urls: [], active: 0}))
  let resolve!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise(done => { resolve = done })))
  const background = await import('./background')
  const pending = background.migrateStoredUpload()
  while (!resolve) await new Promise(done => setTimeout(done, 0))
  values.set('azurpilot.background.plain', JSON.stringify({source: 'off', kind: 'image', name: 'renamed.png', urls: [], active: 0}))
  resolve({ok: true, json: async () => ({entry: {id: 'legacy-id', kind: 'image', name: 'old.png'}})})
  await pending
  expect(JSON.parse(values.get('azurpilot.background.plain')!).entry).toBe('legacy-id')
})

it('honors an explicit non-legacy preference', async () => {
  const {values} = setup()
  values.set('azurpilot.background', JSON.stringify({source: 'upload', kind: 'image', name: 'old.png', legacy: false, urls: [], active: 0}))
  const background = await import('./background')
  expect(background.getBackground().legacy).toBe(false)
  background.reconcileGallery([{id: 'other', name: 'other.png', kind: 'image', size: 1, added: 0}])
  expect(background.getBackground().entry).toBe('other')
})

it('updates an active legacy snapshot after another tab completed migration', async () => {
  const {values, setFile} = setup()
  values.set('azurpilot.background', JSON.stringify({source: 'upload', kind: 'image', name: 'old.png', urls: [], active: 0}))
  const background = await import('./background')
  values.set('azurpilot.background', JSON.stringify({source: 'upload', kind: 'image', name: 'old.png', urls: [], active: 0, entry: 'legacy-id', legacy: false}))
  values.set('azurpilot.background.migrated', '1')
  setFile(undefined)
  await background.migrateStoredUpload()
  expect(background.getBackground().entry).toBe('legacy-id')
  expect(background.getBackground().assetUrl).toBe('/background-library/legacy-id')
  background.reconcileGallery([{id: 'legacy-id', name: 'old.png', kind: 'image', size: 1, added: 0}])
  expect(background.getBackground().entry).toBe('legacy-id')
})

it('updates the legacy snapshot if another tab commits during upload', async () => {
  const {values} = setup()
  values.set('azurpilot.background', JSON.stringify({source: 'upload', kind: 'image', name: 'old.png', urls: [], active: 0}))
  let resolve!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise(done => { resolve = done })))
  const background = await import('./background')
  const pending = background.migrateStoredUpload()
  while (!resolve) await new Promise(done => setTimeout(done, 0))
  values.set('azurpilot.background', JSON.stringify({source: 'upload', kind: 'image', name: 'old.png', urls: [], active: 0, entry: 'legacy-id', legacy: false}))
  values.set('azurpilot.background.migrated', '1')
  resolve({ok: true, json: async () => ({entry: {id: 'legacy-id', kind: 'image', name: 'old.png'}})})
  await pending
  expect(background.getBackground().entry).toBe('legacy-id')
  expect(background.getBackground().legacy).toBe(false)
})

it('does not adopt an unrelated newer preference when another tab finishes', async () => {
  const {values} = setup()
  values.set('azurpilot.background', JSON.stringify({source: 'upload', kind: 'image', name: 'old.png', urls: [], active: 0}))
  const background = await import('./background')
  values.set('azurpilot.background', JSON.stringify({source: 'upload', kind: 'image', name: 'different.png', urls: [], active: 0, entry: 'other'}))
  values.set('azurpilot.background.migrated', '1')
  await background.migrateStoredUpload()
  expect(background.getBackground().name).toBe('old.png')
  expect(background.getBackground().entry).toBeUndefined()
})


it('updates the active legacy preference after switching materials during upload', async () => {
  const {values} = setup()
  const legacy = JSON.stringify({source: 'upload', kind: 'image', name: 'old.png', urls: [], active: 0})
  values.set('azurpilot.background', legacy)
  values.set('azurpilot.background.plain', legacy)
  let resolve!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise(done => { resolve = done })))
  const background = await import('./background')
  const pending = background.migrateStoredUpload()
  while (!resolve) await new Promise(done => setTimeout(done, 0))
  theme.material = 'plain'
  theme.listeners.forEach(listener => listener())
  resolve({ok: true, json: async () => ({entry: {id: 'legacy-id', kind: 'image', name: 'old.png'}})})
  await pending
  expect(JSON.parse(values.get('azurpilot.background.plain')!).entry).toBe('legacy-id')
  expect(background.getBackground().entry).toBe('legacy-id')
  expect(background.getBackground().assetUrl).toBe('/background-library/legacy-id')
})
