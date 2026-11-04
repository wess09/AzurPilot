import {expect,test} from '@playwright/test'

test('股票独立注册、QQ 引导及各主题布局',async({page})=>{
  await page.addInitScript(()=>{Object.defineProperty(navigator,'clipboard',{value:{writeText:async(value:string)=>{(window as Window & {copiedBindingCommand?:string}).copiedBindingCommand=value}}})})
  const failures:string[]=[],requests:string[]=[],responses:string[]=[]
  page.on('pageerror',error=>failures.push(error.message))
  page.on('websocket',socket=>{socket.on('framesent',frame=>requests.push(String(frame.payload)));socket.on('framereceived',frame=>responses.push(String(frame.payload)))})
  await page.goto('/#/i/demo-main/overview')
  await page.locator('.primary-nav').getByRole('link',{name:'茗喵证券交易所',exact:true}).click()
  await expect(page.getByRole('heading',{name:'注册当前实例股票',exact:true})).toBeVisible()
  await expect(page.getByRole('link',{name:'1126124220',exact:true})).toHaveAttribute('href','https://qm.qq.com/q/93NWF3S362')
  await expect(page.getByLabel('密码',{exact:true})).toHaveCount(0)
  await expect(page.locator('iframe')).toHaveCount(0)
  await page.getByLabel('股票用户名',{exact:true}).fill('测')
  await expect(page.getByRole('button',{name:'注册股票账户',exact:true})).toBeDisabled()
  await page.getByLabel('股票用户名',{exact:true}).fill('实例行情测试')
  await expect(page.getByRole('button',{name:'注册股票账户',exact:true})).toBeDisabled()
  await page.getByRole('checkbox',{name:/我已了解股票名称/}).check()
  await page.getByRole('button',{name:'注册股票账户',exact:true}).click()
  await expect(page.getByRole('heading',{name:'当前实例股票',exact:true})).toBeVisible()
  await expect(page.getByText('请在 QQ 群里 @官方机器人并发送下方命令，将股票绑定到你的交易账户。',{exact:true})).toBeVisible()
  await expect(page.locator('.stock-binding-code code')).toHaveText('绑定股票 MMEX-MOCK-demo-main')
  await page.getByRole('button',{name:'复制绑定命令',exact:true}).click()
  await expect(page.getByRole('status')).toHaveText('已复制绑定命令。')
  expect(await page.evaluate(()=>(window as Window & {copiedBindingCommand?:string}).copiedBindingCommand)).toBe('绑定股票 MMEX-MOCK-demo-main')
  await expect(page.getByRole('link',{name:'浏览交易所',exact:true})).toHaveAttribute('href','https://stock.azurpilot.com')
  await expect(page.locator('.app-shell')).toBeVisible()
  for(const width of [1600,900,390]){
    await page.setViewportSize({width,height:900})
    await expect(page.getByRole('heading',{name:'当前实例股票',exact:true})).toBeVisible()
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
    await page.screenshot({path:`test-results/stock-instance-${width}.png`,fullPage:true})
  }
  expect(requests.some(value=>value.includes('stock.register'))).toBe(true)
  expect(requests.some(value=>value.includes('stock.request'))).toBe(false)
  expect(responses.some(value=>value.includes('privateKey')||value.includes('uploadToken'))).toBe(false)
  expect(failures).toEqual([])
})

test('已绑定实例自动新标签页打开独立交易所',async({page,context})=>{
  await context.route('https://stock.azurpilot.com/**',route=>route.fulfill({contentType:'text/html',body:'<h1>交易所站点夹具</h1>'}))
  await page.routeWebSocket('**/api/v1/ws',socket=>{
    const server=socket.connectToServer(),pending=new Set<string>()
    socket.onMessage(message=>{const request=JSON.parse(String(message));if(request.method==='stock.status')pending.add(request.id);server.send(message)})
    server.onMessage(message=>{const reply=JSON.parse(String(message));if(pending.has(reply.id)&&reply.ok){reply.result={...reply.result,registered:true,bound:true,stock:{id:1,symbol:'MM000001',name:'已绑定实例',bound:true,price:800000,observedAt:Date.now()},bindingCode:''};socket.send(JSON.stringify(reply))}else socket.send(message)})
  })
  const opened=context.waitForEvent('page')
  await page.goto('/#/i/demo-main/stock-exchange')
  const exchange=await opened
  await exchange.waitForLoadState()
  await expect(exchange).toHaveURL('https://stock.azurpilot.com/')
  await expect(page.getByRole('link',{name:'进入交易所',exact:true})).toBeVisible()
  await expect(page.locator('.stock-binding-code')).toHaveCount(0)
  await exchange.close()
})


test('管理员删股状态明确展示且不能重新注册原股票',async({page})=>{
 await page.routeWebSocket('**/api/v1/ws',socket=>{
  const server=socket.connectToServer(),pending=new Set<string>()
  socket.onMessage(message=>{const request=JSON.parse(String(message));if(request.method==='stock.status')pending.add(request.id);server.send(message)})
  server.onMessage(message=>{const reply=JSON.parse(String(message));if(pending.has(reply.id)&&reply.ok){reply.result={...reply.result,registered:false,deleted:true,bound:false,stock:null,bindingCode:'',message:'股票已被管理员删除，已停止行动力上报'};socket.send(JSON.stringify(reply))}else socket.send(message)})
 })
 await page.goto('/#/i/demo-main/stock-exchange')
 await expect(page.getByRole('heading',{name:'股票已删除，上报已停止'})).toBeVisible()
 await expect(page.getByRole('button',{name:'注册股票账户',exact:true})).toHaveCount(0)
 await expect(page.getByText(/交易账户已解除绑定/)).toBeVisible()
})
