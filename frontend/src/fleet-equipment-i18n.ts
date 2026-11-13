/**
 * @fileoverview 换船装备功能的界面文案（zh-CN/zh-TW/en-US/ja-JP）；键集以 zh-CN 为准，其余语言经 typeof 逐键对齐。
 */
export const equipmentZhCN = {
  'fleetEquipment.title': '换船装备', 'fleetEquipment.enable': '启用自动换装备', 'fleetEquipment.save': '保存装备码',
  'fleetEquipment.help': '仅联动智能换船，默认关闭。确定来源与舰位后，先清空所有待换出舰船的装备；换船全部完成后，按换入舰船详情左上角的舰种应用对应装备码，最后回到主界面继续任务。',
  'fleetEquipment.skip': '每队前、后排分别按舰位排序，同舰种依次使用第1、2、3格；未换船的同舰种也计入顺序。对应格未填则保留换入舰船当前装备，不重复使用第一格。旧单码保留在第一格。',
  'fleetEquipment.support': '目前支持国服舰种识别，装备码输入复用紧急委托的控制方式要求。开关在每次出击前读取，已卸装的本轮会先完成装备处理。',
  'fleetEquipment.code': '装备码', 'fleetEquipment.placeholder': '未填写：跳过此顺序位', 'fleetEquipment.saved': '换船装备设置已保存',
  'fleetEquipment.pending': '还有 {number} 个舰位未完成换装。开启功能后，下次任务先按实际舰船补完；关闭时保持原换船行为。',
  'fleetEquipment.invalid': '装备码配置包含未知舰种或无效格式',
  'fleetEquipment.DD': '驱逐舰', 'fleetEquipment.CL': '轻巡洋舰', 'fleetEquipment.CA': '重巡洋舰',
  'fleetEquipment.CB': '大型巡洋舰（超巡）', 'fleetEquipment.BC': '战列巡洋舰', 'fleetEquipment.BB': '战列舰',
  'fleetEquipment.CVL': '轻型航空母舰', 'fleetEquipment.CV': '航空母舰', 'fleetEquipment.BBV': '航空战列舰',
  'fleetEquipment.SS': '潜艇', 'fleetEquipment.SSV': '潜水空母', 'fleetEquipment.AR': '维修舰',
  'fleetEquipment.BM': '重炮舰', 'fleetEquipment.AE': '运输舰', 'fleetEquipment.IX': '风帆舰',
}
export const equipmentZhTW: typeof equipmentZhCN = {
  'fleetEquipment.title': '換船裝備', 'fleetEquipment.enable': '啟用自動更換裝備', 'fleetEquipment.save': '儲存裝備碼',
  'fleetEquipment.help': '僅連動智慧換船，預設關閉。確定來源與艦位後，先卸下所有待換出艦船的裝備；全部換船完成後，依換入艦船詳情左上角的艦種套用裝備碼，最後回到主畫面繼續任務。',
  'fleetEquipment.skip': '每隊前、後排各自依艦位排序，同艦種依序使用第1、2、3格；未換船的同艦種也計入順序。對應格未填時保留換入艦船目前裝備，不重用第一格。舊單碼保留於第一格。',
  'fleetEquipment.support': '目前支援國服艦種辨識，裝備碼輸入沿用緊急委託的控制方式要求。開關於每次出擊前讀取，已卸裝的該輪會先完成裝備處理。',
  'fleetEquipment.code': '裝備碼', 'fleetEquipment.placeholder': '未填寫：略過此順序位', 'fleetEquipment.saved': '換船裝備設定已儲存',
  'fleetEquipment.pending': '還有 {number} 個艦位未完成換裝。啟用後，下次任務會先依實際艦船補完；關閉時維持原換船行為。',
  'fleetEquipment.invalid': '裝備碼設定包含未知艦種或無效格式',
  'fleetEquipment.DD': '驅逐艦', 'fleetEquipment.CL': '輕巡洋艦', 'fleetEquipment.CA': '重巡洋艦',
  'fleetEquipment.CB': '大型巡洋艦（超巡）', 'fleetEquipment.BC': '戰列巡洋艦', 'fleetEquipment.BB': '戰列艦',
  'fleetEquipment.CVL': '輕型航空母艦', 'fleetEquipment.CV': '航空母艦', 'fleetEquipment.BBV': '航空戰列艦',
  'fleetEquipment.SS': '潛艇', 'fleetEquipment.SSV': '潛水空母', 'fleetEquipment.AR': '維修艦',
  'fleetEquipment.BM': '重砲艦', 'fleetEquipment.AE': '運輸艦', 'fleetEquipment.IX': '風帆艦',
}
export const equipmentEnUS: typeof equipmentZhCN = {
  'fleetEquipment.title': 'Rotation equipment', 'fleetEquipment.enable': 'Enable automatic equipment', 'fleetEquipment.save': 'Save equipment codes',
  'fleetEquipment.help': 'Used with smart ship rotation; off by default. After choosing the reserve and slots, remove equipment from all outgoing ships. After all swaps, recognize each incoming ship type and apply its equipment code, then return home and resume the task.',
  'fleetEquipment.skip': 'Within each fleet, count each type by slot separately in the main and vanguard rows, including unchanged ships. Use codes 1, 2, then 3. An empty position keeps the incoming ship’s current equipment; it never falls back to code 1. Old single codes stay in the first field.',
  'fleetEquipment.support': 'Ship type recognition currently supports the CN server. Code input uses the same control methods as emergency commissions. The switch is read before each sortie; equipment processing already started will finish.',
  'fleetEquipment.code': 'Equipment code', 'fleetEquipment.placeholder': 'Empty: skip this occurrence', 'fleetEquipment.saved': 'Equipment settings saved',
  'fleetEquipment.pending': '{number} slots still need equipment processing. When enabled, the next task handles the actual ships first. When disabled, the original rotation behavior is retained.',
  'fleetEquipment.invalid': 'Equipment codes contain an unknown ship type or an invalid format',
  'fleetEquipment.DD': 'Destroyer', 'fleetEquipment.CL': 'Light cruiser', 'fleetEquipment.CA': 'Heavy cruiser',
  'fleetEquipment.CB': 'Large cruiser', 'fleetEquipment.BC': 'Battlecruiser', 'fleetEquipment.BB': 'Battleship',
  'fleetEquipment.CVL': 'Light carrier', 'fleetEquipment.CV': 'Aircraft carrier', 'fleetEquipment.BBV': 'Aviation battleship',
  'fleetEquipment.SS': 'Submarine', 'fleetEquipment.SSV': 'Submarine carrier', 'fleetEquipment.AR': 'Repair ship',
  'fleetEquipment.BM': 'Monitor', 'fleetEquipment.AE': 'Munition ship', 'fleetEquipment.IX': 'Sailing frigate',
}
export const equipmentJaJP: typeof equipmentZhCN = {
  'fleetEquipment.title': '交代時の装備', 'fleetEquipment.enable': '自動装備変更を有効化', 'fleetEquipment.save': '装備コードを保存',
  'fleetEquipment.help': '自動艦船交代と連動し、初期設定は無効です。交代元と配置を決定後、交代対象の旧艦船をすべて装備解除します。全交代後に新艦船の艦種を認識して装備コードを適用し、母港に戻って任務を再開します。',
  'fleetEquipment.skip': '各艦隊の主力・前衛ごとに配置順で同艦種を数え、コード1、2、3を順に使います。交代しない艦船も数えます。該当欄が空なら現在の装備を保持し、コード1を再利用しません。旧コードは第1欄に保持します。',
  'fleetEquipment.support': '艦種認識は現在中国版に対応しています。コード入力は緊急委託と同じ操作方式を使用します。設定は各出撃前に読み込み、開始済みの装備処理は完了させます。',
  'fleetEquipment.code': '装備コード', 'fleetEquipment.placeholder': '未入力：この順番をスキップ', 'fleetEquipment.saved': '装備設定を保存しました',
  'fleetEquipment.pending': '未完了の装備変更が{number}配置あります。有効時は次の任務で実際の艦船から先に処理します。無効時は従来の交代動作を維持します。',
  'fleetEquipment.invalid': '装備設定に不明な艦種または無効な形式が含まれています',
  'fleetEquipment.DD': '駆逐艦', 'fleetEquipment.CL': '軽巡洋艦', 'fleetEquipment.CA': '重巡洋艦',
  'fleetEquipment.CB': '超巡洋艦', 'fleetEquipment.BC': '巡洋戦艦', 'fleetEquipment.BB': '戦艦',
  'fleetEquipment.CVL': '軽空母', 'fleetEquipment.CV': '空母', 'fleetEquipment.BBV': '航空戦艦',
  'fleetEquipment.SS': '潜水艦', 'fleetEquipment.SSV': '潜水空母', 'fleetEquipment.AR': '工作艦',
  'fleetEquipment.BM': '砲艦', 'fleetEquipment.AE': '運送艦', 'fleetEquipment.IX': '風帆艦',
}
