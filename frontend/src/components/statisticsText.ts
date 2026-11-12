/**
 * @fileoverview 统计页后端文本的多语言显示。
 *
 * 统计接口的指标名、序列名、表头、备注等沿用中文：前端按中文名查图标，导出与筛选也依赖它们。
 * 这里在显示前把这些中文翻译成当前语言；物品名、任务名由后端随报表附带的 glossary 提供。
 * 简体中文直接显示原文；查不到的文本保持原样，不猜测。
 */

import type {Language} from '../i18n'
import type {ResourceFlowReport, StatGlossary, StatTable, StatisticsReport} from '../api/types'

type Target = 'en-US' | 'ja-JP' | 'zh-TW'
type Row = readonly [zh: string, en: string, ja: string, tw: string]

// 名词与短语：整段相等时替换。
const TERMS: readonly Row[] = [
  // 资源与货币，措辞与资源卡片一致
  ['石油', 'Oil', '燃料', '石油'],
  ['物资', 'Coins', '資金', '物資'],
  ['钻石', 'Gems', 'ダイヤ', '鑽石'],
  ['心智魔方', 'Cubes', 'キューブ', '心智魔方'],
  ['魔方', 'Cubes', 'キューブ', '魔方'],
  ['活动 PT', 'Event PT', 'イベント PT', '活動 PT'],
  ['核心数据', 'Core data', 'コアデータ', '核心數據'],
  ['荣誉勋章', 'Medals of Honor', '勲章', '榮譽勳章'],
  ['功勋', 'Merit', '戦果', '功勳'],
  ['舰队币', 'Guild coins', '艦隊コイン', '艦隊幣'],
  ['行动力', 'Action points', '行動力', '行動力'],
  ['行动力资产', 'Action Point Assets', '行動力資産', '行動力資產'],
  ['海里数', 'Nautical Miles', '海里数', '海里數'],
  ['作战补给凭证', 'Supply vouchers', '作戦補給コイン', '作戰補給憑證'],
  ['特别兑换凭证', 'Special exchange vouchers', '特別交換コイン', '特別兌換憑證'],
  ['心智单元', 'Cognitive chips', 'メンタルユニット', '心智單元'],
  ['心智单元II', 'Cognitive chips II', 'メンタルユニットII', '心智單元II'],
  ['试作型突破部件', 'Prototype Gear Upgrade Part', '試作型突破パーツ', '試作型突破部件'],
  ['后宅粮食', 'Dorm food', '寮舎の食料', '後宅糧食'],
  ['活动 UR 点数', 'Event UR points', 'イベントURポイント', '活動 UR 點數'],
  ['家具币', 'Decor tokens', '家具コイン', '家具幣'],
  ['建造券', 'Build tickets', '建造チケット', '建造券'],
  // 资源管理分组
  ['货币', 'Currency', '通貨', '貨幣'],
  ['材料', 'Materials', '素材', '材料'],
  ['物品', 'Item', 'アイテム', '物品'],
  ['兵装研发材料', 'Gear research materials', '装備開発素材', '兵裝研發材料'],
  ['实验计划', 'Testing reports', '実験計画', '實驗計畫'],
  ['强化部件', 'Enhancement parts', '強化パーツ', '強化部件'],
  ['突破部件', 'Upgrade parts', '突破パーツ', '突破部件'],
  ['装备研发图纸', 'Gear design plans', '装備設計図', '裝備研發圖紙'],
  ['研发图纸', 'Design plans', '設計図', '研發圖紙'],
  ['研发材料', 'Research materials', '開発素材', '研發材料'],
  ['金菜', 'T4 plates', '金パーツ', '金菜'],
  // 资源管理的收支用途
  ['奖励领取', 'Reward collected', '報酬受取', '獎勵領取'],
  ['后宅购粮', 'Dorm food purchase', '寮舎の食料購入', '後宅購糧'],
  ['任务内库存变化', 'Change within task', 'タスク内の在庫変化', '任務內庫存變化'],
  ['跨任务或离线变化', 'Change between tasks or offline', 'タスク間・オフライン中の変化', '跨任務或離線變化'],
  ['活动切换或库存校正', 'Event switch or stock correction', 'イベント切替・在庫補正', '活動切換或庫存校正'],
  // 大世界与经验指标
  ['战斗次数', 'Battles', '戦闘回数', '戰鬥次數'],
  ['出击轮数', 'Sortie rounds', '出撃ラウンド数', '出擊輪數'],
  ['出击消耗', 'Sortie cost', '出撃消費', '出擊消耗'],
  ['明石遭遇', 'Akashi encounters', '明石遭遇', '明石遭遇'],
  ['明石遭遇率', 'Akashi encounter rate', '明石遭遇率', '明石遭遇率'],
  ['塞壬研究装置', 'Siren research devices', 'セイレーン研究装置', '塞壬研究裝置'],
  ['装置获取率', 'Device drop rate', '装置獲得率', '裝置獲取率'],
  ['购买行动力', 'Action points bought', '購入した行動力', '購買行動力'],
  ['平均每次购买', 'Average per purchase', '1回あたりの購入量', '平均每次購買'],
  ['净行动力', 'Net action points', '純行動力', '淨行動力'],
  ['循环效率', 'Loop efficiency', '循環効率', '循環效率'],
  ['平均战斗时长', 'Average battle time', '平均戦闘時間', '平均戰鬥時長'],
  ['预估经验效率', 'Estimated EXP rate', '推定経験値効率', '預估經驗效率'],
  ['今日战斗', 'Battles today', '本日の戦闘', '今日戰鬥'],
  ['今日经验', 'EXP today', '本日の経験値', '今日經驗'],
  ['今日运行', 'Run time today', '本日の稼働', '今日運行'],
  ['目标等级', 'Target level', '目標レベル', '目標等級'],
  ['平均每轮时长', 'Average round time', '平均ラウンド時間', '平均每輪時長'],
  ['短猫平均战斗时长', 'Average meowfficer farming battle time', '短猫平均戦闘時間', '短貓平均戰鬥時長'],
  ['完成委托', 'Commissions completed', '完了した委託', '完成委託'],
  ['掉落记录', 'Drop records', 'ドロップ記録', '掉落記錄'],
  // 单位
  ['场', 'battles', '戦', '場'],
  ['轮', 'rounds', 'ラウンド', '輪'],
  ['次', 'times', '回', '次'],
  ['个', '', '個', '個'],
  ['秒', 's', '秒', '秒'],
  ['/小时', '/h', '/時間', '/小時'],
  ['分钟', 'min', '分', '分鐘'],
  ['项', '', '件', '項'],
  // 表格标题、列名与单元格
  ['短猫运行统计', 'Meowfficer farming runs', '短猫の稼働統計', '短貓運行統計'],
  ['侵蚀等级', 'Hazard level', '侵食レベル', '侵蝕等級'],
  ['有效轮数', 'Valid rounds', '有効ラウンド数', '有效輪數'],
  ['平均战斗秒数', 'Avg. battle seconds', '平均戦闘秒数', '平均戰鬥秒數'],
  ['平均每轮秒数', 'Avg. round seconds', '平均ラウンド秒数', '平均每輪秒數'],
  ['研究装置', 'Research devices', '研究装置', '研究裝置'],
  ['获取率（%）', 'Drop rate (%)', '獲得率（%）', '獲取率（%）'],
  ['统计来源', 'Source', '集計元', '統計來源'],
  ['实测', 'Measured', '実測', '實測'],
  ['估算', 'Estimated', '推定', '估算'],
  ['暂无记录', 'No records yet', '記録なし', '暫無記錄'],
  ['委托收益明细', 'Commission income details', '委託収益の明細', '委託收益明細'],
  ['资源', 'Resource', 'リソース', '資源'],
  ['总收益', 'Total', '総収益', '總收益'],
  ['掉落记录数', 'Drop records', 'ドロップ記録数', '掉落記錄數'],
  ['平均每次掉落', 'Average per drop', '1回あたりの平均', '平均每次掉落'],
  ['委托结算记录', 'Commission settlement records', '委託の精算記録', '委託結算記錄'],
  ['时间', 'Time', '時刻', '時間'],
  ['委托数量', 'Commissions', '委託数', '委託數量'],
  ['舰船升级进度', 'Ship leveling progress', '艦船のレベル上げ進捗', '艦船升級進度'],
  ['位置', 'Position', '位置', '位置'],
  ['等级', 'Level', 'レベル', '等級'],
  ['当前经验', 'Current EXP', '現在の経験値', '當前經驗'],
  ['累计经验', 'Total EXP', '累計経験値', '累計經驗'],
  ['目标经验', 'Target EXP', '目標経験値', '目標經驗'],
  ['检测后战斗数', 'Battles since check', 'チェック後の戦闘数', '檢測後戰鬥數'],
  ['还需经验', 'EXP needed', '残り経験値', '還需經驗'],
  ['还需战斗', 'Battles needed', '残り戦闘数', '還需戰鬥'],
  ['预估用时', 'Estimated time', '推定所要時間', '預估用時'],
  ['每日经验', 'Daily EXP', '日別経験値', '每日經驗'],
  ['每日战斗', 'Daily battles', '日別戦闘数', '每日戰鬥'],
  ['每日运行秒数', 'Daily run seconds', '日別稼働秒数', '每日運行秒數'],
  ['尚未检测', 'not checked yet', '未チェック', '尚未檢測'],
  ['图标', 'Icon', 'アイコン', '圖示'],
  ['稀有度', 'Rarity', 'レアリティ', '稀有度'],
  ['项目', 'Project', 'プロジェクト', '項目'],
  ['期数', 'Series', '期', '期數'],
  ['掉落物', 'Drops', 'ドロップ', '掉落物'],
  ['彩', 'UR', 'UR', '彩'],
  ['金', 'SSR', 'SSR', '金'],
  ['紫', 'Elite', 'SR', '紫'],
  ['蓝', 'Rare', 'R', '藍'],
  ['心智/物资收获明细', 'Cognitive chip / coin harvest details', 'メンタルユニット・資金の収穫明細', '心智/物資收穫明細'],
  ['今日总计', 'Today total', '本日の合計', '今日總計'],
  ['本月总计', 'This month total', '今月の合計', '本月總計'],
  ['选定月份总计', 'Selected month total', '選択した月の合計', '選定月份總計'],
  ['任务', 'Task', 'タスク', '任務'],
  ['海域', 'Zone', '海域', '海域'],
  ['大世界掉落明细', 'Operation Siren drop details', 'セイレーン作戦ドロップの明細', '大世界掉落明細'],
  ['短猫掉落收益', 'Meowfficer farming drops', '短猫ドロップ収益', '短貓掉落收益'],
  ['上次记录时间', 'Last recorded', '最終記録時刻', '上次記錄時間'],
  ['有效战斗轮数', 'Valid battle rounds', '有効戦闘ラウンド数', '有效戰鬥輪數'],
  ['平均黄币/轮', 'Avg. supply vouchers/round', '平均作戦補給コイン/ラウンド', '平均黃幣/輪'],
  ['平均金菜/轮', 'Avg. T4 plates/round', '平均金パーツ/ラウンド', '平均金菜/輪'],
  ['平均深渊/轮', 'Avg. abyssal/round', '平均深淵/ラウンド', '平均深淵/輪'],
  ['平均隐秘/轮', 'Avg. obscured/round', '平均隠秘/ラウンド', '平均隱秘/輪'],
  ['危险海域', 'Dangerous zone', '危険海域', '危險海域'],
  ['安全海域', 'Safe zone', '安全海域', '安全海域'],
  ['隐秘海域', 'Obscured zone', '隠秘海域', '隱秘海域'],
  ['深渊海域', 'Abyssal zone', '深淵海域', '深淵海域'],
  ['要塞海域', 'Stronghold zone', '要塞海域', '要塞海域'],
  ['档案海域', 'Archive zone', 'アーカイブ海域', '檔案海域'],
  ['月度Boss海域', 'Monthly boss zone', '月間ボス海域', '月度Boss海域'],
  ['未知海域', 'Unknown zone', '不明な海域', '未知海域'],
  ['仓库物品', 'Inventory items', '倉庫アイテム', '倉庫物品'],
  ['分类', 'Category', '分類', '分類'],
  ['数量', 'Amount', '数量', '數量'],
  ['状态', 'Status', '状態', '狀態'],
  ['未扫描', 'Not scanned', '未スキャン', '未掃描'],
  ['已复核', 'Verified', '確認済み', '已複核'],
  ['未发现', 'Not found', '未発見', '未發現'],
]

