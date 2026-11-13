import { expect, test } from '@playwright/test'
import { mockWebGLRenderer } from '../webgl'

test.beforeEach(async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('azurpilot.theme', 'legacy-dark')
    localStorage.setItem('azurpilot.motion.speed', '4')
    localStorage.removeItem('azurpilot.motion.reduced')
  })
})

test('暗色任务卡片入场时子元素动画不会阻止清理', async ({page}) => {
  await page.goto('/#/i/demo-main/task/Main')
  const control = page.locator('.config-group [data-slot="switch"]').first()
  await expect(control).toBeVisible()
  const card = control.locator('xpath=ancestor::section[contains(concat(" ", normalize-space(@class), " "), " config-group ")]')
  await card.evaluate(async element => {
    const source = '/src/app/cardMotion.ts'
    const {applyCardStaggerMotion} = await import(/* @vite-ignore */ source)
    applyCardStaggerMotion([element], 1000)
    element.querySelector('[data-slot="switch-thumb"]')!.dispatchEvent(new AnimationEvent('animationend', {bubbles: true}))
  })
  await expect(card).toHaveClass(/\bmotion-card-stagger\b/)
  await expect(card).not.toHaveClass(/\bmotion-card-stagger\b/, {timeout: 5000})
  await expect(card).toHaveCSS('transform', 'none')
})

test('暗色开关初始位置与切换两次后的同状态位置一致', async ({page}) => {
  await page.goto('/#/i/demo-main/task/Main')
  const initialControl = page.locator('.config-group [data-slot="switch"][data-state="checked"]').first()
  await expect(initialControl).toBeVisible()
  const id = await initialControl.getAttribute('id')
  const control = page.locator(`[id="${id}"]`)
  const card = control.locator('xpath=ancestor::section[contains(concat(" ", normalize-space(@class), " "), " config-group ")]')
  await expect(card).not.toHaveClass(/\bmotion-card-stagger\b/, {timeout: 5000})
  const geometry = () => control.evaluate(element => {
    const track = element.getBoundingClientRect()
    const thumb = element.querySelector('[data-slot="switch-thumb"]')!.getBoundingClientRect()
    return {left: thumb.left - track.left, right: track.right - thumb.right, y: (thumb.top + thumb.bottom - track.top - track.bottom) / 2}
  })
  const initial = await geometry()
  await control.click()
  await expect(control).toHaveAttribute('aria-checked', 'false')
  await control.click()
  await expect(control).toHaveAttribute('aria-checked', 'true')
  await expect.poll(async () => {
    const after = await geometry()
    return Math.abs(after.left - initial.left) < 0.5 && Math.abs(after.right - initial.right) < 0.5 && Math.abs(after.y - initial.y) < 0.5
  }).toBe(true)
})

test('暗色玻璃卡片中的开关首次绘制与切换后保持一致', async ({browser}) => {
  const context = await browser.newContext({baseURL: 'http://127.0.0.1:5174', viewport: {width: 2560, height: 1249}})
  try {
    await context.addInitScript(() => {
      localStorage.setItem('azurpilot.theme', 'legacy-dark')
      localStorage.setItem('azurpilot.material', 'glass')
      localStorage.setItem('azurpilot.motion.speed', '2')
      localStorage.setItem('azurpilot.background', JSON.stringify({source: 'url', kind: 'image', urls: ['http://127.0.0.1:5174/azurpilot.webp'], active: 0, name: ''}))
      document.addEventListener('animationstart', event => {
        const card = event.target
        if (card instanceof HTMLElement && card.matches('.config-group')) {
          card.dataset.testCardAnimation = event.animationName
          card.dataset.testCardDelay = card.style.getPropertyValue('--card-stagger-delay')
          const style = getComputedStyle(card)
          card.dataset.testCardDuration = style.animationDuration
          card.dataset.testCardEasing = style.animationTimingFunction
          card.dataset.testActualDelay = style.animationDelay
          const animation = card.getAnimations().find(item => item instanceof CSSAnimation && item.animationName === event.animationName)
          const first = (animation?.effect as KeyframeEffect | undefined)?.getKeyframes()[0]
          card.dataset.testStartTransform = String(first?.transform ?? '')
          card.dataset.testStartOpacity = String(first?.opacity ?? '')
        }
      })
      new MutationObserver(() => {
        const card = document.getElementById('group-GuildLogistics')
        if (!card || card.dataset.testAnimatedOnMount !== undefined) return
        // 在本轮的挂载监听器都执行后、绘制前检查动画状态。
        queueMicrotask(() => {
          card.dataset.testAnimatedOnMount = String(card.classList.contains('motion-card-stagger'))
        })
      }).observe(document, {childList: true, subtree: true})
    })
    const page = await context.newPage()
    await mockWebGLRenderer(page, 'Hardware renderer')
    await page.goto('/#/i/demo-main/task/Main')
    const control = page.locator('[id="Main.Campaign.UseClearMode"]')
    await expect(control).toHaveAttribute('aria-checked', 'true')
    await expect(page.locator('.wallpaper-media')).toBeVisible()
    const card = page.locator('#group-Campaign')
    await expect(card).not.toHaveCSS('backdrop-filter', 'none')
    await expect(card).toHaveAttribute('data-test-card-animation', 'motion-card-stagger-in')
    await expect(card).not.toHaveClass(/\bmotion-card-stagger\b/, {timeout: 5000})
    await control.scrollIntoViewIfNeeded()
    await page.mouse.move(0, 0)
    const before = await control.screenshot()
    await control.click()
    await expect(control).toHaveAttribute('aria-checked', 'false')
    await control.click()
    await expect(control).toHaveAttribute('aria-checked', 'true')
    await control.blur()
    await control.evaluate(async element => {await Promise.allSettled(element.getAnimations({subtree: true}).map(animation => animation.finished))})
    await page.mouse.move(0, 0)
    const after = await control.screenshot()
    const changedPixels = await page.evaluate(async ([first, second]) => {
      const load = (data: string) => new Promise<HTMLImageElement>((resolve, reject) => {
        const image = new Image()
        image.onload = () => resolve(image)
        image.onerror = reject
        image.src = `data:image/png;base64,${data}`
      })
      const [a, b] = await Promise.all([load(first), load(second)])
      if (a.width !== b.width || a.height !== b.height) return Infinity
      const canvas = document.createElement('canvas')
      canvas.width = a.width
      canvas.height = a.height
      const ctx = canvas.getContext('2d')!
      ctx.drawImage(a, 0, 0)
      const pixelsA = ctx.getImageData(0, 0, a.width, a.height).data
      ctx.clearRect(0, 0, a.width, a.height)
      ctx.drawImage(b, 0, 0)
      const pixelsB = ctx.getImageData(0, 0, b.width, b.height).data
      let changed = 0
      for (let i = 0; i < pixelsA.length; i += 4) {
        if (Math.max(...[0, 1, 2].map(offset => Math.abs(pixelsA[i + offset] - pixelsB[i + offset]))) > 4) changed++
      }
      return changed
    }, [before.toString('base64'), after.toString('base64')])
    expect(changedPixels).toBeLessThanOrEqual(5)

    await page.evaluate(() => {location.hash = '/i/demo-main/task/Guild'})
    const logistics = page.locator('#group-GuildLogistics')
    const operation = page.locator('#group-GuildOperation')
    await expect(logistics).toHaveAttribute('data-test-animated-on-mount', 'true')
    await expect(logistics).toHaveAttribute('data-test-card-animation', 'motion-card-stagger-in')
    await expect(operation).toHaveAttribute('data-test-card-animation', 'motion-card-stagger-in')
    await expect(operation).toHaveAttribute('data-test-card-duration', '0.6s')
    await expect(operation).toHaveAttribute('data-test-card-easing', 'cubic-bezier(0.18, 0.92, 0.26, 1.02)')
    await expect(operation).toHaveAttribute('data-test-start-transform', 'translateY(18px) scale(0.975)')
    await expect(operation).toHaveAttribute('data-test-start-opacity', '0')
    const logisticsDelay = Number.parseFloat((await logistics.getAttribute('data-test-card-delay'))!)
    const operationDelay = Number.parseFloat((await operation.getAttribute('data-test-card-delay'))!)
    expect(logisticsDelay).toBeLessThan(operationDelay)
    const actualDelay = Number.parseFloat((await operation.getAttribute('data-test-actual-delay'))!) * 1000
    expect(actualDelay).toBeCloseTo(operationDelay)
  } finally {
    await context.close()
  }
})

