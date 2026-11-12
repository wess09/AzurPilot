/**
 * @fileoverview 编辑器卡片的内嵌参数面板：常用参数与输入/输出端口一体化呈现。
 */

import {memo} from 'react'
import type {CSSProperties} from 'react'
import {Handle, Position} from '@xyflow/react'
import {useApp} from '../app/context'
import type {UiKey} from '../i18n'
import type {CardDefinition, Catalog, PortType, ProgramDocument, ProgramNode} from './types'
import {paramLabels, portColors, typeLabels, wildcardBackground} from './appearance'

interface InlineParamsProps {
  card: ProgramNode
  spec: CardDefinition
  catalog: Catalog
  document: ProgramDocument
  connectedInputs: string[]
  inputTypes?: Record<string, PortType>
  outputTypes?: Record<string, PortType>
  handleStyle?: (declared: PortType, actual: PortType, input: boolean) => CSSProperties
  onChange: (node: string, patch: Record<string, unknown>) => void
}

const fields: Record<string, Array<[string, string]>> = {
  resource: [['name', '读取资源'], ['field', '读取数值'], ['maxAge', '有效期（秒）'], ['autoRefresh', '过期时自动刷新']],
  task: [['name', '指定任务']],
  execute: [['task', '执行任务'], ['followOriginal', '检查原计划任务切换']],
  last_result: [['task', '任务结果']],
  wait: [['seconds', '等待秒数']],
  wait_until: [['time', '等待到'], ['recheckOnConfigChange', '配置变更时重新判断']],
  time_window: [['start', '开始时间'], ['end', '结束时间']],
  compare: [['operator', '比较方式'], ['a', '输入 A'], ['b', '输入 B']],
  math: [['operator', '运算方式'], ['a', '输入 A'], ['b', '输入 B']],
  logic: [['operator', '逻辑规则'], ['a', '输入 A'], ['b', '输入 B']],
  select: [['condition', '判断条件'], ['yes', '满足时输出'], ['no', '不满足时输出']],
  literal: [['valueType', '数据类型'], ['value', '常量']],
  get_variable: [['name', '变量']],
  set_variable: [['name', '变量'], ['value', '赋值']],
  loop: [['count', '循环次数'], ['condition', '继续循环']],
  filter: [['rule', '筛选规则']],
  sort: [['field', '排序字段'], ['descending', '降序']],
  cooldown: [['key', '记录标识'], ['seconds', '冷却秒数']],
  quota: [['key', '配额标识'], ['limit', '每日上限']],
  record: [['key', '记录标识'], ['kind', '记录类型']],
  call: [['graph', '组合卡片']],
  branch: [['condition', '条件']],
  field: [['field', '字段名']],
}

const valueTypes = ['number', 'boolean', 'string', 'time', 'duration', 'task', 'tasks', 'resource', 'result', 'list', 'object', 'any']

/**
 * 卡片下方的内嵌参数面板：纯配置字段逐行编辑，输入/输出端口与内联控件并排。
 * 端口已连线时对应控件禁用并显示「由连线提供」。
 */
