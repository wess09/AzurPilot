import { beforeEach, describe, expect, it, vi } from 'vitest'

// 模块在导入时就会往 document 上落一次档位，所以桩必须早于导入建立。
const stubs = vi.hoisted(() => {
  const values = new Map<string, string>()
  const dataset: Record<string, string> = {}
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value) },
    removeItem: (key: string) => { values.delete(key) },
  })
  vi.stubGlobal('document', {documentElement: {dataset}})
  return {values, dataset}
})

const {readTabSize, setTabSize, TAB_SIZES} = await import('./topbarPrefs')

beforeEach(() => {
  stubs.values.clear()
})

describe('实例标签栏大小', () => {
  it('保存四个档位并应用到 :root', () => {
    expect(TAB_SIZES).toEqual(['sm', 'md', 'lg', 'xl'])
    for (const size of TAB_SIZES) {
      setTabSize(size)
      expect(readTabSize()).toBe(size)
      expect(stubs.dataset.tabSize).toBe(size)
    }
  })

  it('没存过档位时落在第三档', () => {
    expect(readTabSize()).toBe('lg')
  })
})
