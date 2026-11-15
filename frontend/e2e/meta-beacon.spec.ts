/**
 * @fileoverview META 作战设置用例：档案支援与换装的合并行为，求援次数替代旧开关后的保存与隐藏逻辑。
 */

import { expect, test } from '@playwright/test'

test('META作战合并支援，共用换装并保存档案期间暂停支援的设置', async ({page}, testInfo) => {
  await page.goto('/#/i/testpilot/task/OpsiAshBeacon')
  const dossier = page.locator('[id="OpsiAshBeacon.OpsiAshBeacon.DossierSkipAssist"]')
  const assist = page.locator('[id="OpsiAshBeacon.OpsiAshAssist.Enable"]')
  // 首次总览初始化与配置读取共用连接，等待配置实际就绪后再验收字段。
  await expect(dossier).toBeVisible({timeout: 30000})
  await expect(dossier).toHaveAccessibleName('开启档案时不进行支援')
  await expect(page.locator('#group-OpsiAshBeacon')).toContainText('档案已开启、正在解析或自动攻击时暂停每日META支援，待领奖时先领取奖励再恢复支援。')
  await expect(page.locator('#group-OpsiAshBeacon')).toContainText('开启自动换装备功能时务必开启此功能。')
  await expect(page.locator('[id="OpsiAshBeacon.OpsiAshBeacon.DossierAfterAssist"]')).toHaveCount(0)
  await expect(dossier).toHaveAttribute('aria-checked', 'false')
  await expect(assist).toHaveAccessibleName('启用META支援')
  await expect(assist).toHaveAttribute('aria-checked', 'true')
  await expect(page.locator('[id="OpsiAshBeacon.OpsiAshAssist.Tier"]')).toHaveValue('15')
  await expect(page.locator('#group-Equipment')).toHaveCount(1)
  await expect(page.locator('a[href$="/task/OpsiAshAssist"]')).toHaveCount(0)
  await expect(page.locator('[id="OpsiAshAssist.Equipment.Enable"]')).toHaveCount(0)

  await dossier.click()
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
  await page.reload()
  await expect(dossier).toHaveAttribute('aria-checked', 'true')
  await assist.click()
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
  await page.reload()
  await expect(assist).toHaveAttribute('aria-checked', 'false')
  await page.locator('#group-OpsiAshBeacon').screenshot({path: testInfo.outputPath('meta-merged-task.png')})

  // 临时实例恢复默认值，避免影响同文件的其他场景。
  await dossier.click()
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
  await assist.click()
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
})

test('META 求援次数替代旧开关，保存各模式并隐藏运行断点', async ({page}, testInfo) => {
  await page.goto('/#/i/testpilot/task/OpsiAshBeacon')
  const field = page.locator('[id="OpsiAshBeacon.OpsiAshBeacon.AssistRequestLimit"]')
  await expect(field).toBeVisible({timeout: 15000})
  await expect(field).toHaveValue('0')
  await expect(field).toHaveAttribute('inputmode', 'decimal')
  await expect(field).toHaveAccessibleName('求援次数上限')
  await expect(page.locator('[id="OpsiAshBeacon.OpsiAshBeacon.OneHitMode"]')).toHaveCount(0)
  await expect(page.locator('[id="OpsiAshBeacon.OpsiAshBeacon.AssistRequestState"]')).toHaveCount(0)

  for (const value of ['-1', '2', '0']) {
    await field.fill(value)
    await field.blur()
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
    await page.reload()
    await expect(field).toHaveValue(value)
  }

  await field.fill('-2')
  await field.blur()
  await expect(field).toHaveAttribute('aria-invalid', 'true')
  await expect(page.locator('[id="OpsiAshBeacon.OpsiAshBeacon.AssistRequestLimit-status"]')).toContainText('参数格式不正确')
  await field.fill('2')
  await field.press('Enter')
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('azurpilot.edits.config:testpilot'))).toBeNull()
  await expect(field).not.toHaveAttribute('aria-invalid', 'true')
  await page.reload()
  await expect(field).toHaveValue('2')
  await page.locator('.config-group').filter({has: field}).screenshot({
    path: testInfo.outputPath('meta-assist-limit.png'),
  })
})
