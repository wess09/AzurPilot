/**
 * @fileoverview 远程访问状态聚合（disabled/configuring/ready）测试。
 */
import { describe, expect, it } from 'vitest'
import { remoteStatus } from './remoteStatus'

describe('remoteStatus', () => {
  it('未启用时是 disabled', () => {
    expect(remoteStatus('stopped', false)).toBe('disabled')
    expect(remoteStatus('direct_p2p', false)).toBe('disabled')
  })

  it('已分配到地址的等待连接算就绪', () => {
    expect(remoteStatus('waiting_peer', true)).toBe('ready')
    expect(remoteStatus('direct_p2p', true)).toBe('ready')
    expect(remoteStatus('turn_relay', true)).toBe('ready')
    expect(remoteStatus('ssh_forward', true)).toBe('ready')
  })

  it('启动与重连阶段是 starting', () => {
    expect(remoteStatus('starting', true)).toBe('starting')
    expect(remoteStatus('signaling', true)).toBe('starting')
    expect(remoteStatus('reconnecting', true)).toBe('starting')
  })

  it('失败与未知状态归入 failed', () => {
    for (const state of ['failed', 'dependency_missing', 'ssh_not_found', 'stopped', 'wat', undefined]) {
      expect(remoteStatus(state, true)).toBe('failed')
    }
  })
})
