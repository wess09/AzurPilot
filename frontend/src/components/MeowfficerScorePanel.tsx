/**
 * @fileoverview 指挥喵评分结果详情与洗点推荐面板组件。
 */

import { useEffect, useState } from 'react'
import { Cat, ChevronDown, FileText, PawPrint, RefreshCw, Sparkles, Trash2, TriangleAlert } from 'lucide-react'
import { ApiError, api } from '../api/client'
import type { MeowfficerAdvice, MeowfficerCat, MeowfficerRubric, MeowfficerScoreReport, MeowfficerTalent } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { Empty, ErrorBox, Loading, Modal } from './ui'

/** 档位文案由后端按攻略口径给出（中文），这里只按关键词上色，未知档位走中性样式。 */
const tierStyles: [string, string][] = [
  ['完美', 'is-perfect'],
  ['准毕业', 'is-near'],
  ['毕业', 'is-graduate'],
  ['过渡', 'is-transition'],
  ['零食', 'is-snack'],
  ['不适合', 'is-unsuitable'],
  ['雷暴', 'is-thunder'],
]

/** 按档位关键词取样式类名；关键词表见上方 tierStyles，未命中时走 is-other 中性样式。 */
export function tierClass(tier: string): string {
  return tierStyles.find(([keyword]) => tier.includes(keyword))?.[1] ?? 'is-other'
}

/** 命中标签形如「雷击长·潜艇 Lv3」，把等级拆出来单独做成小徽章。 */
export function splitHit(hit: string): {name: string; level: number} {
  const match = /^(.*?)\s*Lv\s*(\d+)$/.exec(hit.trim())
  return {name: match ? match[1] : hit.trim(), level: match ? Number(match[2]) : 0}
}

const levelBadges = ['Ⅰ', 'Ⅱ', 'Ⅲ']

function LevelBadge({level}: {level?: number}) {
  if (!level || level < 1 || level > levelBadges.length) return null
  return <span className="meow-level">{levelBadges[level - 1]}</span>
}

function TalentChip({talent}: {talent: MeowfficerTalent}) {
  const {ui} = useApp()
  const inferred = talent.inferred === true
  // 推断出来的天赋未必准确，用虚线边框加提示图标要求用户自行核对。
  const classes = ['meow-talent', talent.kind === 'special' ? 'is-special' : '', inferred ? 'is-inferred' : ''].filter(Boolean).join(' ')
  return <span className={classes} title={inferred ? ui('meow.inferred') : undefined}>
    {talent.kind === 'special' && <Sparkles size={12}/>}
    {talent.name}
    <LevelBadge level={talent.level}/>
    {inferred && <TriangleAlert size={12}/>}
  </span>
}

function HitChip({hit, special}: {hit: string; special: boolean}) {
  const {name, level} = splitHit(hit)
  return <span className={`meow-hit${special ? ' is-special' : ''}`}>{name}<LevelBadge level={level}/></span>
}

/** X 轴（彩天赋）与 Y 轴（有用普通）的命中标签行。 */
function AxisRow({label, hits, special}: {label: string; hits: string[]; special: boolean}) {
  const {ui} = useApp()
  return <div className="meow-axis">
    <span className="meow-axis-label">{label}</span>
    {hits.length ? hits.map(hit => <HitChip key={hit} hit={hit} special={special}/>) : <span className="meow-hit is-empty">{ui('meow.noHits')}</span>}
  </div>
}

/** 一条口径的正文：命中标签、说明与出处。 */
function RubricDetail({rubric}: {rubric: MeowfficerRubric}) {
  const {ui} = useApp()
  const notes = rubric.notes ?? []
  // 雷暴口径是加权点制，后端不给 x/y；此时不渲染公式，避免出现「x + y = 0 + 0.0」。
  const weighted = typeof rubric.x !== 'number' || typeof rubric.y !== 'number'
  return <>
    <div className="meow-rubric-head">
      <strong>{rubric.label}</strong>
      {!weighted && <span className="meow-formula">x + y = {Number(rubric.x).toFixed(0)} + {Number(rubric.y).toFixed(1)}</span>}
    </div>
    {typeof rubric.score === 'number' && <div className="meow-score-bar" role="img" aria-label={ui('meow.score')}>
      <i style={{width: `${Math.min(100, Math.max(0, rubric.score))}%`}}/>
    </div>}
    <AxisRow label={rubric.xLabel ?? ui('meow.axisX')} hits={rubric.xHits ?? []} special/>
    <AxisRow label={rubric.yLabel ?? ui('meow.axisY')} hits={rubric.yHits ?? []} special={false}/>
    {!!notes.length && <ul className="meow-notes">{notes.map(note => <li key={note}>{note}</li>)}</ul>}
    {rubric.source && <p className="meow-rubric-source">{ui('meow.source', {source: rubric.source})}</p>}
  </>
}

