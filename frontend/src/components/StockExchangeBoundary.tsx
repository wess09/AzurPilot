/**
 * @fileoverview 股票接入页的错误边界：页面渲染出错时只塌这一页的回落视图，不拖垮整个应用。
 */

import {Component,type ReactNode} from 'react'
import {Link,useParams} from 'react-router-dom'
import {LoadBoundary} from './ui/load-boundary'
import {Button} from './ui/button'
import {useApp} from '../app/context'
import {stockText} from '../i18n.stock'
import '../pages/stock-exchange.css'

/** 股票页的回落视图：有 message 显示错误提示，否则显示加载态，总带一条「返回总览」的出口。 */
export function StockExchangeFallback({failed=false}:{failed?:boolean}){
  const {instance=''}=useParams(),{language}=useApp(),t=stockText[language]
  return <div className="stock-instance-fallback"><LoadBoundary ready={false} error={failed ? t.failed : undefined}/><Button variant="outline" asChild><Link to={`/i/${encodeURIComponent(instance)}/overview`}>{t.back}</Link></Button></div>
}
/** 类组件错误边界：子树渲染期抛错就整体切换为回落视图。 */
class Boundary extends Component<{children:ReactNode},{failed:boolean}>{
  state={failed:false}
  static getDerivedStateFromError(){return {failed:true}}
  render(){return this.state.failed?<StockExchangeFallback failed/>:this.props.children}
}
/** 以实例为键包裹股票页：换实例即重挂边界，上一个实例的 failed 状态不会带到下一个实例。 */
export function StockExchangeBoundary({children}:{children:ReactNode}){
  const {instance}=useParams()
  return <Boundary key={instance}>{children}</Boundary>
}
