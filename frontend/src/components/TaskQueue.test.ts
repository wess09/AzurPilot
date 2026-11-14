/** @fileoverview 调度栏任务条目移动判定的回归：静止不动画、亚像素抖动与跨组反向位移。 */

import { describe, expect, it } from 'vitest'
import { movedBy } from './TaskQueue'

describe('任务条目在调度栏内移动的判定', () => {
  it('首次出现没有可比位置，不播动画', () => {
    expect(movedBy(undefined, {left: 10, top: 20})).toBeNull()
  })

  it('位置没动就不播动画', () => {
    expect(movedBy({left: 10, top: 20}, {left: 10, top: 20})).toBeNull()
  })

  it('亚像素抖动不算移动', () => {
    expect(movedBy({left: 10, top: 20}, {left: 10.4, top: 20.3})).toBeNull()
  })

  it('移到别的分组时给出反向位移，用作动画起点', () => {
    expect(movedBy({left: 10, top: 200}, {left: 10, top: 60})).toEqual({dx: 0, dy: 140})
  })

  it('左右方向的变化同样给出位移', () => {
    expect(movedBy({left: 300, top: 20}, {left: 120, top: 20})).toEqual({dx: 180, dy: 0})
  })
})
