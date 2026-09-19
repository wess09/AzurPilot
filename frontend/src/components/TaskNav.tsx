import { useApp } from '../app/context'
import { usesLegacyLayout } from '../app/theme'
import { TaskNavFlyout } from './TaskNavFlyout'
import { TaskNavTree } from './TaskNavTree'

/**
 * 侧栏任务菜单按主题分流：
 * 旧版主题用「分组展开、具体任务往下列」的树状菜单（旧 WebUI 的格式），
 * 其余主题继续用向右浮出的二级菜单。
 */
export function TaskNav({ defaultOpenKey }: { defaultOpenKey?: string } = {}) {
  const { theme } = useApp()
  return usesLegacyLayout(theme)
    ? <TaskNavTree defaultOpenKey={defaultOpenKey}/>
    : <TaskNavFlyout defaultOpenKey={defaultOpenKey}/>
}