// 备注句子：整段相等或作为片段出现在拼接的备注里时替换。
const SENTENCES: readonly Row[] = [
  ['尚未运行仓库统计任务。运行并完成完整扫描后才会更新物品数量。',
    'The inventory statistics task has not run yet. Item counts update after a complete scan.',
    '倉庫統計タスクはまだ実行されていません。完全なスキャンが終わるとアイテム数が更新されます。',
    '尚未執行倉庫統計任務。執行並完成完整掃描後才會更新物品數量。'],
  ['模板目录已更新，当前显示上次扫描结果，请重新运行仓库统计任务。',
    'The template catalog has changed; showing the previous scan. Run the inventory statistics task again.',
    'テンプレート一覧が更新されたため、前回のスキャン結果を表示しています。倉庫統計タスクを再実行してください。',
    '模板目錄已更新，目前顯示上次掃描結果，請重新執行倉庫統計任務。'],
  ['刷新只读取已有快照；未发现的物品显示“未发现”，不把无法确认的数量当成 0。',
    'Refresh only reads existing snapshots; items not found show “Not found”, and unconfirmed counts are never treated as 0.',
    '更新は既存のスナップショットを読むだけです。見つからないアイテムは「未発見」と表示し、確認できない数量を 0 とはみなしません。',
    '重新整理只讀取既有快照；未發現的物品顯示「未發現」，不把無法確認的數量當成 0。'],
  ['记录超过 50,000 条，当前展示最近 50,000 条，请缩短时间范围查看细节。',
    'More than 50,000 records; showing the latest 50,000. Narrow the time range to see details.',
    '記録が 50,000 件を超えたため、最新の 50,000 件を表示しています。詳細は期間を短くして確認してください。',
    '記錄超過 50,000 筆，目前顯示最近 50,000 筆，請縮短時間範圍查看細節。'],
  ['趋势与原始记录只包含成功扫描中已确认的数量；未发现的物品不补为零。',
    'Trends and raw records only include counts confirmed by successful scans; items not found are not filled in as zero.',
    '推移と元の記録には、成功したスキャンで確認された数量だけが含まれます。見つからないアイテムを 0 で埋めることはありません。',
    '趨勢與原始記錄只包含成功掃描中已確認的數量；未發現的物品不補為零。'],
  ['仅统计当前实例的掉落；旧记录缺少实例信息，作为历史共享数据保留，不计入当前实例。',
    'Only drops from this instance are counted; older records without instance info are kept as shared history and not counted here.',
    'このインスタンスのドロップだけを集計します。インスタンス情報のない古い記録は共有履歴として残し、ここには含めません。',
    '僅統計目前實例的掉落；舊記錄缺少實例資訊，作為歷史共享資料保留，不計入目前實例。'],
  ['心智单元与物资不绑期数、各期混着出，所以这里不分期统计（时间范围跟着「汇总周期」走）；清单里没掉过的也留一行，便于对照。图标暂用当前物品模板。',
    'Cognitive chips and coins are not tied to a series and drop from all of them, so they are counted together here (the time range follows “Summary period”). Items that never dropped still get a row for comparison. Icons use the current item templates for now.',
    'メンタルユニットと資金は期に関係なく出るため、ここでは期を分けずに集計します（期間は「集計期間」に従います）。一度も出ていないアイテムも比較用に行を残します。アイコンは現在のアイテムテンプレートを仮に使っています。',
    '心智單元與物資不綁期數、各期混著出，所以這裡不分期統計（時間範圍跟著「彙總週期」走）；清單裡沒掉過的也留一行，便於對照。圖示暫用目前物品模板。'],
  ['这段时间里没有掉落记录。「汇总周期」选今天/本周时窗口很短，改成「选定月份」能看得更多；统计在领奖时自动完成，把「科研截图」设为「保存」或「上传」即可（两者都会统计，区别只是要不要把截图落盘）。',
    'No drop records in this period. “Today” and “This week” are short windows; choose “Selected month” under “Summary period” to see more. Drops are counted automatically when rewards are collected: set “Research screenshot” to “Save” or “Upload” (both count; the only difference is whether screenshots are kept on disk).',
    'この期間のドロップ記録はありません。「集計期間」の「今日」「今週」は短いので、「選択した月」にするとより多く表示されます。集計は報酬受取時に自動で行われます。「科研スクリーンショット」を「保存」か「アップロード」にしてください（どちらも集計され、違いはスクリーンショットをディスクに残すかどうかだけです）。',
    '這段時間裡沒有掉落記錄。「彙總週期」選今日/本週時範圍很短，改成「選定月份」能看得更多；統計在領獎時自動完成，把「科研截圖」設為「儲存」或「上傳」即可（兩者都會統計，差別只是要不要把截圖存到磁碟）。'],
  ['按时间倒序；只列掉了心智单元或物资的记录。',
    'Newest first; only records that dropped cognitive chips or coins.',
    '新しい順。メンタルユニットか資金が出た記録だけを表示します。',
    '依時間倒序；只列掉了心智單元或物資的記錄。'],
  ['记录超过 200 条，只显示最近 200 条。',
    'More than 200 records; showing the latest 200.',
    '記録が 200 件を超えたため、最新の 200 件だけを表示します。',
    '記錄超過 200 筆，只顯示最近 200 筆。'],
  ['每期只统计该期各艘船的图纸与该期的彩装图纸；心智与物资在「心智/物资」里看。图标暂用当前物品模板。清单里本期没掉过的也留一行，便于对照。',
    'Each series only counts its own ship blueprints and its UR gear blueprints; see “Cognitive chips / coins” for chips and coins. Icons use the current item templates for now. Items that never dropped in this series still get a row for comparison.',
    '各期ではその期の艦船設計図とその期の UR 装備設計図だけを集計します。メンタルユニットと資金は「メンタル/資金」で確認してください。アイコンは現在のアイテムテンプレートを仮に使っています。この期に一度も出ていないアイテムも比較用に行を残します。',
    '每期只統計該期各艘船的圖紙與該期的彩裝圖紙；心智與物資在「心智/物資」裡看。圖示暫用目前物品模板。清單裡本期沒掉過的也留一行，便於對照。'],
  ['还没有科研掉落记录。统计在领奖时自动完成：把「科研截图」设为「保存」或「上传」即可（两者都会统计，区别只是要不要把截图落盘）。',
    'No research drop records yet. Drops are counted automatically when rewards are collected: set “Research screenshot” to “Save” or “Upload” (both count; the only difference is whether screenshots are kept on disk).',
    '科研のドロップ記録はまだありません。集計は報酬受取時に自動で行われます。「科研スクリーンショット」を「保存」か「アップロード」にしてください（どちらも集計され、違いはスクリーンショットをディスクに残すかどうかだけです）。',
    '還沒有科研掉落記錄。統計在領獎時自動完成：把「科研截圖」設為「儲存」或「上傳」即可（兩者都會統計，差別只是要不要把截圖存到磁碟）。'],
  ['按时间倒序；只列掉了本期图纸或彩装的记录，那一次只掉心智或物资的不算。',
    'Newest first; only records that dropped this series’ blueprints or UR gear. Runs that only dropped chips or coins are left out.',
    '新しい順。この期の設計図か UR 装備が出た記録だけを表示し、メンタルユニットや資金だけの回は含めません。',
    '依時間倒序；只列掉了本期圖紙或彩裝的記錄，那一次只掉心智或物資的不算。'],
  ['统计金菜（部件T4）、装备研发图纸SSR/UR型、六种金色研发材料、机密/绝密实验计划及特装型突破部件；其他物品照常入库，只是不在这里展示。统计在任务跑完解析掉落时完成：把该任务的「掉落截图」设为保存或上传均可（两者都统计，区别只是要不要把截图落盘）。',
    'Counts T4 plates, SSR/UR gear design plans, the six gold research materials, T2/T3 Ordnance Testing Reports and Specialized Gear Upgrade Parts; other items are stored as usual but not shown here. Drops are counted when a task finishes and its drops are parsed: set that task’s “drop screenshot” to Save or Upload (both count; the only difference is whether screenshots are kept on disk).',
    '金パーツ（T4 パーツ）、SSR/UR 装備設計図、金色の開発素材 6 種、機密/極秘実験計画、特装型突破パーツを集計します。その他のアイテムも通常どおり記録されますが、ここには表示しません。集計はタスク終了後のドロップ解析時に行われます。そのタスクの「ドロップスクリーンショット」を保存かアップロードにしてください（どちらも集計され、違いはスクリーンショットをディスクに残すかどうかだけです）。',
    '統計金菜（部件T4）、裝備研發圖紙SSR/UR型、六種金色研發材料、機密/絕密實驗計畫及特裝型突破部件；其他物品照常入庫，只是不在這裡展示。統計在任務跑完解析掉落時完成：把該任務的「掉落截圖」設為儲存或上傳均可（兩者都統計，差別只是要不要把截圖存到磁碟）。'],
  ['这段时间里没有掉落记录——「汇总周期」选今天/本周时窗口很短，改成「选定月份」能看得更多。',
    'No drop records in this period. “Today” and “This week” are short windows; choose “Selected month” under “Summary period” to see more.',
    'この期間のドロップ記録はありません。「集計期間」の「今日」「今週」は短いので、「選択した月」にするとより多く表示されます。',
    '這段時間裡沒有掉落記錄——「彙總週期」選今日/本週時範圍很短，改成「選定月份」能看得更多。'],
  ['按时间倒序；只列含上述统计物品的掉落记录，其余掉落不入这张表。',
    'Newest first; only drop records containing the items above. Other drops are not listed here.',
    '新しい順。上記の集計対象アイテムを含むドロップ記録だけを表示し、それ以外は載せません。',
    '依時間倒序；只列含上述統計物品的掉落記錄，其餘掉落不入這張表。'],
]

