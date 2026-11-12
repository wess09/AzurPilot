// @vitest-environment jsdom
/**
 * @fileoverview 系统设置页保存状态的回归测试：草稿保留、错误提示与静默期。
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Edit } from '../config/EditQueue'
import { Settings } from './Settings'

// vi.mock 的工厂会被提升到文件最前，用例要驱动的共享状态必须用 vi.hoisted 同层提升才能被工厂引用。
const {state} = vi.hoisted(() => ({
  state: {
    data: {groups: [{key: 'Git', fields: [
      {key: 'Branch', type: 'string', label: 'Branch', help: '', value: 'dev', options: []},
      {key: 'Port', type: 'int', label: 'Port', help: '', value: 10, options: []},
      {key: 'SSLVerify', type: 'bool', label: 'SSL verification', help: 'Verify certificates', value: false, options: []},
    ]}], demo: false},
    error: '',
    edits: {edits: {} as Record<string, Edit>, storageError: ''},
    queue: {change: vi.fn((..._args: unknown[]) => {}), retry: vi.fn(), savedVisible: vi.fn(() => true)},
  },
}))

// ui 桩成「键名 + 错误参数」直出：断言直接对键名，不必维护一份翻译表。
vi.mock('../app/context', () => ({
  useApp: () => ({t: (key: string) => key, ui: (key: string, params?: {error?: string}) => `${key}${params?.error ?? ''}`}),
}))
vi.mock('../app/useDeploySettings', () => ({useDeploySettings: () => state}))
vi.mock('../components/LauncherCard', () => ({LauncherCard: () => null}))

beforeEach(() => {
  state.error = ''
  state.data.demo = false
  state.edits = {edits: {}, storageError: ''}
  state.queue.change.mockClear()
  state.queue.retry.mockClear()
  state.queue.savedVisible.mockReturnValue(true)
})
afterEach(cleanup)

describe('系统设置保存状态', () => {
  it('保留错误草稿，提供关联提示和可重试操作', () => {
    state.edits.edits.Branch = {value: 'draft', payload: 'draft', sequence: 1, status: 'error', error: 'offline', retryable: true}
    render(<Settings/>)
    const input = screen.getByRole('textbox', {name: 'Branch'})
    expect((input as HTMLInputElement).value).toBe('draft')
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(input.getAttribute('aria-describedby')).toBe('deploy-Branch-description deploy-Branch-status')
    expect(screen.getByRole('alert').textContent).toContain('offline')
    fireEvent.click(screen.getByRole('button', {name: 'edit.retry'}))
    expect(state.queue.retry).toHaveBeenCalledOnce()
  })

  it('在保存时公布状态，分别显示读取和草稿存储错误', () => {
    state.error = '读取失败'
    state.edits.storageError = '草稿存储失败'
    state.edits.edits.Branch = {value: 'draft', payload: 'draft', sequence: 1, status: 'saving'}
    render(<Settings/>)
    expect(screen.getAllByRole('alert').map(item => item.textContent)).toEqual(['读取失败', '草稿存储失败'])
    expect(screen.getByRole('status').textContent).toBe('edit.saving')
  })

  it('保留非法数字并交给队列处理校验错误', () => {
    render(<Settings/>)
    const input = screen.getByRole('textbox', {name: 'Port'})
    fireEvent.focus(input)
    fireEvent.change(input, {target: {value: '--'}})
    fireEvent.blur(input)
    expect(state.queue.change).toHaveBeenCalledOnce()
    const [path, text, payload, error] = state.queue.change.mock.calls[0]
    expect([path, text, payload]).toEqual(['Port', '--', '--'])
    expect(error).toEqual(expect.any(String))
  })

  it('不在保存静默期显示状态', () => {
    state.edits.edits.Branch = {value: 'saved', payload: 'saved', sequence: 1, status: 'saved'}
    state.queue.savedVisible.mockReturnValue(false)
    render(<Settings/>)
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('布尔开关向保存队列提交布尔值', () => {
    render(<Settings/>)
    const control = screen.getByRole('switch', {name: 'SSL verification'})
    expect(control.getAttribute('aria-describedby')).toBe('deploy-SSLVerify-description')
    fireEvent.click(control)
    expect(state.queue.change).toHaveBeenCalledExactlyOnceWith('SSLVerify', true, true, undefined)
  })

  it('演示模式禁用字段并阻止提交', () => {
    state.data.demo = true
    render(<Settings/>)
    const input = screen.getByRole('textbox', {name: 'Branch'})
    const control = screen.getByRole('switch', {name: 'SSL verification'})
    expect(input.hasAttribute('disabled')).toBe(true)
    expect(control.hasAttribute('disabled')).toBe(true)
    fireEvent.click(control)
    expect(state.queue.change).not.toHaveBeenCalled()
  })
})
