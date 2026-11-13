import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { translateCurrentUi } from '../i18n'
import { EditQueue } from './EditQueue'
import { prepareValue } from './editors'

function storage() {
  const values = new Map<string, string>()
  return {getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => {values.set(key, value)}, removeItem: (key: string) => {values.delete(key)}}
}
function deferred() {
  let resolve!: () => void
  let reject!: (error: Error) => void
  const promise = new Promise<void>((yes, no) => {resolve = yes; reject = no})
  return {promise, resolve, reject}
}
afterEach(() => vi.useRealTimers())

describe('即时配置队列', () => {
  it('输入时立即发送，旧响应不会撤销后续输入，并串行提交最终值', async () => {
    const first = deferred()
    const send = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(undefined)
    const queue = new EditQueue('test', {ready: () => true, send}, storage())
    queue.change('serial', 'first')
    expect(send).toHaveBeenCalledWith('serial', 'first')
    queue.change('serial', 'second')
    queue.change('serial', 'latest')
    expect(queue.getSnapshot().edits.serial.value).toBe('latest')
    expect(send).toHaveBeenCalledTimes(1)
    first.resolve()
    await queue.settled()
    expect(send.mock.calls).toEqual([['serial', 'first'], ['serial', 'latest']])
    expect(queue.getSnapshot().edits.serial).toMatchObject({value: 'latest', status: 'saved'})
  })

  it('格式错误保留原文，其他字段独立保存，修正后立即重试', async () => {
    const send = vi.fn().mockRejectedValueOnce(new ApiError('INVALID_PARAMS', '日期格式不正确')).mockResolvedValue(undefined)
    const queue = new EditQueue('test', {ready: () => true, send}, storage())
    queue.change('date', '2026-')
    queue.change('enabled', true)
    await queue.flush()
    expect(queue.getSnapshot().edits.date).toMatchObject({value: '2026-', status: 'error'})
    expect(queue.getSnapshot().edits.enabled.status).toBe('saved')
    await expect(queue.settled()).rejects.toThrow(translateCurrentUi('edit.unsaved'))
    queue.change('date', '2026-09-14 12:00:00')
    await queue.settled()
    expect(queue.getSnapshot().edits.date.status).toBe('saved')
  })

  it('旧请求失败不能将新输入标记为错误', async () => {
    const first = deferred()
    const send = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue(undefined)
    const queue = new EditQueue('test', {ready: () => true, send}, storage())
    queue.change('number', '-')
    queue.change('number', '12', 12)
    first.reject(new ApiError('INVALID_PARAMS', '必须是整数'))
    await queue.settled()
    expect(queue.getSnapshot().edits.number).toMatchObject({value: '12', payload: 12, status: 'saved'})
  })

  it('离线和刷新不丢失草稿，恢复全部字段，已保存字段不再重放', async () => {
    const memory = storage()
    const send = vi.fn().mockResolvedValue(undefined)
    const first = new EditQueue('instance-a', {ready: () => false, send}, memory)
    first.change('serial', 'offline')
    first.change('number', '-', '-', '请输入数字')
    expect(send).not.toHaveBeenCalled()
    const restored = new EditQueue('instance-a', {ready: () => true, send}, memory)
    await restored.flush()
    expect(send.mock.calls).toEqual([['serial', 'offline']])
    expect(restored.getSnapshot().edits.number).toMatchObject({value: '-', status: 'error'})
    const again = new EditQueue('instance-a', {ready: () => true, send}, memory)
    expect(again.getSnapshot().edits.serial).toBeUndefined()
    expect(again.getSnapshot().edits.number.value).toBe('-')
  })

  it('恢复草稿时丢弃服务端已拒绝的空值，字段回到配置里的值', () => {
    const memory = storage()
    // 空值没有可修正的内容，却会把字段永久钉死：字段本来就是空的，用户再清空
    // 不会触发输入事件，草稿永远换不掉。
    memory.setItem('instance-stuck', JSON.stringify({
      'Main.Scheduler.NextRun': {value: '', payload: '', sequence: 1, status: 'error', retryable: false, error: '日期格式应为 YYYY-MM-DD HH:mm:ss：Main.Scheduler.NextRun'},
    }))
    const queue = new EditQueue('instance-stuck', {ready: () => true, send: vi.fn()}, memory)
    expect(queue.getSnapshot().edits['Main.Scheduler.NextRun']).toBeUndefined()
  })

  it('恢复草稿时保留非空的错误原文，用户仍可修正', () => {
    const memory = storage()
    memory.setItem('instance-stuck', JSON.stringify({
      date: {value: '2026-', payload: '2026-', sequence: 1, status: 'error', retryable: false, error: '日期格式不正确'},
    }))
    const queue = new EditQueue('instance-stuck', {ready: () => true, send: vi.fn()}, memory)
    expect(queue.getSnapshot().edits.date).toMatchObject({value: '2026-', status: 'error'})
  })

  it('断线和超时会自动重试，其他实例的队列不受影响', async () => {
    vi.useFakeTimers()
    const send = vi.fn().mockRejectedValueOnce(new ApiError('TIMEOUT', '请求超时')).mockResolvedValue(undefined)
    const memory = storage()
    const queue = new EditQueue('a', {ready: () => true, send}, memory)
    queue.change('serial', 'retained')
    await queue.flush()
    expect(queue.getSnapshot().edits.serial.value).toBe('retained')
    const other = new EditQueue('b', {ready: () => true, send}, memory)
    other.change('serial', 'other')
    await other.settled()
    await vi.advanceTimersByTimeAsync(1000)
    expect(send.mock.calls).toEqual([['serial', 'retained'], ['serial', 'other'], ['serial', 'retained']])
    expect(queue.getSnapshot().edits.serial.status).toBe('saved')
  })

  it('浏览器存储失败不打断输入和提交，并明确提示', async () => {
    const send = vi.fn().mockResolvedValue(undefined)
    const queue = new EditQueue('test', {ready: () => true, send})
    queue.change('serial', 'retained')
    await queue.settled()
    expect(send).toHaveBeenCalledWith('serial', 'retained')
    expect(queue.getSnapshot().storageError).toBe(translateCurrentUi('edit.draftPersistError'))
  })
})