test('暗色开关在不同窗口宽度和设备缩放下保持对齐', async ({browser}) => {
  test.setTimeout(120_000)
  const sizes: ReadonlyArray<readonly [number, number]> = [[1024, 1], [1280, 1.25], [1440, 1], [1440, 1.5], [1920, 2], [2560, 1]]
  for (const [width, dpr] of sizes) {
    const context = await browser.newContext({baseURL: 'http://127.0.0.1:5174', viewport: {width, height: 900}, deviceScaleFactor: dpr})
    try {
      await context.addInitScript(() => {
        localStorage.setItem('azurpilot.theme', 'legacy-dark')
        localStorage.setItem('azurpilot.motion.speed', '4')
      })
      const page = await context.newPage()
      await page.goto('/#/i/demo-main/task/Event2')
      const control = page.locator('[id="Event2.Campaign.UseClearMode"]')
      await expect(control).toHaveAttribute('aria-checked', 'true')
      const card = control.locator('xpath=ancestor::section[contains(concat(" ", normalize-space(@class), " "), " config-group ")]')
      await expect(card).not.toHaveClass(/\bmotion-card-stagger\b/, {timeout: 5000})
      const measure = () => control.evaluate(element => {
        const track = element.getBoundingClientRect()
        const thumb = element.querySelector('[data-slot="switch-thumb"]')!.getBoundingClientRect()
        return {left: thumb.left - track.left, right: track.right - thumb.right, center: (thumb.top + thumb.bottom - track.top - track.bottom) / 2}
      })
      const initial = await measure()
      expect(initial.right, `${width}px / ${dpr}x right inset`).toBeGreaterThanOrEqual(0)
      expect(initial.right, `${width}px / ${dpr}x checked thumb reaches the right edge`).toBeLessThanOrEqual(2.5)
      expect(Math.abs(initial.center), `${width}px / ${dpr}x vertical alignment`).toBeLessThan(0.5)
      await control.click()
      await expect(control).toHaveAttribute('aria-checked', 'false')
      await control.evaluate(async element => {await Promise.allSettled(element.getAnimations({subtree: true}).map(animation => animation.finished))})
      const unchecked = await measure()
      expect(unchecked.left, `${width}px / ${dpr}x unchecked thumb stays inside the track`).toBeGreaterThanOrEqual(0)
      expect(unchecked.left, `${width}px / ${dpr}x unchecked thumb reaches the left edge`).toBeLessThanOrEqual(2.5)
      await control.click()
      await expect(control).toHaveAttribute('aria-checked', 'true')
      await expect.poll(async () => {
        const next = await measure()
        return Math.abs(next.right - initial.right) < 0.5 && Math.abs(next.center - initial.center) < 0.5
      }).toBe(true)
    } finally {
      await context.close()
    }
  }
})
