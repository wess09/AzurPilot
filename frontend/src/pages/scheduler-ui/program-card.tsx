/**
 * 从 SchedulerProgram.tsx 原 25-55 行提取，纯搬迁未改动（仅新增导出）。
 * 画布节点卡片：按规格渲染标题、端口与内联参数，并注册为 react-flow 节点类型。
 */
import {memo, type CSSProperties} from 'react'
import {Handle, Position, useConnection as useFlowConnection, type NodeProps} from '@xyflow/react'
import {categoryColor, controlColor, getCardIcon, portColors, wildcardBackground} from '../../scheduler/appearance'
import {InlineParams} from '../../scheduler/InlineParams'
import type {CanvasNode} from '../../scheduler/Canvas'
import type {PortType} from '../../scheduler/types'
import {exits} from './labels'

export const Card = memo(function Card({data, selected}: NodeProps<CanvasNode>) {
  const {card, spec} = data
  const CardIcon = getCardIcon(card.type, spec.category)
  const isEntry = spec.type === 'entry' || card.type === 'entry' || Boolean(spec.entry)
  const connection = useFlowConnection<CanvasNode>()
  const connectingPort = connection.fromHandle?.id?.replace(/^data:/,'')
  const connectingType = connectingPort && connection.fromNode?.data.outputTypes[connectingPort]
  // 连线进行中：any 输入端口实时显示来源类型配色，提示当前连接是否兼容。
  const handleStyle = (declared: PortType, actual: PortType, input: boolean) => {
    const type = declared === 'any' && input && connectingType ? connectingType : actual
    return {background:type === 'any' ? wildcardBackground : portColors[type]}
  }
  return <div style={{'--card-color':categoryColor(spec.category)} as CSSProperties} className={`program-card ${spec.pure ? 'data' : 'action'} ${selected ? 'selected' : ''} ${data.current ? 'current' : ''} ${data.invalid ? 'invalid' : ''}`}>
    <div className="program-card-heading">{!spec.pure && !isEntry && <Handle type="target" position={Position.Left} id="control:in" className="control-handle" style={{background:controlColor}} title="执行入口"/>}<span className="program-card-category">{spec.category} · {spec.pure ? '数据' : '执行'}</span><strong className="program-card-title"><CardIcon size={16} className="program-card-icon" aria-hidden="true"/>{spec.label}</strong>{card.label && <small className="program-card-alias">名称：{card.label}</small>}</div>
    {card.comment && <div className="program-card-comment">{card.comment}</div>}
    {spec.exits.length > 0 && <div className="program-card-exits">{spec.exits.map(exit => <div key={exit} className="program-port output exit-port"><span>{exits[exit] ?? exit}</span><Handle type="source" position={Position.Right} id={`control:${exit}`} className="control-handle" style={{background:controlColor}} title={`${exits[exit] ?? exit} · 执行`}/></div>)}</div>}
    <InlineParams
      card={card}
      spec={spec}
      catalog={data.catalog}
      document={data.document}
      connectedInputs={data.connectedInputs}
      inputTypes={data.inputTypes}
      outputTypes={data.outputTypes}
      handleStyle={handleStyle}
      onChange={data.onParamsChange}
    />
  </div>
})
export const nodeTypes = {card: Card}
