// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SettingsField } from './SettingsField'

vi.mock('../app/context', () => ({useApp: () => ({ui: (key: string) => key})}))

afterEach(cleanup)

const common = {id: 'deploy-value', label: 'Value', options: [], disabled: false, invalid: false}

describe('系统设置字段', () => {
  it('保留文本草稿并在失焦时提交', () => {
    const onChange = vi.fn()
    render(<SettingsField {...common} type="int" value={10} onChange={onChange}/>)
    const input = screen.getByRole('textbox', {name: 'Value'})
    fireEvent.focus(input)
    fireEvent.change(input, {target: {value: '-12'}})
    expect(onChange).not.toHaveBeenCalled()
    fireEvent.blur(input)
    expect(onChange).toHaveBeenCalledExactlyOnceWith('-12')
  })

  it('没有选项元数据时仍可编辑旧设置字段', () => {
    const onChange = vi.fn()
    render(<SettingsField {...common} options={undefined} type="string" value="old" onChange={onChange}/>)
    const input = screen.getByRole<HTMLInputElement>('textbox', {name: 'Value'})
    expect(input.value).toBe('old')
    fireEvent.focus(input)
    fireEvent.change(input, {target: {value: 'new'}})
    fireEvent.blur(input)
    expect(onChange).toHaveBeenCalledExactlyOnceWith('new')
  })

  it('编辑期间保留草稿，回车提交后恢复服务端值', async () => {
    const onChange = vi.fn()
    const view = render(<SettingsField {...common} type="string" value="initial" onChange={onChange}/>)
    const input = screen.getByRole<HTMLInputElement>('textbox', {name: 'Value'})
    act(() => input.focus())
    fireEvent.change(input, {target: {value: 'draft'}})
    view.rerender(<SettingsField {...common} type="string" value="remote" onChange={onChange}/>)
    expect(input.value).toBe('draft')
    fireEvent.keyDown(input, {key: 'Enter'})
    expect(onChange).toHaveBeenCalledExactlyOnceWith('draft')
    await waitFor(() => expect(input.value).toBe('remote'))
  })

  it('密码显示切换保留输入并反映无效状态', () => {
    const onChange = vi.fn()
    render(<SettingsField {...common} type="password" value="example" invalid onChange={onChange}/>)
    const input = screen.getByLabelText<HTMLInputElement>('Value')
    expect(input.type).toBe('password')
    expect(input.getAttribute('aria-describedby')).toBe('deploy-value-status')
    fireEvent.click(screen.getByRole('button', {name: 'common.showPassword'}))
    expect(input.type).toBe('text')
    expect(input.value).toBe('example')
    expect(screen.getByRole('button', {name: 'common.hidePassword'}).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByRole('button', {name: 'common.hidePassword'}))
    expect(input.type).toBe('password')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('开关提交布尔值并反映禁用状态', () => {
    const onChange = vi.fn()
    const view = render(<SettingsField {...common} type="bool" value={false} onChange={onChange}/>)
    fireEvent.click(screen.getByRole('switch', {name: 'Value'}))
    expect(onChange).toHaveBeenCalledExactlyOnceWith(true)
    view.rerender(<SettingsField {...common} type="bool" value={true} disabled onChange={onChange}/>)
    expect(screen.getByRole('switch', {name: 'Value'}).hasAttribute('disabled')).toBe(true)
  })

  it('选项保留原有值类型和未列出的当前值', async () => {
    const onChange = vi.fn()
    // jsdom 未实现 scrollIntoView；radix Select 选中项时会调用它，桩掉避免用例中断。
    Object.defineProperty(Element.prototype, 'scrollIntoView', {configurable: true, value: vi.fn()})
    try {
      render(<SettingsField {...common} type="select" value={3} options={[1, 2]} onChange={onChange}/>)
      const trigger = screen.getByRole('combobox', {name: 'Value'})
      expect(trigger.textContent).toContain('3')
      fireEvent.keyDown(trigger, {key: 'ArrowDown'})
      fireEvent.click(await screen.findByRole('option', {name: '2'}))
      await waitFor(() => expect(onChange).toHaveBeenCalledExactlyOnceWith(2))
    } finally {
      delete (Element.prototype as {scrollIntoView?: Element['scrollIntoView']}).scrollIntoView
    }
  })
})
