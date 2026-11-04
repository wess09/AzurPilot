/** 股票实例页面的隔离夹具；不连接外网，不创建交易账户。 */
export function createStockProxy(snapshot){
  const instances=new Map(),listeners=new Set()
  const base={url:'https://stock.azurpilot.com',bound:false,bindingCode:'',message:'输入股票名称即可注册当前实例'}
  const status=name=>{
    const value=instances.get(name),row=snapshot(name)
    return {...base,instance:name,instanceId:`mock-instance-${name}`,registered:!!value,stock:value?.stock??null,bindingCode:value?.code??'',message:value?'行动力增量同步已启用':base.message,lastObservedAt:row?.observedAt??0}
  }
  return {
    subscribe(listener){listeners.add(listener);return ()=>listeners.delete(listener)},
    close(){listeners.clear()},
    status,
    register(name,{username,noticeVersion}){
      if(typeof username!=='string'||[...username.trim()].length<2||[...username.trim()].length>32||/[\r\n\0]/.test(username))throw Object.assign(new Error('股票名称须为 2 至 32 个字符'),{code:'INVALID_PARAMS'})
      if(!instances.has(name)&&noticeVersion!=='stock-public-v2-20261101')throw Object.assign(new Error('请确认股票公开同步告知'),{code:'STOCK_NOTICE_REQUIRED'})
      if(!instances.has(name)){
        const id=instances.size+1,row=snapshot(name)
        instances.set(name,{stock:{id,symbol:`MM${String(id).padStart(6,'0')}`,name:username.trim(),price:(row?.actionPoints??0)*100,observedAt:(row?.observedAt??0)*1000,bound:false},code:`MMEX-MOCK-${name}`})
        listeners.forEach(listener=>listener({instance:name}))
      }
      return status(name)
    },
    rebuild(name,{confirm=false,scope='instance'}={}){
      if(scope!=='instance')throw Object.assign(new Error('重建范围已变化，请重新确认'),{code:'STOCK_REBUILD_SCOPE_CHANGED'})
      if(confirm)instances.delete(name)
      return {instance:name,scope,affectedInstances:[name],rebuilt:confirm}
    },
  }
}