// 带变量的整句。
type Pattern = readonly [RegExp, (match: RegExpMatchArray, language: Target, term: (text: string) => string) => string]
const PATTERNS: readonly Pattern[] = [
  [/^最近完整扫描：(.+)；服务器：(.+)；复核 (\d+) 页。$/, ([, time, server, pages], language) => ({
    'en-US': `Last complete scan: ${time}; server: ${server}; ${pages} pages verified.`,
    'ja-JP': `最後の完全スキャン：${time}、サーバー：${server}、${pages} ページを確認。`,
    'zh-TW': `最近完整掃描：${time}；伺服器：${server}；複核 ${pages} 頁。`,
  })[language]],
  [/^上次检测：(.+)；舰队：(.+)。$/, ([, time, fleet], language, term) => ({
    'en-US': `Last check: ${term(time)}; fleet: ${fleet}.`,
    'ja-JP': `前回のチェック：${term(time)}、艦隊：${fleet}。`,
    'zh-TW': `上次檢測：${term(time)}；艦隊：${fleet}。`,
  })[language]],
  [/^第 (\d+) 期收获明细$/, ([, series], language) => ({
    'en-US': `Series ${series} harvest details`, 'ja-JP': `第 ${series} 期の収穫明細`, 'zh-TW': `第 ${series} 期收穫明細`,
  })[language]],
  [/^第 (\d+) 期在统计区间内没有记录；有记录的期数：(.+)（可把「汇总周期」改成选定月份再看）$/, ([, series, available], language) => {
    const list = [...available.matchAll(/第 (\d+) 期/g)].map(item => item[1])
    return ({
      'en-US': `No records for series ${series} in this period. Series with records: ${list.join(', ')} (try “Selected month” under “Summary period”).`,
      'ja-JP': `第 ${series} 期はこの期間に記録がありません。記録のある期：${list.map(item => `第 ${item} 期`).join('、')}（「集計期間」を「選択した月」にして確認してください）`,
      'zh-TW': `第 ${series} 期在統計區間內沒有記錄；有記錄的期數：${list.map(item => `第 ${item} 期`).join('、')}（可把「彙總週期」改成選定月份再看）`,
    })[language]
  }],
  [/^(\d+)小时(\d+)分钟$/, ([, hours, minutes], language) => ({
    'en-US': `${hours} h ${minutes} min`, 'ja-JP': `${hours}時間${minutes}分`, 'zh-TW': `${hours}小時${minutes}分鐘`,
  })[language]],
  [/^(\d+)分钟$/, ([, minutes], language) => ({'en-US': `${minutes} min`, 'ja-JP': `${minutes}分`, 'zh-TW': `${minutes}分鐘`})[language]],
  [/^(\S+海域)(?: (.+?))?(?:（侵蚀(\d+)）)?$/, ([, zone, name, hazard], language, term) => {
    const head = [term(zone), name].filter(Boolean).join(' ')
    if (!hazard) return head
    return ({'en-US': `${head} (hazard ${hazard})`, 'ja-JP': `${head}（侵食${hazard}）`, 'zh-TW': `${head}（侵蝕${hazard}）`})[language]
  }],
  [/^购买 (.+) × (\d+)$/, ([, item, count], language, term) => ({
    'en-US': `Bought ${term(item)} × ${count}`, 'ja-JP': `${term(item)} × ${count} を購入`, 'zh-TW': `購買 ${term(item)} × ${count}`,
  })[language]],
  [/^建造 (.+) × (\d+)$/, ([, pool, count], language, term) => ({
    'en-US': `Built ${term(pool)} × ${count}`, 'ja-JP': `${term(pool)} × ${count} を建造`, 'zh-TW': `建造 ${term(pool)} × ${count}`,
  })[language]],
  [/^启动科研 (.+)$/, ([, project], language, term) => ({
    'en-US': `Started research ${term(project)}`, 'ja-JP': `科研 ${term(project)} を開始`, 'zh-TW': `啟動科研 ${term(project)}`,
  })[language]],
]