/** 自动刷新间隔（毫秒）：扫描结束后最多这么久，报告就会自己更新出来。 */
const AUTO_REFRESH_INTERVAL = 5000

/**
 * 洗点推荐。配色由后端的 verdict 决定，文案（含成本）全部由后端给出：
 * 「要不要洗点」依赖档位与是否已投入点数，这些判断留在后端，前端只负责展示。
 */
function AdviceBlock({advice}: {advice: MeowfficerAdvice}) {
  const targets = advice.targets ?? []
  return <div className={`meow-advice is-${advice.verdict}`}>
    <div className="meow-advice-head"><Sparkles size={14}/><strong>{advice.headline}</strong></div>
    <p className="meow-advice-reason">{advice.reason}</p>
    {advice.costText && <p className="meow-advice-cost">{advice.costText}</p>}
    {!!targets.length && <ul className="meow-advice-targets">
      {targets.map(target => <li key={target}>{target}</li>)}
    </ul>}
  </div>
}

function CatCard({cat}: {cat: MeowfficerCat}) {
  const {ui} = useApp()
  const talents = cat.talents ?? []
  const rubrics = cat.rubrics ?? []
  // 后端已把主口径排在最前，这里仍显式优先取 primary，其余口径折叠展示。
  const primary = rubrics.find(rubric => rubric.primary) ?? rubrics[0]
  const others = rubrics.filter(rubric => rubric !== primary)
  const inferred = talents.some(talent => talent.inferred)
  return <section className="meow-card">
    <div className="panel-heading">
      <div>
        <h2>{cat.cat}</h2>
        {(cat.tags ?? []).map(tag => <span className="meow-tag" key={tag}>{tag}</span>)}
        {typeof cat.level === 'number' && <span className="meow-flag is-level">Lv{cat.level}</span>}
        {cat.maxed && <span className="meow-flag is-maxed">{ui('meow.maxed')}</span>}
        {cat.fixed && <span className="meow-flag is-fixed">{ui('meow.fixed')}</span>}
      </div>
      <div className="meow-card-score">
        {primary?.tier && <span className={`meow-tier ${tierClass(primary.tier)}`}>{primary.tier}</span>}
        {typeof primary?.score === 'number' && <span className="meow-score">{primary.score}<small>{ui('meow.score')}</small></span>}
      </div>
    </div>
    {cat.note && <p className="meow-cat-note">{cat.note}</p>}
    {!!talents.length && <div className="meow-talents">
      {talents.map(talent => <TalentChip key={`${talent.name}-${talent.level ?? 0}`} talent={talent}/>)}
      {inferred && <span className="meow-inferred-hint"><TriangleAlert size={12}/>{ui('meow.inferred')}</span>}
    </div>}
    {primary && <div className="meow-primary"><RubricDetail rubric={primary}/></div>}
    {cat.advice && <AdviceBlock advice={cat.advice}/>}
    {!!others.length && <details className="meow-others">
      <summary><ChevronDown size={14}/>{ui('meow.otherRubrics', {count: others.length})}</summary>
      <div className="meow-others-body">{others.map(rubric => <div className="meow-rubric-minor" key={rubric.key ?? rubric.label}>
        <div className="meow-rubric-head">
          <strong>{rubric.label}</strong>
          {rubric.tier && <span className={`meow-tier ${tierClass(rubric.tier)}`}>{rubric.tier}</span>}
          {typeof rubric.score === 'number' && <span className="meow-score">{rubric.score}<small>{ui('meow.score')}</small></span>}
        </div>
        <AxisRow label={rubric.xLabel ?? ui('meow.axisX')} hits={rubric.xHits ?? []} special/>
        <AxisRow label={rubric.yLabel ?? ui('meow.axisY')} hits={rubric.yHits ?? []} special={false}/>
      </div>)}</div>
    </details>}
    {(cat.source || typeof cat.pointsSpent === 'number') && <div className="meow-card-foot">
      {cat.source && <span className="meow-shot">{ui('meow.screenshot', {name: cat.source})}</span>}
      {typeof cat.pointsSpent === 'number' && <span>{ui('meow.pointsSpent', {count: cat.pointsSpent})}</span>}
    </div>}
  </section>
}

