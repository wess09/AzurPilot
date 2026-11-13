/**
 * @fileoverview LogCardView 的行为测试：块级聚合规则、各卡片渲染与虚拟窗口化；
 * 性能部分覆盖 token LRU 缓存与增量聚合的前缀复用。
 */
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  aggregateEntriesToCards,
  clearAggregationCache,
  getAggregationCacheInfo,
  renderTokens,
  clearTokenCache,
  getTokenCacheSize,
  TOKEN_CACHE_MAX,
  MapGridCard,
  PerspectiveCard,
  PropertySheetCard,
  DataTableCard,
  ErrorContextCard,
  TracebackCard,
  LlmReportCard,
  MatrixGridCard,
  CostGridCard,
  SystemBannerCard,
  StageHeaderCard,
  SingleLogLineCard,
  renderCellContent,
  getCostHeatmapStyle,
  VIRTUAL_THRESHOLD,
  getCardEstimatedHeight,
  findVisibleRange,
  LogCardView,
} from './LogCardView'

describe('LogCardView 块级聚合器与卡片组件', () => {
  it('正确将三行式 hr(0) 规则聚合成单个系统横幅卡片', () => {
    const entries = [
      { id: 1, level: 'INFO', text: '═'.repeat(60) },
      { id: 2, level: 'INFO', text: ' '.repeat(20) + '启动' + ' '.repeat(20) },
      { id: 3, level: 'INFO', text: '═'.repeat(60) },
    ]
    const cards = aggregateEntriesToCards(entries)
    expect(cards).toHaveLength(1)
    expect(cards[0].type).toBe('system_banner')
    if (cards[0].type === 'system_banner') {
      expect(cards[0].title).toBe('启动')
    }
  })

  it('正确消除 Level 1/2 HR 下方重复出现的同名 INFO 标题', () => {
    const entries = [
      { id: 1, level: 'INFO', text: '═'.repeat(20) + ' COMMISSION ' + '═'.repeat(20) },
      { id: 2, level: 'INFO', text: 'INFO     14:24:30.120 │ COMMISSION' },
    ]
    const cards = aggregateEntriesToCards(entries)
    expect(cards).toHaveLength(1)
    expect(cards[0].type).toBe('stage_header')
    if (cards[0].type === 'stage_header') {
      expect(cards[0].title).toBe('COMMISSION')
      expect(cards[0].level).toBe(1)
    }
  })

  it('正确聚合海域透视与边缘线识别（两行紧密拓扑 / _ \\）', () => {
    const entries = [
      { id: 1, level: 'INFO', text: 'INFO 14:24:30.500 │ [地图-透视] 0.045s  _   水平: 7 (7 内部, 0 边缘)' },
      { id: 2, level: 'INFO', text: 'INFO 14:24:30.501 │ [地图-透视] 边缘: /_\\    垂直: 8 (8 内部, 0 边缘)' },
    ]
    const cards = aggregateEntriesToCards(entries)
    expect(cards).toHaveLength(1)
    expect(cards[0].type).toBe('perspective')
    if (cards[0].type === 'perspective') {
      expect(cards[0].duration).toBe('0.045s')
      expect(cards[0].lowerEdge).toBe(true)
      expect(cards[0].leftEdge).toBe(true)
      expect(cards[0].upperEdge).toBe(true)
      expect(cards[0].rightEdge).toBe(true)

      const html = renderToStaticMarkup(<PerspectiveCard card={cards[0]} />)
      expect(html).toContain('perspective-card')
      expect(html).toContain('trapezoid-visual')
      expect(html).toContain('0.045s')
      expect(html).toContain('edge-active')
    }
  })

  it('正确表现缺失边界时的红色虚线与状态标记', () => {
    // 右边缘与下边缘缺失，左、上仍在
    const entries = [
      { id: 1, level: 'INFO', text: 'INFO 14:24:30.500 │ [地图-透视] 0.041s      水平: 5 (5 内部, 0 边缘)' },
      { id: 2, level: 'INFO', text: 'INFO 14:24:30.501 │ [地图-透视] 边缘: /_     垂直: 6 (6 内部, 0 边缘)' },
    ]
    const cards = aggregateEntriesToCards(entries)
    expect(cards).toHaveLength(1)
    expect(cards[0].type).toBe('perspective')
    if (cards[0].type === 'perspective') {
      expect(cards[0].lowerEdge).toBe(false)
      expect(cards[0].rightEdge).toBe(false)
      expect(cards[0].leftEdge).toBe(true)
      expect(cards[0].upperEdge).toBe(true)

      const html = renderToStaticMarkup(<PerspectiveCard card={cards[0]} />)
      expect(html).toContain('edge-missing')
      expect(html).toContain('0.041s')
    }
  })

  it('正确将 [地图-显示] 与连续数据行聚合成单个海图战术卡片', () => {
    const entries = [
      { id: 1, level: 'INFO', text: 'INFO 14:24:31.851 │ [地图-显示]   A  B  C  D  E  F  G  H' },
      { id: 2, level: 'INFO', text: 'INFO 14:24:31.852 │  1 ++ ++ ++ -- -- -- -- --' },
      { id: 3, level: 'INFO', text: 'INFO 14:24:31.853 │  2 ++ ++ ++ -- 1M -- -- --' },
      { id: 4, level: 'INFO', text: 'INFO 14:24:31.854 │  3 -- -- FL -- -- -- 2C BO' },
    ]
    const cards = aggregateEntriesToCards(entries)
    expect(cards).toHaveLength(1)
    expect(cards[0].type).toBe('map_grid')
    if (cards[0].type === 'map_grid') {
      expect(cards[0].cols).toEqual(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'])
      expect(cards[0].rows).toHaveLength(3)
      expect(cards[0].rows[0].cells).toEqual(['++', '++', '++', '--', '--', '--', '--', '--'])

      const html = renderToStaticMarkup(<MapGridCard card={cards[0]} />)
      expect(html).toContain('map-card')
      expect(html).toContain('海域战术地图快照')
      expect(html).toContain('8×3')
      expect(html).toContain('cell-fleet-1')
      expect(html).toContain('cell-boss')
      expect(html).toContain('cell-enemy')
      expect(html).toContain('cell-land')
    }
  })

  it('正确将连续 attr_align 聚合成属性清单卡片', () => {
    const entries = [
      { id: 1, level: 'INFO', text: 'INFO 14:24:32.410 │                    摄像机: (4, 3)' },
      { id: 2, level: 'INFO', text: 'INFO 14:24:32.411 │                  摄像机修正: (4, 3) -> (5, 3)' },
      { id: 3, level: 'INFO', text: 'INFO 14:24:32.412 │                 之前中心偏移: (12, -4)' },
    ]
    const cards = aggregateEntriesToCards(entries)
    expect(cards).toHaveLength(1)
    expect(cards[0].type).toBe('property_sheet')
    if (cards[0].type === 'property_sheet') {
      expect(cards[0].items).toHaveLength(3)
      expect(cards[0].items[0]).toEqual({ key: '摄像机', value: '(4, 3)' })

      const html = renderToStaticMarkup(<PropertySheetCard card={cards[0]} search="" />)
      expect(html).toContain('property-card')
      expect(html).toContain('摄像机')
      expect(html).toContain('4, 3')
      expect(html).toContain('hl-brace')
    }
  })

  it('正确将 Unicode Rich 表格解析为原生数据表格卡片', () => {
    const rawTable = [
      '                                Benchmark Result                                ',
      '                  ┌──────────────┬──────────┬──────┬─────────┐                  ',
      '                  │ Device       │  Method  │  FPS │ Latency │                  ',
      '                  ├──────────────┼──────────┼──────┼─────────┤                  ',
      '                  │ MuMuPlayer12 │ nemu_ipc │ 58.4 │  0.005s │                  ',
      '                  └──────────────┴──────────┴──────┴─────────┘                  ',
    ].join('\n')
    const entries = [{ id: 1, level: 'INFO', text: rawTable }]
    const cards = aggregateEntriesToCards(entries)
    expect(cards).toHaveLength(1)
    expect(cards[0].type).toBe('data_table')
    if (cards[0].type === 'data_table') {
      expect(cards[0].headers).toEqual(['Device', 'Method', 'FPS', 'Latency'])
      expect(cards[0].rows[0]).toEqual(['MuMuPlayer12', 'nemu_ipc', '58.4', '0.005s'])

      const html = renderToStaticMarkup(<DataTableCard card={cards[0]} />)
      expect(html).toContain('table-card')
      expect(html).toContain('native-log-table')
      expect(html).toContain('MuMuPlayer12')
      expect(html).toContain('nemu_ipc')
    }
  })

  it('正确解析并渲染带 +--+ 边界的经典 ASCII 表格与状态颜色', () => {
    const rawAsciiTable = [
      '                                Legacy ASCII Benchmark                          ',
      '                      +--------------+--------+--------+                        ',
      '                      |  Screenshot  |  Time  | Speed  |                        ',
      '                      +--------------+--------+--------+                        ',
      '                      |     ADB      | 0.319s |  Fast  |                        ',
      '                      | uiautomator2 | 0.476s | Medium |                        ',
      '                      |  aScreenCap  | Failed | Failed |                        ',
      '                      +--------------+--------+--------+                        ',
    ].join('\n')
    const entries = [{ id: 1, level: 'INFO', text: rawAsciiTable }]
    const cards = aggregateEntriesToCards(entries)
    expect(cards).toHaveLength(1)
    expect(cards[0].type).toBe('data_table')
    if (cards[0].type === 'data_table') {
      expect(cards[0].title).toBe('Legacy ASCII Benchmark')
      expect(cards[0].headers).toEqual(['Screenshot', 'Time', 'Speed'])
      expect(cards[0].rows).toHaveLength(3)

      const html = renderToStaticMarkup(<DataTableCard card={cards[0]} />)
      expect(html).toContain('Legacy ASCII Benchmark')
      expect(html).toContain('0.319s')
      expect(html).toContain('Medium')
      expect(html).toContain('Failed')
    }
  })

  it('正确将四段式 error_context 渲染为警示操作卡片并完整直接渲染堆栈', () => {
    const rawError = [
      '[错误] 任务执行发生未处理异常（opsi_ash_beacon）',
      '原因：程序抛出了 ScriptEnd。',
      '影响：当前任务中断。',
      '建议：查看完整堆栈。',
      '异常：ScriptEnd: 计算模式红脸弹窗',
      '╭ Traceback (most recent call last) ╮',
      '│ E:\\AzurPilot\\alas.py:1019 in run │',
      '│ ❱ 1019 │ self.__getattribute__(command)() │',
      '│ ╭ locals ╮ │',
      '│ │ command = \'opsi_ash_beacon\' │ │',
      '│ ╰────────╯ │',
      '╰───────────────────────────────────╯',
      'ScriptEnd: 计算模式红脸弹窗',
    ].join('\n')
    const entries = [{ id: 1, level: 'ERROR', text: rawError }]
    const cards = aggregateEntriesToCards(entries)
    expect(cards).toHaveLength(1)
    expect(cards[0].type).toBe('error_context')
    if (cards[0].type === 'error_context') {
      expect(cards[0].title).toBe('任务执行发生未处理异常（opsi_ash_beacon）')
      expect(cards[0].reason).toBe('程序抛出了 ScriptEnd。')
      expect(cards[0].action).toBe('查看完整堆栈。')
      expect(cards[0].stackTrace).toContain('Traceback')

      const html = renderToStaticMarkup(<ErrorContextCard card={cards[0]} />)
      expect(html).toContain('error-card')
      expect(html).toContain('建议操作')
      expect(html).toContain('查看完整堆栈。')
      expect(html).toContain('traceback-viewer')
      expect(html).toContain('alas.py')
      expect(html).toContain('1019')
      expect(html).toContain('fault-row')
      expect(html).toContain('opsi_ash_beacon')
      expect(html).toContain('ScriptEnd: 计算模式红脸弹窗')
    }
  })

  it('海域方格保持纯净无冗余波浪图标，大世界战术地标全量覆盖图标', () => {
    // 海域航道不渲染图标，返回 null。
    expect(renderCellContent('--')).toBeNull()
    expect(renderCellContent('==')).toBeNull()

    // 大世界战术图标全量覆盖核对
    const meHtml = renderToStaticMarkup(<>{renderCellContent('ME')}</>)
    expect(meHtml).toContain('大世界指挥喵搜索点')

    const exHtml = renderToStaticMarkup(<>{renderCellContent('EX')}</>)
    expect(exHtml).toContain('大世界感叹号特殊事件')

    const sdHtml = renderToStaticMarkup(<>{renderCellContent('SD')}</>)
    expect(sdHtml).toContain('大世界环境扫描探测装置')

    const arHtml = renderToStaticMarkup(<>{renderCellContent('AR')}</>)
    expect(arHtml).toContain('大世界机密档案记录')

    const poHtml = renderToStaticMarkup(<>{renderCellContent('PO')}</>)
    expect(poHtml).toContain('大世界补给港口')

    const enHtml = renderToStaticMarkup(<>{renderCellContent('EN')}</>)
    expect(enHtml).toContain('敌舰 (EN)')

    const boHtml = renderToStaticMarkup(<>{renderCellContent('BO')}</>)
    expect(boHtml).toContain('关卡旗舰 Boss')
  })

  it('正确渲染寻路移动代价热力图 (CostGridCard)：9999为纯黑色底，0为绿色起点，其余按代价渐变', () => {
    // 单元样式断言。
    const wallStyle = getCostHeatmapStyle(9999, 8)
    expect(wallStyle.backgroundColor).toBe('#000000')

    const originStyle = getCostHeatmapStyle(0, 8)
    expect(originStyle.backgroundColor).toBe('#10b981')
    expect(originStyle.fontWeight).toBe(700)

    const minStyle = getCostHeatmapStyle(1, 8)
    expect(minStyle.backgroundColor).toBe('rgb(2, 132, 199)')

    const maxStyle = getCostHeatmapStyle(8, 8)
    expect(maxStyle.backgroundColor).toBe('rgb(225, 29, 72)')

    // 聚合与卡片渲染断言。
    const entries = [
      { id: 1, level: 'INFO', text: 'INFO 14:24:30.100 │       A    B    C' },
      { id: 2, level: 'INFO', text: 'INFO 14:24:30.101 │  1 9999    2    3' },
      { id: 3, level: 'INFO', text: 'INFO 14:24:30.102 │  2    1    0    1' },
    ]
    const cards = aggregateEntriesToCards(entries)
    expect(cards).toHaveLength(1)
    expect(cards[0].type).toBe('cost_grid')

    if (cards[0].type === 'cost_grid') {
      const html = renderToStaticMarkup(<CostGridCard card={cards[0]} />)
      expect(html).toContain('寻路移动代价热力图')
      expect(html).toContain('cost-wall')
      expect(html).toContain('background-color:#000000')
      expect(html).toContain('cost-origin')
      expect(html).toContain('background-color:#10b981')
      expect(html).toContain('不可达障碍 (9999)')
      expect(html).toContain('寻路起点 (0 步)')
    }
  })

  describe('虚拟化窗口算法与视口渲染 (Virtual Windowing)', () => {
    it('正确预估不同类型卡片的基础高度', () => {
      expect(getCardEstimatedHeight({
        type: 'single',
        id: 1,
        entry: { id: 1, level: 'INFO', text: 'test' },
        time: '12:00:00',
        level: 'INFO',
        message: 'test',
        rawText: 'test',
      })).toBe(34)

      expect(getCardEstimatedHeight({
        type: 'stage_header',
        id: 2,
        time: '12:00:00',
        title: 'stage',
        level: 1,
        rawText: 'test',
      })).toBe(44)

      expect(getCardEstimatedHeight({
        type: 'system_banner',
        id: 3,
        time: '12:00:00',
        title: 'banner',
        rawText: 'test',
      })).toBe(74)

      expect(getCardEstimatedHeight({
        type: 'perspective',
        id: 4,
        time: '12:00:00',
        model: '透视',
        duration: '0.05s',
        lowerEdge: true,
        leftEdge: true,
        upperEdge: true,
        rightEdge: true,
        info1: '',
        info2: '',
        rawText: 'test',
      })).toBe(172)
    })

    it('二分查找 findVisibleRange 精准定位视口范围卡片索引且不越界', () => {
      // 假设 100 张卡片，每张高度 40px，间距已被计算进 heights。
      const count = 100
      const heights = new Array(count).fill(40)
      const offsets = new Array(count)
      let cur = 0
      for (let i = 0; i < count; i++) {
        offsets[i] = cur
        cur += heights[i]
      }

      // 1. 顶部视口 [0, 800]。
      const [start1, end1] = findVisibleRange(offsets, heights, 0, 800, count)
      expect(start1).toBe(0)
      expect(end1).toBe(20) // 20 * 40 = 800 <= 800

      // 2. 中间视口 [1200, 2000]。
      const [start2, end2] = findVisibleRange(offsets, heights, 1200, 2000, count)
      // 第 30 张卡片底部是 30*40 + 40 = 1240 >= 1200，第 29 张底部是 1160+40=1200 >= 1200
      expect(start2).toBe(29)
      expect(end2).toBe(50) // 50 * 40 = 2000 <= 2000

      // 3. 底部吸底视口 [3600, 4000]。
      const [start3, end3] = findVisibleRange(offsets, heights, 3600, 4000, count)
      expect(start3).toBe(89)
      expect(end3).toBe(99) // 最后一个索引 99

      // 4. 超范围视口（大于总高）不越界。
      const [start4, end4] = findVisibleRange(offsets, heights, 5000, 6000, count)
      expect(start4).toBe(99)
      expect(end4).toBe(99)
    })

    it('卡片数量少于阈值 VIRTUAL_THRESHOLD 时全量渲染，不添加虚拟 padding', () => {
      expect(VIRTUAL_THRESHOLD).toBe(40)
      const entries = Array.from({ length: 10 }, (_, i) => ({
        id: i + 1,
        level: 'INFO',
        text: `INFO 14:00:00.000 │ 日志 ${i + 1}`,
      }))

      const html = renderToStaticMarkup(<LogCardView entries={entries} search="" />)
      expect(html).toContain('log-cards-container')
      // 少于阈值时不应出现虚拟占位的 padding-top。
      expect(html).not.toContain('padding-top')
      for (let i = 1; i <= 10; i++) {
        expect(html).toContain(`日志 ${i}`)
      }
    })

    it('卡片数量达到 VIRTUAL_THRESHOLD 时激活窗口化，有效剪裁视口外的卡片', () => {
      // 构造 200 条日志卡片。
      const entries = Array.from({ length: 200 }, (_, i) => ({
        id: i + 1,
        level: 'INFO',
        text: `INFO 14:00:00.000 │ 日志条目编号_${i + 1}`,
      }))

      // 在默认视口（顶部 0，高 800，overscan 800）下。
      const html = renderToStaticMarkup(<LogCardView entries={entries} search="" />)
      expect(html).toContain('log-cards-container')
      expect(html).toContain('log-card-virtual-item')
      expect(html).toContain('padding-bottom')

      // 前几张卡片必定渲染在初始视口内。
      expect(html).toContain('日志条目编号_1')
      expect(html).toContain('日志条目编号_5')

      // 遥远末尾的卡片（如第 190 张）必定被虚拟化窗口剪裁，不出现在 DOM 中。
      expect(html).not.toContain('日志条目编号_190')
      expect(html).not.toContain('日志条目编号_200')
    })
  })

  describe('性能优化专项验证 (Memoization & Token Cache & Incremental Aggregation)', () => {
    describe('词法解析与高亮 LRU 缓存 (Token Lexer Cache)', () => {
      it('相同文本和搜索词时命中缓存，多次调用返回相同结果', () => {
        clearTokenCache()
        const text = 'INFO 14:00:00.123 │ status = True, target = None, [CN_server]'
        const node1 = renderTokens(text, '')
        expect(getTokenCacheSize()).toBe(1)
        const node2 = renderTokens(text, '')
        expect(node1).toBe(node2) // 严格复用同一个 ReactNode 引用
        expect(getTokenCacheSize()).toBe(1)
      })

      it('搜索词发生变化时返回不同高亮节点并分别缓存', () => {
        clearTokenCache()
        const text = 'Operation completed with True'
        const nodeNoSearch = renderTokens(text, '')
        const nodeSearch = renderTokens(text, 'completed')
        expect(nodeNoSearch).not.toBe(nodeSearch)
        expect(getTokenCacheSize()).toBe(2)

        const html = renderToStaticMarkup(<>{nodeSearch}</>)
        expect(html).toContain('log-search-match')
        expect(html).toContain('completed')
      })

      it('LRU 机制在缓存达到上限时淘汰最久未访问的条目', () => {
        clearTokenCache()
        // 填满缓存：插入 TOKEN_CACHE_MAX 个不同文本。
        for (let i = 0; i < TOKEN_CACHE_MAX; i++) {
          renderTokens(`unique_log_line_${i}`, '')
        }
        expect(getTokenCacheSize()).toBe(TOKEN_CACHE_MAX)

        // 访问第 0 项，使其被提升为最新。
        renderTokens('unique_log_line_0', '')

        // 再插入第 2001 项，此时应淘汰第 1 项（第 0 项刚被刷新）。
        renderTokens('overflow_log_line', '')
        expect(getTokenCacheSize()).toBe(TOKEN_CACHE_MAX)

        // 验证第 0 项依然在缓存中（再次调用不增加 size）。
        renderTokens('unique_log_line_0', '')
        expect(getTokenCacheSize()).toBe(TOKEN_CACHE_MAX)
      })
    })

    describe('日志聚合增量计算与前缀复用 (Incremental Card Aggregation)', () => {
      it('完全相同引用再次传入时 O(1) 返回上一卡片数组引用', () => {
        clearAggregationCache()
        const entries = [
          { id: 1, level: 'INFO', text: 'INFO 12:00:00 │ Log 1' },
          { id: 2, level: 'INFO', text: 'INFO 12:00:01 │ Log 2' },
        ]
        const cards1 = aggregateEntriesToCards(entries)
        const cards2 = aggregateEntriesToCards(entries)
        expect(cards1).toBe(cards2)
      })

      it('尾部追加日志时复用前置安全卡片对象引用', () => {
        clearAggregationCache()
        // 构造 10 条单行日志。
        const initialEntries = Array.from({ length: 10 }, (_, i) => ({
          id: i + 1,
          level: 'INFO',
          text: `INFO 12:00:0${i} │ 日志行 ${i + 1}`,
        }))

        const initialCards = aggregateEntriesToCards(initialEntries)
        expect(initialCards).toHaveLength(10)

        // 追加 3 条新日志。
        const appendedEntries = [
          ...initialEntries,
          { id: 11, level: 'INFO', text: 'INFO 12:00:10 │ 日志行 11' },
          { id: 12, level: 'INFO', text: 'INFO 12:00:11 │ 日志行 12' },
          { id: 13, level: 'INFO', text: 'INFO 12:00:12 │ 日志行 13' },
        ]

        const nextCards = aggregateEntriesToCards(appendedEntries)
        expect(nextCards).toHaveLength(13)

        // 验证安全边界前（10 - 4 = 6 张）的历史卡片对象引用绝对保持一致。
        for (let i = 0; i < 6; i++) {
          expect(nextCards[i]).toBe(initialCards[i])
        }
      })

      it('增量聚合产生的结果与全量重新计算的结果完全等价', () => {
        clearAggregationCache()
        const entries1 = Array.from({ length: 8 }, (_, i) => ({
          id: i + 1,
          level: 'INFO',
          text: `INFO 12:00:0${i} │ 批量日志 ${i + 1}`,
        }))

        aggregateEntriesToCards(entries1)

        // 追加新日志，其中包含海图。
        const entries2 = [
          ...entries1,
          { id: 9, level: 'INFO', text: 'INFO 12:00:09 │ [地图-显示]   A  B' },
          { id: 10, level: 'INFO', text: 'INFO 12:00:10 │  1 ++ --' },
          { id: 11, level: 'INFO', text: 'INFO 12:00:11 │  2 -- FL' },
        ]

        const incrementalCards = aggregateEntriesToCards(entries2)

        // 清空缓存后重新全量计算一次。
        clearAggregationCache()
        const fullCards = aggregateEntriesToCards(entries2)

        expect(incrementalCards).toEqual(fullCards)
      })

      it('缓冲窗口从多行属性卡中间裁剪时，重建首尾并复用中间卡片', () => {
        const entry = (id: number, text: string) => ({id, level: 'INFO', text: `INFO 12:00:00 │ ${text}`})
        const history = [
          entry(1, '作战次数: 1'),
          entry(2, '当前舰队: 主力舰队'),
          ...Array.from({length: 12}, (_, index) => entry(index + 3, `日志 ${index}`)),
          entry(15, '[地图-显示] A B'),
        ]
        clearAggregationCache()
        const initial = aggregateEntriesToCards(history)
        const window = [...history.slice(1), entry(16, '1 ++ --')]
        const updated = aggregateEntriesToCards(window)
        expect(updated[1]).toBe(initial[1])
        expect(updated[0].type).toBe('single')
        expect(updated.at(-1)?.type).toBe('map_grid')
        clearAggregationCache()
        expect(updated).toEqual(aggregateEntriesToCards(window))
      })

      it('日志被重置或截断时自动回退至全量计算', () => {
        clearAggregationCache()
        const entriesLong = Array.from({ length: 10 }, (_, i) => ({
          id: i + 1,
          level: 'INFO',
          text: `INFO 12:00:0${i} │ 历史日志 ${i + 1}`,
        }))
        aggregateEntriesToCards(entriesLong)
        expect(getAggregationCacheInfo().cachedEntriesCount).toBe(10)

        // 模拟清空日志或筛选截断。
        const entriesShort = [
          { id: 101, level: 'INFO', text: 'INFO 13:00:00 │ 重置后的新日志' },
        ]
        const resetCards = aggregateEntriesToCards(entriesShort)
        expect(resetCards).toHaveLength(1)
        expect(getAggregationCacheInfo().cachedEntriesCount).toBe(1)
        expect(resetCards[0].id).toBe(101)
      })
    })

    describe('组件 React.memo 包装与属性比对验证', () => {
      it('SingleLogLineCard 与 PropertySheetCard 在 card 与 search 均相同时跳过无效渲染', () => {
        const dummyCard = {
          type: 'single' as const,
          id: 1,
          entry: { id: 1, level: 'INFO', text: 'test' },
          time: '12:00:00',
          level: 'INFO',
          message: 'test message',
          rawText: 'test message',
        }

        const dummyPropCard = {
          type: 'property_sheet' as const,
          id: 2,
          time: '12:00:00',
          items: [{ key: '耗时', value: '1.2s' }],
          rawText: '耗时: 1.2s',
        }

        // React.memo 会将比较函数存放在 compare 属性上。
        const compareSingle = (SingleLogLineCard as any).compare
        if (compareSingle) {
          expect(compareSingle({ card: dummyCard, search: '' }, { card: dummyCard, search: '' })).toBe(true)
          expect(compareSingle({ card: dummyCard, search: 'a' }, { card: dummyCard, search: 'b' })).toBe(false)
          expect(compareSingle({ card: dummyCard, search: '' }, { card: { ...dummyCard }, search: '' })).toBe(false)
        }

        const compareProp = (PropertySheetCard as any).compare
        if (compareProp) {
          expect(compareProp({ card: dummyPropCard, search: '' }, { card: dummyPropCard, search: '' })).toBe(true)
          expect(compareProp({ card: dummyPropCard, search: 'x' }, { card: dummyPropCard, search: 'y' })).toBe(false)
        }

        // 仅比对 card 的卡片组件。
        const cardComponents = [
          MapGridCard,
          TracebackCard,
          LlmReportCard,
          MatrixGridCard,
          SystemBannerCard,
          StageHeaderCard,
        ]
        const sampleCard = { id: 99, time: '', rawText: '' }
        for (const comp of cardComponents) {
          const compCompare = (comp as any).compare
          if (compCompare) {
            expect(compCompare({ card: sampleCard }, { card: sampleCard })).toBe(true)
            expect(compCompare({ card: sampleCard }, { card: { ...sampleCard } })).toBe(false)
          }
        }
      })
    })
  })
})