const columnOf: Record<Target, number> = {'en-US': 1, 'ja-JP': 2, 'zh-TW': 3}
const termMaps = new Map<Target, Map<string, string>>()
function termMap(language: Target) {
  let map = termMaps.get(language)
  if (!map) {
    map = new Map([...TERMS, ...SENTENCES].map(row => [row[0], row[columnOf[language]]]))
    termMaps.set(language, map)
  }
  return map
}
// 长句优先，避免短句先替换掉长句的一部分。
const sentencesByLength = [...SENTENCES].sort((a, b) => b[0].length - a[0].length)

function isTarget(language: Language): language is Target {
  return language in columnOf
}

/**
 * 把一段统计文本翻译成指定语言。
 *
 * 依次尝试：固定词句、后端对照表、带变量的句式、按顿号拼接的掉落清单、拼接备注里的已知句子；都不匹配时原样返回。
 */
export function translateStatText(language: Language, text: string, glossary: StatGlossary = {}): string {
  if (!isTarget(language) || !text) return text
  const map = termMap(language)
  const term = (value: string): string => map.get(value) ?? glossary[value]?.[language] ?? value
  const direct = map.get(text) ?? glossary[text]?.[language]
  if (direct !== undefined) return direct
  for (const [pattern, render] of PATTERNS) {
    const match = text.match(pattern)
    if (match) return render(match, language, term)
  }
  // 掉落清单形如「钛合金 x2、HBX炸药 x1」
  if (text.includes('、') && !/[。；]/.test(text)) {
    const parts = text.split('、').map(part => {
      const match = part.match(/^(.*?)\s*x(\d+)$/)
      return match ? `${term(match[1])} x${match[2]}` : term(part)
    })
    return parts.join(language === 'en-US' ? ', ' : '、')
  }
  let result = text
  for (const row of sentencesByLength) {
    if (result.includes(row[0])) result = result.split(row[0]).join(row[columnOf[language]])
  }
  return result
}

