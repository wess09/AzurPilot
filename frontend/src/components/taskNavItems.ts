/**
 * @fileoverview 侧栏导航项拼装：把任务表与独立 WebUI 页面合并成导航序列，
 * 并提供搜索命中的归属任务换算与导航显示名换算。
 */

/** 仅提供 WebUI 页面的导航项，不注册成可执行的游戏任务。 */
const SCHEDULER_EDITOR = 'SchedulerProgram'
const FLEET_ANALYSIS = 'FleetAnalysis'
export const FLEET_SWITCH = 'FleetSwitch'
export const FLEET_ROTATION = 'FleetRotation'
export const FLEET_EQUIPMENT = 'FleetEquipment'
export const FLEET_LEVEL_TRAINING = 'FleetLevelTraining'
export const FLEET_AFFINITY_TRAINING = 'FleetAffinityTraining'
export const FLEET_TRAINING = 'FleetTraining'
/**
 * 拼出某个分组下的导航项序列：DockScan 永不进导航；舰队管理组前置智能换船、
 * 隐藏 FleetInfo 并把舰船数据追加在末尾；系统组在首个任务后插入自定义调度页。
 */
export function taskNavItems(key: string | null, tasks: string[]) {
  tasks = tasks.filter(task => task !== 'DockScan')
  if (key === 'FleetManagement') return [FLEET_SWITCH, ...tasks.filter(task => task !== 'FleetInfo'), FLEET_ANALYSIS]
  // tasks[0]! 的前提：Alas 分组始终带有任务，否则这里会插入 undefined。
  return key === 'Alas' ? [tasks[0]!, SCHEDULER_EDITOR, ...tasks.slice(1)] : tasks
}

/** 查出一条命中项属于哪个任务：配置树是「任务 → 分组 → 配置项」三层，文案里只有后两层。 */
export function ownerTaskOf(args: Record<string, Record<string, Record<string, unknown>>>, group: string, arg: string): string | undefined {
  return Object.keys(args).find(task => Boolean(args[task]?.[group]?.[arg]))
}

/** 卡片级命中的归属任务：只要求该任务有这张卡片（分组），没有具体配置项。 */
export function ownerTaskOfGroup(args: Record<string, Record<string, Record<string, unknown>>>, group: string): string | undefined {
  return Object.keys(args).find(task => Boolean(args[task]?.[group]))
}

/** 独立 WebUI 页面使用界面翻译，其余取任务表里的显示名。 */
export function taskLabel(task: string, ui: (key: 'analysis.title' | 'nav.schedulerProgram' | 'rotation.pageTitle' | 'rotation.title' | 'fleetEquipment.title' | 'training.title') => string, t: (key: string) => string) {
  if (task === FLEET_SWITCH) return ui('rotation.pageTitle')
  if (task === FLEET_TRAINING || task === FLEET_LEVEL_TRAINING || task === FLEET_AFFINITY_TRAINING) return ui('training.title')
  return task === FLEET_ANALYSIS ? ui('analysis.title') : task === FLEET_EQUIPMENT ? ui('fleetEquipment.title') : task === FLEET_ROTATION ? ui('rotation.title') : task === SCHEDULER_EDITOR ? ui('nav.schedulerProgram') : t(`Task.${task}.name`)
}
