import { matchPath, useLocation, useNavigate, useParams } from 'react-router-dom'
import { Activity, AlertTriangle, LoaderCircle, Pause, Play, Plus, Square, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api/client'
import { useApp, useConnection } from '../app/context'
import { editor } from '../config/editors'
import type { Status } from '../api/types'
import type { UiKey } from '../i18n'
import { ErrorBox, Modal } from './ui'

/** 图标随状态换：跑着的两种叠动画，出错的与停下的静态。 */
const STATUS_ICON: Record<Status, typeof Activity> = {
    running: Activity,
    updating: LoaderCircle,
    error: AlertTriangle,
    stopped: Pause,
}

/** 悬停提示用的状态文案。 */
const STATUS_LABEL: Record<Status, UiKey> = {
    running: 'status.running',
    updating: 'status.updating',
    error: 'status.error',
    stopped: 'status.stopped',
}

/** 实例分页条：所有实例平铺在顶栏一行，一点即切，不用展开下拉。 */
export function InstanceTabs({onCreate}: {onCreate: () => void}) {
    const {instances, ui} = useApp()
    const {instance} = useParams()
    const navigate = useNavigate()
    const {pathname} = useLocation()
    /* 标签跳到目标实例的同一页型；不在实例页内（如主页）时统一落到总览。 */
    const suffix = matchPath('/i/:instance/*', pathname)?.params['*'] || 'overview'
    const [pendingDelete, setPendingDelete] = useState<string>()
    const jump = (name: string) => { if (name !== instance) navigate(`/i/${name}/${suffix}`) }

    return <div className="instance-tabs" role="tablist" aria-label={ui('nav.instanceTabs')}>
        {instances.map(item => {
            const StatusIcon = STATUS_ICON[item.status]
            const current = item.name === instance
            const hint = [item.name, ui(STATUS_LABEL[item.status]), item.currentTask].filter(Boolean).join(' · ')
            return <button
                key={item.name}
                type="button"
                role="tab"
                aria-selected={current}
                className={`instance-tab ${item.status}${current ? ' current' : ''}`}
                title={hint}
                onClick={() => jump(item.name)}
            >
                <span className="instance-tab-cell">
                    <StatusIcon className="instance-tab-icon" size={14} aria-hidden="true"/>
                    <SchedulerToggle name={item.name} status={item.status}/>
                </span>
                <span className="instance-tab-name">{item.name}</span>
                <span className="instance-tab-cell instance-tab-remove" role="button" tabIndex={-1} aria-label={`${ui('instance.delete')} · ${ui('instance.rightClick')}`} title={`${ui('instance.delete')} · ${ui('instance.rightClick')}`} onContextMenu={event => { event.preventDefault(); setPendingDelete(item.name) }}><X size={13} aria-hidden="true"/></span>
            </button>
        })}
        <button type="button" className="instance-tab-create" aria-label={ui('instance.create')} title={ui('instance.create')} onClick={onCreate}><Plus size={15}/></button>
        {pendingDelete && <DeleteInstance name={pendingDelete} onClose={() => setPendingDelete(undefined)}/>}
    </div>
}

/** 标签页左侧状态格：平时显示运行状态，悬停换成该实例的启停按钮。 */
function SchedulerToggle({name, status}: {name: string; status: Status}) {
    const connection = useConnection()
    const {notify, ui} = useApp()
    const [busy, setBusy] = useState(false)
    const running = status === 'running'
    /* 更新中的实例不接受就地启停。 */
    const usable = connection === 'ready' && !busy && status !== 'updating'

    async function toggle(event: React.MouseEvent) {
        event.preventDefault()
        if (!usable) return
        setBusy(true)
        try {
            /* 与调度器卡片同一道落盘屏障。 */
            if (!running) await editor(`config:${name}`).settled()
            await api.request(running ? 'scheduler.stop' : 'scheduler.start', {instance: name})
            notify(running ? ui('scheduler.stoppedNotice') : ui('scheduler.started'))
        } catch (error) {
            notify((error as Error).message, true)
        } finally {
            setBusy(false)
        }
    }

    return <span
        className="instance-tab-power"
        role="button"
        tabIndex={-1}
        aria-label={`${running ? ui('scheduler.stop') : ui('scheduler.start')} · ${ui('instance.rightClick')}`}
        title={`${running ? ui('scheduler.stop') : ui('scheduler.start')} · ${ui('instance.rightClick')}`}
        onContextMenu={toggle}
    >{running ? <Square size={13} aria-hidden="true"/> : <Play size={13} aria-hidden="true"/>}</span>
}

/** 删除实例的三次确认：连点三次才真删，每次换一档提示文案与抖动幅度，末档转强调红。 */
const PROMPT_KEYS = ['instance.deletePrompt', 'instance.deletePrompt2', 'instance.deletePrompt3'] as const
function DeleteInstance({name, onClose}: {name: string; onClose: () => void}) {
    const [step, setStep] = useState(0)
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState('')
    const connection = useConnection()
    const {instances, refresh, notify, ui} = useApp()
    const navigate = useNavigate()
    /* 当前打开的是哪个实例 —— 决定删完落在哪一页。 */
    const {instance: routeInstance} = useParams()
    const current = routeInstance ?? ''

    async function remove() {
        setBusy(true); setError('')
        try {
            const config = await api.request('config.get', {instance: name})
            await api.request('instances.delete', {instance: name, revision: config.revision})
            /* 删完就地换到邻近实例的运行总览：删自己则接前一个（没有前一个就接后一个），
               删别人则留在当前标签页。 */
            const order = instances.map(item => item.name)
            const at = order.indexOf(name)
            const currentAt = order.indexOf(current)
            const landing = at === currentAt ? (order[at - 1] ?? order[at + 1]) : current
            /* 跳转要在 refresh 之前发出：刷新后 URL 里的实例已不在列表，外壳的兜底守卫会抢先把页面推回主页。 */
            if (landing) navigate(`/i/${landing}/overview`)
            await refresh(); onClose(); notify(ui('instance.backupNotice'))
            if (landing) navigate(`/i/${landing}/overview`)
        } catch (error) { setError((error as Error).message) } finally { setBusy(false) }
    }

    /* 三次点击对应三档：警戒 → 危险 → 执行；前两下只推进档位。 */
    const phase = ['armed', 'danger', 'execute'][step]
    return <Modal title={ui('instance.delete')} onClose={onClose}><div className="form-stack">
        <p>{ui(PROMPT_KEYS[step] ?? PROMPT_KEYS[0], {name})}</p>
        {error && <ErrorBox message={error}/>}
        <button
            className={`button tab-delete-confirm ${phase}`}
            disabled={busy || connection !== 'ready'}
            onClick={() => step < 2 ? setStep(step + 1) : void remove()}
        ><Trash2 size={15}/>{busy ? ui('instance.deleting') : ui('instance.deleteConfirm')}</button>
    </div></Modal>
}
