// @vitest-environment jsdom
/**
 * @fileoverview 启动器卡片状态行文案测试：状态机 + 后端字段 → 界面用语。
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { LauncherCard, launcherStatusText, type Phase } from './LauncherCard'

// vi.hoisted 先于 vi.mock 的工厂求值：把 api.onEvent 登记的监听器留出来，用例里手动派发启动器事件。
const {events} = vi.hoisted(() => ({events: {listener: undefined as undefined | ((event: {topic: string; data: unknown}) => void)}}))

// 界面文案桩成键名回显（断言对准 GUI 键，同下方 t 的用途），连接固定为 ready 让组件走已连接分支；api.request 由各用例自行编排返回值。
vi.mock('../app/context', () => ({
  useApp: () => ({t: (key: string) => key}),
  useConnection: () => 'ready',
}))
vi.mock('../api/client', () => ({
  api: {request: vi.fn(), onEvent: (listener: (event: {topic: string; data: unknown}) => void) => {
    events.listener = listener
    return () => {events.listener = undefined}
  }},
  ApiError: class ApiError extends Error {},
}))

afterEach(() => {
  cleanup()
  vi.mocked(api.request).mockReset()
})

/** 取词即回显键名，断言直接对准用到的 GUI 键。 */
const t = (key: string) => key

function text(phase: Phase, state: Partial<{enabled: boolean; pending: boolean; detail: string}> = {}) {
  return launcherStatusText(phase, {enabled: false, pending: false, detail: '', ...state}, t)
}

describe('启动器卡片状态行', () => {
  it('本机读取中与未连接各有专门文案', () => {
    expect(text('loading')).toBe('Gui.Launcher.Loading')
    expect(text('disconnected')).toBe('Gui.Launcher.Disconnected')
  })

  it('远端访问、平台不支持与设置中沿用既有提示', () => {
    expect(text('remote')).toBe('Gui.Launcher.RemoteUnavailable')
    expect(text('unsupported')).toBe('Gui.Launcher.Unsupported')
    expect(text('setting')).toBe('Gui.Launcher.Setting')
  })

  it('失败时附带原因', () => {
    expect(text('failed', {detail: '启动器未连接，请通过启动器打开 AzurPilot'}))
      .toBe('Gui.Launcher.Failed：启动器未连接，请通过启动器打开 AzurPilot')
  })

  it('已连接时区分「状态未知」「已开启」「已关闭」', () => {
    expect(text('ready', {pending: true})).toBe('Gui.Launcher.Connected · Gui.Launcher.Loading')
    expect(text('ready', {enabled: true})).toBe('Gui.Launcher.Connected · Gui.Launcher.Enabled')
    expect(text('ready')).toBe('Gui.Launcher.Connected · Gui.Launcher.Disabled')
  })
})

it('通过设置页开关提交启动器自启动状态', async () => {
  vi.mocked(api.request)
    .mockResolvedValueOnce({connected: true, autostart: {supported: true, enabled: false}, commands: []} as never)
    .mockResolvedValueOnce({commandId: 'command-1', status: 'pending'} as never)
    .mockResolvedValueOnce({connected: true, autostart: {supported: true, enabled: true}, commands: [{id: 'command-1', status: 'success'}]} as never)

  render(<LauncherCard/>)
  const control = await screen.findByRole('switch', {name: 'Gui.Launcher.AutoStart'})
  await waitFor(() => expect(control.hasAttribute('disabled')).toBe(false))
  fireEvent.click(control)
  await waitFor(() => expect(api.request).toHaveBeenCalledWith('launcher.autostart.set', {enabled: true}))
  await waitFor(() => expect(control.getAttribute('aria-checked')).toBe('true'))
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Gui.Launcher.Enabled'))
})

it('设置请求期间禁用开关，请求失败后恢复原状态', async () => {
  // 第二次请求挂起不返回：让开关停在「设置中」的禁用态，随后手动 reject 验证失败回滚。
  let rejectChange!: (error: Error) => void
  const pending = new Promise<never>((_, reject) => {rejectChange = reject})
  vi.mocked(api.request)
    .mockResolvedValueOnce({connected: true, autostart: {supported: true, enabled: false}, commands: []} as never)
    .mockReturnValueOnce(pending)

  render(<LauncherCard/>)
  const control = await screen.findByRole('switch', {name: 'Gui.Launcher.AutoStart'})
  await waitFor(() => expect(control.hasAttribute('disabled')).toBe(false))
  fireEvent.click(control)
  expect(control.getAttribute('aria-checked')).toBe('true')
  expect(control.hasAttribute('disabled')).toBe(true)
  fireEvent.click(control)
  expect(api.request).toHaveBeenCalledTimes(2)

  await act(async () => rejectChange(new Error('write failed')))
  expect(control.getAttribute('aria-checked')).toBe('false')
  expect(screen.getByRole('alert').textContent).toContain('write failed')
})

it('平台不支持自启动时禁用开关', async () => {
  vi.mocked(api.request).mockResolvedValueOnce({connected: true, autostart: {supported: false, enabled: null}, commands: []} as never)
  render(<LauncherCard/>)
  const control = await screen.findByRole('switch', {name: 'Gui.Launcher.AutoStart'})
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Gui.Launcher.Unsupported'))
  expect(control.hasAttribute('disabled')).toBe(true)
})

it('等待中的命令由启动器事件确认后恢复开关', async () => {
  vi.mocked(api.request)
    .mockResolvedValueOnce({connected: true, autostart: {supported: true, enabled: false}, commands: []} as never)
    .mockResolvedValueOnce({commandId: 'command-1', status: 'pending'} as never)
    .mockResolvedValueOnce({connected: true, autostart: {supported: true, enabled: false}, commands: [{id: 'command-1', status: 'pending'}]} as never)

  render(<LauncherCard/>)
  const control = await screen.findByRole('switch', {name: 'Gui.Launcher.AutoStart'})
  await waitFor(() => expect(control.hasAttribute('disabled')).toBe(false))
  fireEvent.click(control)
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Gui.Launcher.Setting'))
  expect(control.hasAttribute('disabled')).toBe(true)

  act(() => events.listener?.({topic: 'launcher', data: {
    connected: true, autostart: {supported: true, enabled: true}, commands: [{id: 'command-1', status: 'success'}],
  }}))
  expect(control.hasAttribute('disabled')).toBe(false)
  expect(control.getAttribute('aria-checked')).toBe('true')
  expect(screen.getByRole('status').textContent).toContain('Gui.Launcher.Enabled')
})
