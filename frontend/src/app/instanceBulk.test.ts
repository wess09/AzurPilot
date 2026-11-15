/**
 * @fileoverview 实例一键启停的批量操作按钮状态判定。
 */
import {describe, expect, it} from 'vitest'
import type {Instance} from '../api/types'
import {bulkAction, bulkTargets} from './instanceBulk'

const make = (name: string, status: Instance['status']): Instance => ({name, status, serial: '', server: ''})

describe('一键启停', () => {
  it('全部在运行才暂停，其余情况一律启用', () => {
    expect(bulkAction([make('a', 'running'), make('b', 'running')])).toBe('stop')
    expect(bulkAction([make('a', 'running'), make('b', 'stopped')])).toBe('start')
    expect(bulkAction([make('a', 'stopped'), make('b', 'error')])).toBe('start')
    expect(bulkAction([])).toBe('start')
  })

  it('只挑真正需要改变状态的实例', () => {
    const instances = [make('a', 'running'), make('b', 'stopped'), make('c', 'error')]
    expect(bulkTargets(instances, 'start')).toEqual(['b', 'c'])
    expect(bulkTargets(instances, 'stop')).toEqual(['a'])
  })
})
