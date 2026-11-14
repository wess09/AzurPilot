/**
 * 从 SchedulerProgram.tsx 原 21-24 行提取，纯搬迁未改动（仅新增导出）。
 * 调度编辑器共用中文标签：端口与变量类型、执行出口与参数名。
 */
export const typeLabels: Record<string, string> = {any:'任意值', number:'数值', boolean:'布尔', string:'文本', time:'时间', duration:'时长（秒）', resource:'资源记录', task:'任务', tasks:'任务列表', result:'任务结果', list:'列表', object:'对象'}
export const exits: Record<string, string> = {next:'下一步', yes:'是', no:'否', unavailable:'数据不可用', completed:'完成', yielded:'主动让出', recoverable:'可恢复错误', failed:'失败', empty:'没有任务', success:'成功', body:'循环体', done:'结束'}
export const labels: Record<string, string> = {name:'名称', value:'值', operator:'运算符', a:'输入 A', b:'输入 B', condition:'条件', yes:'满足时的值', no:'不满足时的值', seconds:'时长（秒）', time:'目标时间', start:'开始时刻', end:'结束时刻', weekdays:'星期（1～7）', field:'字段', maxAge:'有效期（秒）', autoRefresh:'过期时自动刷新', task:'任务', rule:'筛选规则', descending:'降序', count:'循环次数（-1 为持续）', loop:'所属循环', graph:'组合卡片', guard:'继续条件', key:'记录标识', kind:'记录类型', reset:'刷新时刻', limit:'每日上限', valueType:'数据类型'}
Object.assign(labels, {order:'当前优先级顺序', dueBefore:'到期截止时间', deadline:'最近计划时间', idleMode:'空闲策略', before:'到期截止时间', strict:'截止之前才视为到期'})