/** 返回翻译某一语言的函数，供组件一次性取用。 */
export function statTextTranslator(language: Language, glossary?: StatGlossary) {
  return (text: string) => translateStatText(language, text, glossary)
}

function localizeTable(table: StatTable, tr: (text: string) => string): StatTable {
  return {
    ...table, title: tr(table.title), columns: table.columns.map(tr), note: table.note && tr(table.note),
    // 模板图标值（research:、opsi:、storage:）与数字保持原样。
    rows: table.rows.map(row => row.map(value => typeof value === 'string' && !/^[a-z]+:/.test(value) ? tr(value) : value)),
  }
}

// 英文单位与数字之间留空格（「0 battles」），符号单位除外。
function unitText(language: Target, unit: string) {
  return language === 'en-US' && unit && !/^[\s/%]/.test(unit) ? ` ${unit}` : unit
}

/** 把统计报表的显示文本翻译成当前语言；数据、键与图标值不变。 */
export function localizeReport(report: StatisticsReport, language: Language): StatisticsReport {
  if (!isTarget(language)) return report
  const tr = statTextTranslator(language, report.glossary)
  return {
    ...report,
    metrics: report.metrics.map(item => ({...item, label: tr(item.label), unit: unitText(language, tr(item.unit))})),
    series: report.series.map(item => ({...item, label: tr(item.label)})),
    tables: report.tables.map(table => localizeTable(table, tr)),
    notes: report.notes.map(tr),
    taskOptions: report.taskOptions?.map(item => ({...item, label: tr(item.label)})),
  }
}

/** 资源管理的物品名、分组与用途翻译成当前语言；键与数值不变。 */
export function localizeFlowReport(report: ResourceFlowReport, language: Language): ResourceFlowReport {
  if (!isTarget(language)) return report
  const tr = statTextTranslator(language, report.glossary)
  return {
    ...report,
    resources: report.resources.map(item => ({...item, label: tr(item.label), group: tr(item.group)})),
    flows: report.flows.map(item => ({...item, operation: tr(item.operation)})),
    entries: report.entries.map(item => ({...item, operation: tr(item.operation)})),
  }
}

/**
 * 给按中文名查图标的表补上各语言的译名，翻译后的标签仍能找到图标。
 *
 * @param icons 以中文名为键的图标表。
 */
export function withTranslatedKeys<T>(icons: Record<string, T>): Record<string, T> {
  const result = {...icons}
  for (const row of TERMS) {
    if (!(row[0] in icons)) continue
    for (const index of [1, 2, 3]) if (row[index] && !(row[index] in result)) result[row[index]] = icons[row[0]]
  }
  return result
}
