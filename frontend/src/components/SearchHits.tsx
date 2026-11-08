/**
 * @fileoverview 侧栏的「配置项命中」分组。
 *
 * 侧栏任务搜索使用这份实现：
 * 任务名由各自本地过滤，页面里的文字统一走这个分组查后端索引。
 */

import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { useApp } from '../app/context'
import { setSearchTarget } from '../app/searchTarget'
import { ownerTaskOf, ownerTaskOfGroup } from './taskNavItems'
import type { SearchContentHit } from '../api/types'

/** 命中项分两类：卡片（三级标题）与配置项；卡片命中没有配置项键。 */
type Hit = SearchContentHit & {card?: boolean}

export function SearchHits({search, onNavigate}: {search: string; onNavigate?: () => void}) {
  const {schema, ui} = useApp()
  const {instance} = useParams()
  const navigate = useNavigate()
  const base = instance ? `/i/${instance}` : ''
  const [hits, setHits] = useState<Hit[]>([])
  const keyword = search.trim()

  useEffect(() => {
    if (!keyword) {
      setHits([])
      return
    }
    const timer = window.setTimeout(() => {
      void api.request('search.content', {query: keyword})
        .then(result => setHits([
          ...(result?.groups ?? []).map(hit => ({...hit, card: true})),
          ...(result?.options ?? []),
        ]))
        .catch(() => setHits([]))
    }, 200)
    return () => window.clearTimeout(timer)
  }, [keyword])

  if (!keyword) return null

  /** 打开一条命中项：跳到它所属的任务页，并请配置页滚动定位到该项；卡片命中定位到整张卡片。 */
  function openHit(hit: Hit) {
    const args = schema?.args ?? {}
    const task = hit.card ? ownerTaskOfGroup(args, hit.task) : ownerTaskOf(args, hit.task, hit.key)
    if (!task) return
    setSearchTarget(hit.card ? `${task}.${hit.task}` : `${task}.${hit.task}.${hit.key}`)
    navigate(`${base}/task/${task}`)
    onNavigate?.()
  }

  return (
    <div className="nav-search-hits">
      <div className="sidebar-label">{ui('nav.searchConfigGroup')}</div>
      {hits.length ? hits.map(hit => (
        <button
          key={`${hit.card ? 'group' : 'option'}.${hit.task}.${hit.key}`}
          type="button"
          className="nav-search-hit"
          onClick={() => openHit(hit)}
        >
          <span className="nav-search-hit-label">{hit.label || hit.key}</span>
          <span className="nav-search-hit-path">{hit.card ? hit.task : `${hit.task}.${hit.key}`}</span>
          {hit.help && <span className="nav-search-hit-help">{hit.help}</span>}
        </button>
      )) : <div className="nav-search-empty">{ui('nav.searchConfigEmpty')}</div>}
    </div>
  )
}
