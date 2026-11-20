/**
 * @fileoverview 实例股票注册与绑定引导。交易账户、登录和交易仅在独立交易所提供。
 */
import {useCallback,useEffect,useRef,useState,type FormEvent} from 'react'
import {useParams,Link} from 'react-router-dom'
import {ArrowLeft,CheckCircle2,Copy,ExternalLink,ShieldCheck} from 'lucide-react'
import {api} from '../api/client'
import type {StockExchangeStatus,StockExchangeRebuild} from '../api/types'
import {useApp,useConnection} from '../app/context'
import {usePageRead} from '../app/usePageRead'
import {stockText} from '../i18n.stock'
import {ErrorBox,Modal,Panel,PanelHeading,PageTitle} from '../components/ui'
import {LoadBoundary} from '../components/ui/load-boundary'
import {Checkbox} from '../components/FormControls'
import {Input} from '../components/ui/input'
import {Button} from '../components/ui/button'
import './stock-exchange.css'

const EXCHANGE='https://stock.azurpilot.com'
const stockPollInterval = () => 15000

/** 注册实例股票、经 QQ 群机器人把股票绑定到交易账户，绑定成功后自动打开独立交易所。 */
export function StockExchange(){
  const {instance=''}=useParams(),connection=useConnection(),{language,ui}=useApp(),t=stockText[language]
  const [error,setError]=useState(''),[recoveryAvailable,setRecoveryAvailable]=useState(false),[rebuildError,setRebuildError]=useState('')
  const [username,setUsername]=useState(''),[busy,setBusy]=useState(false),[copied,setCopied]=useState(false),[rebuild,setRebuild]=useState<StockExchangeRebuild>(),[confirmRebuild,setConfirmRebuild]=useState(false),[consent,setConsent]=useState(false)
  // current 镜像当前实例，异步回调据此丢弃切换实例后的过期响应。
  const current=useRef(instance),opened=useRef(''),recoveryActive=useRef(false),writeActive=useRef(false),planButton=useRef<HTMLButtonElement>(null);current.current=instance
  const loadStatus=useCallback(()=>api.request('stock.status',{instance}),[instance])
  const canPoll = useCallback(() => document.visibilityState === 'visible' && !writeActive.current && !recoveryActive.current, [])
  const read=usePageRead<StockExchangeStatus>(`stock:${instance}`,connection==='ready',loadStatus,stockPollInterval,{when: canPoll})
  const {data:status,reload:refresh,reloadAndWait,setData:setStatus,invalidate}=read
  useEffect(()=>{
    recoveryActive.current=false;writeActive.current=false;setRecoveryAvailable(false);setRebuildError('');setUsername('');setError('');setCopied(false);setConsent(false);setBusy(false);setRebuild(undefined);setConfirmRebuild(false)
  },[instance])
  useEffect(()=>{if(read.error)setRecoveryAvailable(true)},[read.error])
  useEffect(()=>{if(status&&!recoveryActive.current){setRecoveryAvailable(false);setError('')}},[status])
  useEffect(()=>{
    const autoRefresh=()=>{if(!writeActive.current&&!recoveryActive.current)refresh()}
    return api.onEvent(event=>{if(event.topic==='stock'&&(event.data as {instance?:string}).instance===instance)autoRefresh()})
  },[instance,refresh])
  // 绑定成功即自动打开交易所；opened 守卫同实例只开一次，轮询与事件触发的重渲染不会重复弹窗。
  useEffect(()=>{
    if(status?.registered&&status.bound&&opened.current!==instance){
      opened.current=instance
      window.open(EXCHANGE,'_blank','noopener,noreferrer')
    }
  },[status,instance])
  async function register(event:FormEvent){
    event.preventDefault();if(writeActive.current)return;writeActive.current=true;invalidate();setBusy(true);setError('')
    // noticeVersion 须与后端约定的公告版本逐字一致，否则注册被拒（STOCK_NOTICE_REQUIRED）；公告改版时两端同步更新。
    try{const next=await api.request('stock.register',{instance,username:username.trim(),noticeVersion:'stock-public-v2-20261101'});if(current.current===instance)setStatus(next)}
    catch(error){if(current.current===instance)setError((error as Error).message)}
    finally{if(current.current===instance){writeActive.current=false;setBusy(false)}}
  }
  async function copyCode(){
    try{await navigator.clipboard.writeText(`绑定股票 ${status?.bindingCode??''}`);if(current.current===instance)setCopied(true)}
    catch{if(current.current===instance)setError(t.copyError)}
  }
  function closeRecovery(){
    if(busy)return
    recoveryActive.current=false;setRebuild(undefined);setConfirmRebuild(false);setRebuildError('')
    requestAnimationFrame(()=>planButton.current?.focus())
  }
  async function recovery(confirm=false){
    if(writeActive.current)return
    recoveryActive.current=true;writeActive.current=true;invalidate();setRecoveryAvailable(true);setBusy(true);setRebuildError('')
    try{const plan=await api.request('stock.rebuild',{instance,confirm,scope:rebuild?.scope??'instance'});if(current.current!==instance)return;if(plan.rebuilt){recoveryActive.current=false;setRebuild(undefined);setConfirmRebuild(false);opened.current='';try{await reloadAndWait()}catch{/* Read errors are displayed by the boundary. */}}else{setRebuild(plan);setConfirmRebuild(false)}}
    catch(error){if(current.current===instance){if(confirm)setRebuildError((error as Error).message);else{recoveryActive.current=false;setError((error as Error).message)}}}finally{if(current.current===instance){writeActive.current=false;setBusy(false)}}
  }
  return <section className="stock-instance-page">
    <PageTitle title={ui('stock.name')} actions={<Button variant="outline" asChild><Link to={`/i/${encodeURIComponent(instance)}/overview`}><ArrowLeft/>{t.back}</Link></Button>}/>
    <p className="stock-instance-intro">{t.intro}</p>
    {(error||read.error||recoveryAvailable)&&<Panel className="stock-instance-card"><h3>{t.recoveryHelp}</h3><p>{t.recoveryDesc}</p><Button ref={planButton} variant="outline" aria-disabled={busy} onClick={()=>void recovery()}>{t.plan}</Button></Panel>}
    {rebuild&&<Modal title={t.rebuild} onClose={closeRecovery}>
      <div className="stock-rebuild-content"><p>{t.scope}: {rebuild.scope==='all'?t.all:t.current}</p><p>{t.affected}: {rebuild.affectedInstances.join('、')}</p><p>{t.rebuildDesc}</p>{rebuildError&&<ErrorBox message={rebuildError}/>}<Checkbox checked={confirmRebuild} onChange={e=>setConfirmRebuild(e.target.checked)}>{t.understand}</Checkbox><div className="stock-rebuild-actions"><Button variant="outline" disabled={busy} onClick={closeRecovery}>{t.cancel}</Button><Button variant="destructive" disabled={busy||!confirmRebuild} onClick={()=>void recovery(true)}>{t.confirm}</Button></div></div>
    </Modal>}
    <LoadBoundary ready={!!status} error={error||read.error} retry={()=>{if(!writeActive.current&&!recoveryActive.current)refresh()}}>
      {status&&<div className="stock-instance-grid">
      <Panel className="stock-instance-card">
        <PanelHeading title={status.registered?t.registered:t.registerTitle} actions={status.registered&&<CheckCircle2 size={20}/>}/>
        <p className="muted">{t.instance}: {instance}</p>
        {status.deleted?<div role="status"><h3>{t.deleted}</h3><p>{t.deletedDesc}</p></div>:!status.registered?<form onSubmit={event=>void register(event)}>
          <label htmlFor="stock-username">{t.username}</label><Input id="stock-username" autoComplete="nickname" minLength={2} maxLength={32} required value={username} onChange={event=>setUsername(event.target.value)} placeholder={t.placeholder} disabled={busy}/>
          <p className="muted">{t.registerHelp}</p>
          <Checkbox checked={consent} onChange={e=>setConsent(e.target.checked)}>{t.consent}</Checkbox><Button disabled={busy||!consent||[...username.trim()].length<2}>{busy?t.registering:t.register}</Button>
        </form>:<>
          <dl className="stock-instance-facts"><div><dt>{t.name}</dt><dd>{status.stock?.name??t.waiting}</dd></div><div><dt>{t.symbol}</dt><dd>{status.stock?.symbol??'—'}</dd></div><div><dt>{t.account}</dt><dd>{status.bound?t.bound:t.unbound}</dd></div><div><dt>{t.sync}</dt><dd>{status.message}</dd></div></dl>
          {status.bound?<div className="stock-instance-success"><ShieldCheck size={21}/><p>{t.success}</p></div>:<>
            <p>{t.bindHelp}</p>
            <div className="stock-binding-code"><code>绑定股票 {status.bindingCode||t.waitingCode}</code><Button variant="ghost" size="icon" type="button" disabled={!status.bindingCode} aria-label={t.copy} onClick={()=>void copyCode()}><Copy size={17}/></Button></div>
            {copied&&<p role="status">{t.copied}</p>}
            <p className="muted">{t.public}</p>
          </>}
          <Button asChild><a href={EXCHANGE} target="_blank" rel="noreferrer">{status.bound?t.enter:t.browse}<ExternalLink/></a></Button>
        </>}
      </Panel>
      <aside className="panel stock-instance-card stock-instance-guide"><h2>{t.guide}</h2><ol><li><strong>{t.step1}</strong><p>{t.step1Desc}</p></li><li><strong>{t.step2}</strong><p>{t.step2Before}<a href="https://qm.qq.com/q/93NWF3S362" target="_blank" rel="noreferrer">1126124220</a>{t.step2After}</p></li><li><strong>{t.step3}</strong><p>{t.step3Before}<a href={EXCHANGE} target="_blank" rel="noreferrer">stock.azurpilot.com</a>{t.step3After}</p></li></ol><p className="muted">{t.disclaimer}</p></aside>
    </div>}
    </LoadBoundary>
  </section>
}
