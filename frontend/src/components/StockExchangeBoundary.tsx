import {Component,type ReactNode} from 'react'
import {Link,useParams} from 'react-router-dom'
import {Loading} from './ui'
import '../pages/stock-exchange.css'

export function StockExchangeFallback({message}:{message?:string}){
  const {instance=''}=useParams()
  return <div className="stock-instance-fallback">{message?<p role="alert">{message}</p>:<Loading/>}<Link className="button" to={`/i/${encodeURIComponent(instance)}/overview`}>返回总览</Link></div>
}
class Boundary extends Component<{children:ReactNode},{failed:boolean}>{
  state={failed:false}
  static getDerivedStateFromError(){return {failed:true}}
  render(){return this.state.failed?<StockExchangeFallback message="股票接入页面加载失败，请返回总览后重试。"/>:this.props.children}
}
export function StockExchangeBoundary({children}:{children:ReactNode}){
  const {instance}=useParams()
  return <Boundary key={instance}>{children}</Boundary>
}
