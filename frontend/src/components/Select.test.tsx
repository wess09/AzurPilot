// @vitest-environment jsdom
/**
 * @fileoverview 下拉选择器的选项解析：`{cond && <option/>}` 与 `{options.map(...)}`
 * 会在 children 里留下 false 与嵌套数组，解析必须递归摊平，否则整组选项被丢掉，
 * 触发器只能回退显示带引号的 JSON 原始值。
 */
import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Select } from './Select'
import { AppContext, type AppContextValue } from '../app/context'

afterEach(cleanup)

function wrap(node: React.ReactNode) {
  const value = {ui: (key: string) => key, t: (key: string) => key} as unknown as AppContextValue
  return render(<AppContext.Provider value={value}>{node}</AppContext.Provider>)
}

describe('Select 选项解析', () => {
  it('map 出来的选项能给出 label，不显示带引号的原始值', () => {
    const options = ['normal', 'fast']
    const {getByRole} = wrap(
      <Select value={JSON.stringify('normal')} onChange={vi.fn()}>
        {false}
        {options.map(option => <option key={option} value={JSON.stringify(option)}>{option}</option>)}
      </Select>,
    )
    const trigger = getByRole('combobox')
    expect(trigger.textContent).toContain('normal')
    expect(trigger.textContent).not.toContain('"')
  })

  it('值不在选项里时显示该值本身，同样不带引号', () => {
    const {getByRole} = wrap(
      <Select value={JSON.stringify('slow')} onChange={vi.fn()}>
        {['normal', 'fast'].map(option => <option key={option} value={JSON.stringify(option)}>{option}</option>)}
      </Select>,
    )
    expect(getByRole('combobox').textContent).toContain('slow')
    expect(getByRole('combobox').textContent).not.toContain('"')
  })
})