export const InlineParams = memo(function InlineParams({
  card,
  spec,
  catalog,
  document,
  connectedInputs,
  inputTypes = {},
  outputTypes = {},
  handleStyle,
  onChange,
}: InlineParamsProps) {
  const {ui, t} = useApp()
  const values = {...spec.params, ...card.params}
  const resourceName = (name: string) => (name.startsWith('Emotion') ? `舰队 ${name.slice(-1)} 心情` : ui(`resource.${name}` as UiKey))
  const taskName = (name: string) => {
    const translated = t(`Task.${name}.name`)
    return translated.startsWith('Task.') ? name : translated
  }

  const defaultHandleStyle = (declared: PortType, actual: PortType) => ({
    background: declared === 'any' || actual === 'any' ? wildcardBackground : portColors[actual ?? declared] ?? portColors.any,
  })
  const getHandleStyle = handleStyle ?? defaultHandleStyle

  // 换 valueType 时把 value 重置成新类型的空值：控件按 typeof value 选形态，残留旧形态会渲染出错误控件。
  const update = (key: string, value: unknown) => {
    onChange(card.id, {
      ...{[key]: value},
      ...(key === 'valueType'
        ? {
            value:
              value === 'boolean'
                ? false
                : ['number', 'duration'].includes(String(value))
                ? 0
                : ['list', 'tasks'].includes(String(value))
                ? []
                : ['object', 'resource', 'task', 'result'].includes(String(value))
                ? {}
                : '',
          }
        : {}),
    })
  }

  const cardFieldEntries = fields[card.type] ?? []
  // 字段表里的键同时也是输入端口名的归端口区渲染，剩下的才是纯配置行。
  const configFields = cardFieldEntries.filter(([key]) => !spec.inputs.some(p => p.name === key))
  const portFieldMap = new Map(cardFieldEntries.filter(([key]) => spec.inputs.some(p => p.name === key)))

  const renderFieldControl = (key: string, label: string) => {
    const value = values[key]
    const connected = connectedInputs.includes(key)
    let options: Array<[string, string]> | undefined

    if (key === 'name' && card.type === 'resource') {
      options = catalog.resources.map(r => [r.name, resourceName(r.name)])
    } else if ((key === 'name' && card.type === 'task') || key === 'task') {
      options = catalog.tasks.map(task => [task.name, taskName(task.name)])
    } else if (key === 'field' && card.type === 'resource') {
      options = [
        ['value', values.name === 'ActionPoint' ? '当前行动力' : '当前值'],
        ['limit', '上限'],
        ['total', values.name === 'ActionPoint' ? '总行动力（含体力箱）' : '总量'],
      ]
    } else if (key === 'name' && card.type.includes('variable')) {
      options = document.variables.map(v => [v.name, v.name])
    } else if (key === 'graph') {
      options = document.subgraphs.map(s => [s.id, s.name])
    } else if (key === 'valueType') {
      options = valueTypes.map(type => [type, typeLabels[type as PortType] ?? type])
    } else if (key === 'operator') {
      if (card.type === 'logic') {
        options = [
          ['and', 'AND 且'],
          ['or', 'OR 或'],
          ['not', 'NOT 非'],
        ]
      } else if (card.type === 'math') {
        options = [
          ['+', '+ 加'],
          ['-', '- 减'],
          ['*', '× 乘'],
          ['/', '÷ 除'],
          ['%', '% 取模'],
          ['min', 'min 较小值'],
          ['max', 'max 较大值'],
        ]
      } else {
        options = [
          ['>=', '>= 大于等于'],
          ['>', '> 大于'],
          ['<=', '<= 小于等于'],
          ['<', '< 小于'],
          ['==', '== 等于'],
          ['!=', '!= 不等于'],
        ]
      }
    } else if (key === 'rule') {
      options = [
        ['enabled', '已启用'],
        ['due', '已到期'],
        ['field', '按字段判断'],
      ]
    } else if (key === 'kind' && card.type === 'record') {
      options = [
        ['quota', '配额记录'],
        ['cooldown', '冷却记录'],
      ]
    }

    if (!options && typeof value !== 'string' && typeof value !== 'number' && typeof value !== 'boolean') {
      return null
    }

    const inputId = `inline-${card.id}-${key}`

    if (options) {
      return (
        <select
          id={inputId}
          aria-label={label}
          disabled={connected}
          value={connected ? '__connected' : String(value ?? '')}
          onChange={e => update(key, e.target.value)}
        >
          {connected ? <option value="__connected">由连线提供</option> : <option value="">请选择…</option>}
          {options.map(([opt, txt]) => (
            <option key={opt} value={opt}>
              {txt}
            </option>
          ))}
        </select>
      )
    }

    if (typeof value === 'boolean') {
      return (
        <input
          id={inputId}
          type="checkbox"
          aria-label={label}
          disabled={connected}
          checked={Boolean(value)}
          onChange={e => update(key, e.target.checked)}
        />
      )
    }

    const isNumeric = typeof value === 'number' || (card.type === 'literal' && values.valueType === 'number')

    return (
      <input
        id={inputId}
        aria-label={label}
        type={
          connected
            ? 'text'
            : isNumeric
            ? 'number'
            : key === 'start' || key === 'end' || (key === 'time' && String(value).length <= 5)
            ? 'time'
            : 'text'
        }
        disabled={connected}
        value={connected ? '由连线提供' : String(value ?? '')}
        onChange={e => update(key, isNumeric ? Number(e.target.value) : e.target.value)}
      />
    )
  }

  const hasContent = configFields.length > 0 || spec.inputs.length > 0 || spec.outputs.length > 0

  if (!hasContent) {
    return null
  }

  return (
    <div className="program-card-settings nodrag nopan nowheel nokey">
      {/* 1. 顶部纯配置字段 */}
      {configFields.length > 0 && (
        <div className="program-card-configs">
          {configFields.map(([key, label]) => {
            const inputId = `inline-${card.id}-${key}`
            const value = values[key]
            const isCheckbox = typeof value === 'boolean' && key !== 'operator' && key !== 'rule'
            return (
              <div key={key} className={isCheckbox ? 'program-card-checkbox' : 'program-card-field'}>
                <label htmlFor={inputId}>{label}</label>
                {renderFieldControl(key, label)}
              </div>
            )
          })}
          {card.type === 'resource' && (
            <small className="program-card-resource-note">
              {catalog.resources.find(r => r.name === values.name)?.refreshable ? '可在任务边界刷新' : '读取任务观察记录'}
            </small>
          )}
        </div>
      )}

      {/* 2. 输入端口区（端口与内联输入控件并排一体） */}
      {spec.inputs.length > 0 && (
        <div className="program-card-inputs">
          {spec.inputs.map(p => {
            const inlineLabel = portFieldMap.get(p.name)
            const label = inlineLabel ?? (paramLabels[p.name] ?? p.name)
            const connected = connectedInputs.includes(p.name)
            const actualType = inputTypes[p.name] ?? p.type
            const hasControl = portFieldMap.has(p.name)
            const inputId = `inline-${card.id}-${p.name}`

            return (
              <div
                key={p.name}
                className={`program-port-row program-input-port ${connected ? 'connected' : ''} ${hasControl ? 'with-control' : ''}`}
              >
                <Handle
                  type="target"
                  position={Position.Left}
                  id={`data:${p.name}`}
                  style={getHandleStyle(p.type, actualType, true)}
                  title={`${label} · ${typeLabels[p.type] ?? p.type}`}
                />
                <div className="program-port-info">
                  <label htmlFor={hasControl ? inputId : undefined} className="program-port-label">
                    {label}
                  </label>
                  <span className="program-port-type-tag">{typeLabels[actualType] ?? actualType}</span>
                </div>
                {hasControl ? (
                  <div className="program-port-control">
                    {renderFieldControl(p.name, label)}
                  </div>
                ) : connected ? (
                  <div className="program-port-control">
                    <span className="program-port-badge">已连线</span>
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      )}

      {/* 3. 输出端口区 */}
      {spec.outputs.length > 0 && (
        <div className="program-card-outputs">
          {spec.outputs.map(p => {
            const label = paramLabels[p.name] ?? p.name
            const actualType = outputTypes[p.name] ?? p.type

            return (
              <div key={p.name} className="program-port-row program-output-port">
                <div className="program-port-info output">
                  <span className="program-port-label">{label}</span>
                  <span className="program-port-type-tag">{typeLabels[actualType] ?? actualType}</span>
                </div>
                <Handle
                  type="source"
                  position={Position.Right}
                  id={`data:${p.name}`}
                  style={getHandleStyle(p.type, actualType, false)}
                  title={`${label} · ${typeLabels[p.type] ?? p.type}`}
                />
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
})
