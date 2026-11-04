/** 实例股票注册与绑定引导。交易账户、登录和交易仅在独立交易所提供。 */
import {useCallback,useEffect,useRef,useState,type FormEvent} from 'react'
import {useParams,Link} from 'react-router-dom'
import {ArrowLeft,CheckCircle2,Copy,ExternalLink,ShieldCheck,TrendingUp} from 'lucide-react'
import {api} from '../api/client'
import type {StockExchangeStatus,StockExchangeRebuild} from '../api/types'
import {useConnection} from '../app/context'
import {ErrorBox,Loading,PageTitle} from '../components/ui'
import './stock-exchange.css'

const EXCHANGE='https://stock.azurpilot.com'

export function StockExchange(){
  const {instance=''}=useParams(),connection=useConnection()
  const [status,setStatus]=useState<StockExchangeStatus>(),[error,setError]=useState('')
  const [username,setUsername]=useState(''),[busy,setBusy]=useState(false),[copied,setCopied]=useState(false),[rebuild,setRebuild]=useState<StockExchangeRebuild>(),[confirmRebuild,setConfirmRebuild]=useState(false),[consent,setConsent]=useState(false)
  const current=useRef(instance),opened=useRef('');current.current=instance
  const refresh=useCallback(async()=>{
    if(connection!=='ready')return
    try{const next=await api.request('stock.status',{instance});if(current.current===instance){setStatus(next);setError('')}}
    catch(error){if(current.current===instance)setError((error as Error).message)}
  },[instance,connection])
  useEffect(()=>{
    setStatus(undefined);setUsername('');setError('');setCopied(false);setConsent(false);setBusy(false);setRebuild(undefined);setConfirmRebuild(false)
    void refresh()
    const timer=window.setInterval(()=>{if(document.visibilityState==='visible')void refresh()},15000)
    const unsubscribe=api.onEvent(event=>{if(event.topic==='stock'&&(event.data as {instance?:string}).instance===instance)void refresh()})
    return ()=>{window.clearInterval(timer);unsubscribe()}
  },[instance,refresh])
  useEffect(()=>{
    if(status?.registered&&status.bound&&opened.current!==instance){
      opened.current=instance
      window.open(EXCHANGE,'_blank','noopener,noreferrer')
    }
  },[status,instance])
  async function register(event:FormEvent){
    event.preventDefault();setBusy(true);setError('')
    try{const next=await api.request('stock.register',{instance,username:username.trim(),noticeVersion:'stock-public-v2-20261101'});if(current.current===instance)setStatus(next)}
    catch(error){if(current.current===instance)setError((error as Error).message)}
    finally{if(current.current===instance)setBusy(false)}
  }
  async function copyCode(){
    try{await navigator.clipboard.writeText(`绑定股票 ${status?.bindingCode??''}`);setCopied(true)}
    catch{setError('浏览器未允许复制，请手动复制绑定码。')}
  }
  async function recovery(confirm=false){
    setBusy(true);setError('')
    try{const plan=await api.request('stock.rebuild',{instance,confirm,scope:rebuild?.scope??'instance'});if(current.current!==instance)return;if(plan.rebuilt){setRebuild(undefined);setConfirmRebuild(false);opened.current='';await refresh()}else{setRebuild(plan);setConfirmRebuild(false)}}
    catch(error){if(current.current===instance)setError((error as Error).message)}finally{if(current.current===instance)setBusy(false)}
  }
  return <section className="stock-instance-page">
    <PageTitle title="茗喵证券交易所" actions={<Link className="button" to={`/i/${encodeURIComponent(instance)}/overview`}><ArrowLeft size={16}/>返回总览</Link>}/>
    <section className="panel stock-instance-hero">
      <div className="stock-instance-mark"><TrendingUp size={30}/></div>
      <div><span className="stock-instance-eyebrow">AZURPILOT · 茗交所</span><h2>让行动力成为你的股票</h2><p>当前实例独立发行股票，行情使用已有的总行动力记录。交易与账户管理在独立交易所完成，脚本任务继续照常运行。</p></div>
    </section>
    {error&&<><ErrorBox message={error} retry={()=>void refresh()}/><section className="panel stock-instance-card"><h3>玩家数据需要处理？</h3><p>网络故障请重试。若身份、历史或来源不一致，可先查看本地重建计划。重建会备份本地旧资料、创建新身份；远端账户与原股票不会被删除，脚本任务保持原状。</p><button className="button" disabled={busy} onClick={()=>void recovery()}>查看本地数据重建计划</button></section></>}
    {rebuild&&<section className="panel stock-instance-card" role="dialog" aria-label="确认本地股票数据重建"><h3>完全重建本地股票数据</h3><p>范围：{rebuild.scope==='all'?'所有本地实例':'当前实例'}</p><p>受影响实例：{rebuild.affectedInstances.join('、')}</p><p>先备份后重建身份与股票历史登记，不删除远端账户、远端股票或脚本配置。新身份不会继承原绑定，无法用重建恢复管理员已删除的原股票。</p><label><input type="checkbox" checked={confirmRebuild} onChange={e=>setConfirmRebuild(e.target.checked)}/>我已理解本地身份与绑定将重建</label><button className="button" disabled={busy||!confirmRebuild} onClick={()=>void recovery(true)}>确认完全重建</button><button className="button" disabled={busy} onClick={()=>setRebuild(undefined)}>取消</button></section>}
    {!status&&!error?<Loading/>:status&&<div className="stock-instance-grid">
      <section className="panel stock-instance-card">
        <div className="panel-heading"><h2>{status.registered?'当前实例股票':'注册当前实例股票'}</h2>{status.registered&&<CheckCircle2 size={20}/>}</div>
        <p className="muted">实例：{instance}</p>
        {status.deleted?<div role="status"><h3>股票已删除，上报已停止</h3><p>原实例不能重新登记。绑定的交易账户已解除绑定，须绑定其他实例股票后才可继续使用。</p></div>:!status.registered?<form onSubmit={event=>void register(event)}>
          <label htmlFor="stock-username">股票用户名</label><input id="stock-username" autoComplete="nickname" minLength={2} maxLength={32} required value={username} onChange={event=>setUsername(event.target.value)} placeholder="输入你希望显示的股票名称" disabled={busy}/>
          <p className="muted">只需设置用户名，无需交易账户或密码。首次注册后会开始补足已有历史，之后自动增量同步。</p>
          <label><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>我已了解股票名称、行动力报价历史与交易数据公开，注册后后台持续自动同步。</label><button className="button primary" disabled={busy||!consent||[...username.trim()].length<2}>{busy?'正在注册…':'注册股票账户'}</button>
        </form>:<>
          <dl className="stock-instance-facts"><div><dt>股票名称</dt><dd>{status.stock?.name??'等待交易所返回'}</dd></div><div><dt>股票编号</dt><dd>{status.stock?.symbol??'—'}</dd></div><div><dt>交易账户</dt><dd>{status.bound?'已绑定':'尚未绑定'}</dd></div><div><dt>行动力同步</dt><dd>{status.message}</dd></div></dl>
          {status.bound?<div className="stock-instance-success"><ShieldCheck size={21}/><p>股票已绑定交易账户，已尝试在新标签页打开交易所。浏览器拦截时可点击下方按钮。</p></div>:<>
            <p>请在 QQ 群里 @官方机器人并发送下方命令，将股票绑定到你的交易账户。</p>
            <div className="stock-binding-code"><code>绑定股票 {status.bindingCode||'等待绑定码'}</code><button className="icon-button" type="button" disabled={!status.bindingCode} aria-label="复制绑定命令" onClick={()=>void copyCode()}><Copy size={17}/></button></div>
            {copied&&<p role="status">已复制绑定命令。</p>}
            <p className="muted">群内绑定命令和机器人回复均公开可见。绑定后自动打开交易所；本页每 15 秒检查一次绑定状态。</p>
          </>}
          <a className="button primary" href={EXCHANGE} target="_blank" rel="noreferrer">{status.bound?'进入交易所':'浏览交易所'}<ExternalLink size={16}/></a>
        </>}
      </section>
      <aside className="panel stock-instance-card stock-instance-guide"><h2>注册与绑定</h2><ol><li><strong>注册实例股票</strong><p>在本页输入用户名，为当前实例发行一只股票。它与 QQ 交易账户分开管理。</p></li><li><strong>注册 QQ 交易账户</strong><p>加 QQ 群 <a href="https://qm.qq.com/q/93NWF3S362" target="_blank" rel="noreferrer">1126124220</a> 进行注册。在群里 @官方机器人并发送“注册 &lt;用户名&gt;”，直接获得随机初始密码；首次网页登录必须改密。单独 @机器人可查看指令菜单。</p></li><li><strong>绑定并开始交易</strong><p>在群里 @官方机器人并发送“绑定股票 &lt;绑定码&gt;”，命令无需加“/”。使用交易账号和密码登录 <a href={EXCHANGE} target="_blank" rel="noreferrer">stock.azurpilot.com</a>；机器人重置密码后，首次登录需设置新密码。</p></li></ol><p className="muted">茗交所是模拟证券游戏，模拟币及股票不对应真实资金，不提供充值或提现。</p></aside>
    </div>}
  </section>
}
