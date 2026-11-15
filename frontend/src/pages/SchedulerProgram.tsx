/**
 * @fileoverview 卡片式调度编辑器：图、属性、隔离模拟和运行轨迹。
 */
import {ReactFlowProvider} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import '../scheduler/editor.css'
import {Editor} from './scheduler-ui/editor'

/** 调度程序页入口：react-flow 的 hook 必须在 Provider 内使用，Editor 由这里统一包一层。 */
export function SchedulerProgram() {return <ReactFlowProvider><Editor/></ReactFlowProvider>}