/** 报告列表本体，与取数逻辑分开，便于单独渲染检查。 */
export function MeowfficerScoreList({report}: {report: MeowfficerScoreReport}) {
  return <div className="meow-cats">{report.cats.map((cat, index) => <CatCard key={`${index}-${cat.cat}`} cat={cat}/>)}</div>
}

/**
 * 「工具 → 指挥喵评分」的结果面板。
 *
 * 报告按机器共享一份，未跑过任务时后端返回 NOT_FOUND，这里显示空状态而不是错误。
 */
export function MeowfficerScorePanel({instance}: {instance: string}) {
  const {ui} = useApp()
  const connection = useConnection()
  const [report, setReport] = useState<MeowfficerScoreReport>()
  const [missing, setMissing] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  const [clearing, setClearing] = useState(false)

  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    setReport(undefined); setMissing(false); setError('')
    void api.request('meowfficer.scoreReport', {instance}).then(value => {
      if (active) setReport(value)
    }).catch(error => {
      if (!active) return
      // 报告不存在属于正常情况（还没跑过任务），单独走空状态。
      if (error instanceof ApiError && error.code === 'NOT_FOUND') setMissing(true)
      else setError(error.message)
    }).finally(() => {if (active) setRefreshing(false)})
    return () => {active = false}
  }, [connection, instance, revision])

  function refresh() {
    setRefreshing(true)
    setRevision(value => value + 1)
  }

  // 报告在任务结束时一次性写入，轮询能接住扫描完成；后端读本地 JSON，成本很低。
  // 只在页面可见时轮询，且仅数据变化才更新 state——避免每次轮询重渲染、冲掉展开状态。
  useEffect(() => {
    if (connection !== 'ready') return
    const timer = setInterval(() => {
      if (document.visibilityState !== 'visible') return
      void api.request('meowfficer.scoreReport', {instance}).then(value => {
        setMissing(false)
        setReport(previous => (
          previous && previous.generatedAt === value.generatedAt && previous.cats.length === value.cats.length
            ? previous
            : value))
      }).catch(() => {
        // 轮询失败不打扰用户：手动「刷新」仍会给出明确报错。
      })
    }, AUTO_REFRESH_INTERVAL)
    return () => clearInterval(timer)
  }, [connection, instance])

  /** 清空报告：三份产物都由后端删掉，成功后本地直接切回空状态，不必再请求一次。 */
  async function clearReport() {
    setClearing(true)
    try {
      await api.request('meowfficer.clearReport', {instance})
      setConfirmClear(false)
      setReport(undefined); setMissing(true); setError('')
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error))
    } finally {
      setClearing(false)
    }
  }

  const empty = <Empty icon={<Cat size={32}/>} title={ui('meow.emptyTitle')}>{ui('meow.emptyHint')}</Empty>
  return <>
    <section className="panel meow-panel" aria-label={ui('meow.title')}>
    <div className="panel-heading">
      <div><PawPrint size={18}/><h2>{ui('meow.title')}</h2></div>
      <div className="meow-panel-actions">
        {report && <span className="meow-summary">{ui('meow.summary', {count: report.cats.length, time: report.generatedAt || '—'})}</span>}
        {/* HTML 报告与面板读的是同一份产物，有数据即存在。 */}
        {!!report?.cats.length && <a className="button secondary" href="/reports/meowfficer_score" target="_blank" rel="noopener noreferrer">
          <FileText size={15}/>{ui('meow.openReport')}
        </a>}
        {!!report?.cats.length && <button className="button secondary" disabled={connection !== 'ready'} onClick={() => setConfirmClear(true)}>
          <Trash2 size={15}/>{ui('meow.clear')}
        </button>}
        <button className="button secondary" disabled={connection !== 'ready' || refreshing} onClick={refresh}>
          <RefreshCw size={15}/>{refreshing ? ui('meow.refreshing') : ui('meow.refresh')}
        </button>
      </div>
    </div>
    {error ? <div className="meow-body"><ErrorBox message={error} retry={refresh}/></div>
      : missing ? <div className="meow-body">{empty}</div>
      : !report ? <Loading/>
      : !report.cats.length ? <div className="meow-body">{empty}</div>
      : <MeowfficerScoreList report={report}/>}
    <p className="panel-note">{ui('meow.disclaimer')}</p>
    </section>
    {confirmClear && <Modal title={ui('meow.clearTitle')} onClose={() => setConfirmClear(false)}>
      <p>{ui('meow.clearWarning')}</p>
      <button className="button danger" disabled={clearing} onClick={clearReport}>
        <Trash2 size={15}/>{clearing ? ui('meow.clearing') : ui('meow.clearConfirm')}
      </button>
    </Modal>}
  </>
}
