import {expect,test} from '@playwright/test'

test('股票接入错误保留正常总览和返回入口',async({page})=>{
  const failures:string[]=[]
  page.on('pageerror',error=>failures.push(error.message))
  await page.routeWebSocket('**/api/v1/ws',socket=>{
    const server=socket.connectToServer()
    socket.onMessage(message=>{const request=JSON.parse(String(message));if(request.method==='stock.status')socket.send(JSON.stringify({v:1,type:'response',id:request.id,ok:false,error:{code:'STOCK_IDENTITY_DAMAGED',message:'实例股票身份需要恢复备份'}}));else server.send(message)})
    server.onMessage(message=>socket.send(message))
  })
  await page.goto('/#/i/demo-main/stock-exchange')
  await expect(page.getByRole('alert')).toContainText('实例股票身份需要恢复备份')
  await expect(page.getByRole('link',{name:'返回总览',exact:true})).toBeVisible()
  await expect(page.getByRole('button',{name:'完全重建账户',exact:true})).toHaveCount(0)
  await page.getByRole('link',{name:'返回总览',exact:true}).click()
  await expect(page).toHaveURL(/#\/i\/demo-main\/overview$/)
  await expect(page.getByRole('button',{name:'仪表盘设置',exact:true})).toBeVisible()
  expect(failures).toEqual([])
})