describe('保留数值输入原文', () => {
  const field = {type: 'int', value: 3, validate: [1, 10]}
  it.each(['-', '1e', 'abc', 'Infinity', '1.5', '11', '9007199254740993'])('拒绝不完整或不合法的数值 %s', value => {
    expect(prepareValue(value, field).error).toBeTruthy()
  })
  it('只转换提交值，不改写原始文本', () => {
    expect(prepareValue('03', field)).toEqual({payload: 3})
    expect(prepareValue('1.50', {type: 'float', value: 0.5})).toEqual({payload: 1.5})
    expect(prepareValue('1.50', {type: 'input', value: 1})).toEqual({payload: 1.5})
    expect(prepareValue('9007199254740993', {type: 'input', value: 1}).error).toBeTruthy()
  })
  it('文本默认值允许提交逗号分隔的海域列表', () => {
    expect(prepareValue('12, 13, 71, 73', {type: 'input', value: '0'})).toEqual({payload: '12, 13, 71, 73'})
  })
  it('比例参数遵循显式小数类型，兼容默认值在 JSON 中写成整数', () => {
    const ratio = {type: 'input', value: 1, valuetype: 'float', validate: [0, 1]}
    for (const value of ['0', '0.2', '.5', '1.0', ' 2e-1 ']) {
      expect(prepareValue(value, ratio)).toEqual({payload: Number(value)})
    }
    for (const value of ['-0.1', '1.1', '1000', 'Infinity']) {
      expect(prepareValue(value, ratio).error).toBeTruthy()
    }
  })
  it('整数参数接受等值数字写法，但不能保存实际的小数', () => {
    const integer = {type: 'input', value: 0, valuetype: 'int'}
    for (const value of [' 2 ', '2.0', '+02', '2e0']) {
      expect(prepareValue(value, integer)).toEqual({payload: 2})
    }
    expect(prepareValue('2.5', integer).error).toBeTruthy()
    expect(prepareValue(' 001 ', {type: 'input', value: 0, valuetype: 'str'})).toEqual({payload: ' 001 '})
  })
})

