/** 仅提供 WebUI 页面的导航项，不注册成可执行的游戏任务。 */
export const SCHEDULER_EDITOR = 'SchedulerProgram'
export const MIND_CALCULATOR = 'MindCalculator'
export function taskNavItems(key: string | null, tasks: string[]) {
  if (key === 'FleetManagement') return [...tasks, MIND_CALCULATOR]
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
export function taskLabel(task: string, ui: (key: 'nav.schedulerProgram' | 'mind.title') => string, t: (key: string) => string) {
  return task === SCHEDULER_EDITOR ? ui('nav.schedulerProgram') : task === MIND_CALCULATOR ? ui('mind.title') : t(`Task.${task}.name`)
}
