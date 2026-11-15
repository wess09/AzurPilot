/** @fileoverview 配置输入控件的渲染回归：显式类型声明优先于旧配置里的数字值。 */

import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AppContext, type AppContextValue } from '../app/context'
import { translateUi } from '../i18n'
import { FieldInput } from './FieldInput'

describe('配置输入控件', () => {
  it('显式文本模式不会被旧的数字配置值改回数字输入框', () => {
    const html = renderToStaticMarkup(
      <AppContext.Provider value={{ui: (key, params) => translateUi('zh-CN', key, params)} as AppContextValue}>
        <FieldInput id="target-zone" label="指定海域" type="input" mode="text" value={12} onChange={vi.fn()}/>
      </AppContext.Provider>,
    )

    expect(html).toContain('type="text"')
    expect(html).not.toContain('inputMode="decimal"')
  })
})