describe('清空时回落到参数默认值', () => {
  const datetime = {type: 'datetime', value: '2020-01-01 00:00:00', validate: 'datetime'}
  it('清空时间后提交参数默认值，输入框同步显示它', () => {
    expect(prepareValue('', datetime)).toEqual({payload: '2020-01-01 00:00:00', text: '2020-01-01 00:00:00'})
  })
  it('清空数字后同样回落，不再提示格式错误', () => {
    expect(prepareValue('', {type: 'input', value: 119})).toEqual({payload: 119, text: '119'})
    expect(prepareValue('', {type: 'int', value: 3, validate: [1, 10]})).toEqual({payload: 3, text: '3'})
  })
  it('只有清空才改写文本，输入中的值原样提交', () => {
    expect(prepareValue('2026-09-19 12:00:00', datetime)).toEqual({payload: '2026-09-19 12:00:00'})
    expect(prepareValue('03', {type: 'int', value: 3, validate: [1, 10]})).toEqual({payload: 3})
  })
  it('声明 preserve_empty 的字段保留空值本身', () => {
    expect(prepareValue('', {type: 'int', value: 3, preserve_empty: true}).error).toBeTruthy()
  })
  it('默认值缺失时维持原有的报错行为', () => {
    expect(prepareValue('', {type: 'int', value: null}).error).toBeTruthy()
  })
  it('文本字段被全部清空时自动还原为参数默认值', () => {
    expect(prepareValue('', {type: 'input', value: 'text'})).toEqual({payload: 'text', text: 'text'})
    expect(prepareValue('   ', {type: 'input', value: '127.0.0.1:5555'})).toEqual({payload: '127.0.0.1:5555', text: '127.0.0.1:5555'})
    expect(prepareValue('', {type: 'textarea', value: 'EquipUR > EquipSSR'})).toEqual({payload: 'EquipUR > EquipSSR', text: 'EquipUR > EquipSSR'})
  })
  it('声明 preserve_empty 的文本字段保留空值本身', () => {
    expect(prepareValue('', {type: 'input', value: 'text', preserve_empty: true})).toEqual({payload: ''})
    expect(prepareValue('', {type: 'textarea', value: '', preserve_empty: true})).toEqual({payload: ''})
  })
  it('默认值本身为空或缺失时清空保留空值', () => {
    expect(prepareValue('', {type: 'input', value: ''})).toEqual({payload: ''})
    expect(prepareValue('', {type: 'input', value: null})).toEqual({payload: ''})
  })
})

describe('字段保存成功后回传服务端配置', () => {
  it('把 send 的返回值交给 onSaved，供页面替换本地配置', async () => {
    const config = {values: {Alas: {Scheduler: {Enable: true}}}}
    const send = vi.fn().mockResolvedValue(config)
    const queue = new EditQueue('test', {ready: () => true, send}, storage())
    const onSaved = vi.fn()
    queue.onSaved = onSaved
    queue.change('Alas.Scheduler.Enable', true, true)
    await queue.settled()
    expect(onSaved).toHaveBeenCalledWith(config)
  })

  it('被更新的输入顶掉的旧响应不再回传', async () => {
    const first = deferred()
    const send = vi.fn()
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValue({values: {}})
    const queue = new EditQueue('test', {ready: () => true, send}, storage())
    const onSaved = vi.fn()
    queue.onSaved = onSaved
    queue.change('Alas.Scheduler.Enable', true, true)
    void queue.flush()
    queue.change('Alas.Scheduler.Enable', false, false)
    first.resolve()
    await queue.settled()
    expect(onSaved).toHaveBeenCalledTimes(1)
    expect(onSaved).toHaveBeenCalledWith({values: {}})
  })
})
