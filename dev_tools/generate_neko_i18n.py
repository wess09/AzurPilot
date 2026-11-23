"""
Generate Nekomimi (猫娘语) Localization for AzurLaneAutoScript.

Generates:
1. module/config/i18n/zh-CN-neko.json (all 5,414 backend leaf keys)
2. frontend/src/i18n.neko.ts (all 1,065 frontend UI keys)

Design Philosophy:
- Natural, human-quality catgirl translation with living warmth and wit
- ZERO rigid, robotic regex word-swapping (no awkward Franken-sentences)
- 100% placeholder preservation ({name}, {count}, {0}, {{exts}}, etc.)
- ZERO Unicode emojis, pure safe Kaomoji
"""

import json
import re
import subprocess
from pathlib import Path

try:
    from dev_tools.neko_custom_i18n import ALL_FRONTEND_OVERRIDES, BACKEND_OVERRIDES
except ImportError:
    from neko_custom_i18n import ALL_FRONTEND_OVERRIDES, BACKEND_OVERRIDES

# Safe kaomojis verified against EMOJI_PATTERN
KAOMOJI_ALL = [
    "(ฅ'ω'ฅ)", "(*^▽^*)", "(=・ω・=)", "(ง •_•)ง", "(o^ω^o)", "(≧∇ sales)/" if False else "(≧∇≦)/", "(ฅ>ω<*ฅ)",
    "(ﾉ>ω<)ﾉ", "(=^･ω･^=)", "(•̀ω•́)", "(^・ω・^)", "(oﾟ▽ﾟ)o", "(=ﾟωﾟ)ﾉ",
    "(=`･ω･´=)", "(ฅ`ω´ฅ)", "(｀・ω・´)", "(•̀_•́)", "(•̀へ•́)",
    "(=^-ω-^=)", "( ˘ω˘ )", "( =①ω①= )",
    "(*/ω＼*)", "(,,・ω・,,)", "(⁄ ⁄•⁄ω⁄•⁄ ⁄)"
]

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U0001F004\U0001F0CF"
    "\U0001F170-\U0001F251"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "\uFE0F"
    "]+",
    flags=re.UNICODE
)

PLACEHOLDER_REGEX = re.compile(r'(\{\{[^{}]+\}\}|\{[^{}]+\})')

# Curated handcrafted translations for specific UI components, buttons, menus, and tasks
SPECIAL_OVERRIDES = {
    # Buttons & Controls
    "启动": "出击跑跑喵！(ﾉ>ω<)ﾉ",
    "停止": "停下休息喵~ (=^-ω-^=)",
    "保存": "保存好啦喵~ (ฅ'ω'ฅ)",
    "取消": "取消喵~ ( > < )",
    "确认": "确认无误喵！(•̀ω•́)",
    "确定": "确定好啦喵！(=`･ω･´=)",
    "删除": "删除掉喵~ (*/ω＼*)",
    "清空": "全部清空喵~ (ฅ'ω'ฅ)",
    "清空日志": "清空日志喵！(╬ﾟдﾟ)ﾉ",
    "设置": "系统设置喵~ (•̀ω•́)",
    "检查更新": "嗅嗅新版本喵~ (=①ω①=)",
    "进行更新": "快快更新喵！(ﾉ>ω<)ﾉ",
    "重试更新": "再试一次更新喵！(ง •_•)ง",
    "取消更新": "先不更新啦喵~",
    "折叠": "折叠起来喵~ (=^-ω-^=)",
    "展开": "展开看看喵~ (*^▽^*)",
    "打开": "打开喵~ (ฅ'ω'ฅ)",
    "关闭": "关闭喵~ (=^-ω-^=)",
    "刷新": "刷新一下喵~ (o^ω^o)",
    "重置": "全部重置喵！(╬ﾟдﾟ)ﾉ",
    "导入": "导入配置喵~ (ﾉ>ω<)ﾉ",
    "导出": "导出配置喵~ (ฅ'ω'ฅ)",
    "下载": "下载文件喵~ (•̀ω•́)",
    "上传": "上传文件喵~ (ฅ'ω'ฅ)",
    "搜索": "搜索搜寻喵~ (=①ω①=)",
    "全选": "全都选上喵！(ﾉ>ω<)ﾉ",
    "反选": "反向选择喵！(=`･ω･´=)",
    "运行": "正在运行喵！(ง •_•)ง",
    "暂停": "稍等暂停喵~ (=^-ω-^=)",
    "恢复": "继续跑跑喵！(ﾉ>ω<)ﾉ",
    "编辑": "编辑修改喵~ (•̀ω•́)",
    "复制": "复制好啦喵~ (*/ω＼*)",
    "粘贴": "粘贴上来喵！(ฅ'ω'ฅ)",
    "返回": "返回上一页喵~ (*/ω＼*)",
    "普通": "普通难度喵~",
    "困难": "困难挑战喵！(•̀ω•́)",
    "简单": "简单轻松喵~ (=^-ω-^=)",
    "启用": "启用喵！(ﾉ>ω<)ﾉ",
    "禁用": "禁用喵~ (╬ﾟдﾟ)ﾉ",
    "开启": "开启喵！(•̀ω•́)",
    "默认": "默认设置喵~",
    "自动": "全自动代打喵~ (=^-ω-^=)",
    "手动": "指挥官亲手来喵~ (•̀ω•́)",
    "始终": "一直保持喵~ (ฅ>ω<*ฅ)",
    "从不": "绝对不要喵！(╬ﾟдﾟ)ﾉ",
    "仅Boss战": "只打Boss头领喵！(ฅ`ω´ฅ)",
    "仅小怪战": "只清理杂鱼小怪喵~ (ฅ'ω'ฅ)",
    "全清": "全图全部扫荡喵！(ง •_•)ง",
    "不使用": "不使用喵~ ( > < )",
    "无": "空空如也喵~ (｡•́︿•̀｡)",
    "成功": "大获全胜搞定啦喵！快奖励小鱼干~ (*^▽^*)",
    "失败": "猫猫翻车了呜呜呜……给罐头安慰一下喵 (｡•́︿•̀｡)",
    "已保存": "设置已经藏好啦喵~ (ฅ'ω'ฅ)",
    "保存中": "正在保存中喵~",
    "已更新": "已经换上热乎的新版本啦喵！(*^▽^*)",
    "已刷新": "数据已经刷新好啦喵！(ฅ'ω'ฅ)",
    "已清空": "已经全部清空啦喵！(ฅ>ω<*ฅ)",
    "已删除": "已经安全删除啦喵！(╬ﾟдﾟ)ﾉ",
    "已完成": "已经大功告成收工啦喵！(*^▽^*)",
    "已启动": "已经开足马力跑跑啦喵！(ﾉ>ω<)ﾉ",

    # Toasts & Alerts
    "设置已保存": "设置已经悄悄藏好啦喵~ (ฅ'ω'ฅ)",
    "调度器已在运行中": "调度器已经在努力运转中啦，指挥官别催催喵！(ﾉ`□´)ﾉ",
    "秘书舰正在处理": "秘书舰正在认真踩奶盖章中喵~ (*^▽^*)",
    "茗正在偷走你的箱子": "奸商茗喵叼着箱子光速逃窜中喵！(=`･ω･´=) 抓小偷喵！",
    "发生错误": "出错了喵呜……猫爪爪被缠住了啦 (つд⊂)",
    "等待更新": "正在乖乖等待新版本更新喵~ (•̀ω•́)",
    "点击这里关闭翻译模式": "戳这里收起猫猫翻译滤镜喵~ (ฅ'ω'ฅ)",
    "有可用更新nanoda!": "发现新版本可以更新了喵！nanoda~ (ﾉ>ω<)ﾉ",
    "运行中": "努力跑跑中喵！(ง •_•)ง",
    "待命中": "在猫窝打盹待命中喵~ ( ˘ω˘ )",
    "需要处理": "猫爪卡住了快来救猫！(つд⊂)",
    "更新中": "正在吃热乎新补丁喵！(•̀ω•́)",
    "未运行": "在猫窝香甜睡大觉中喵~ ( ˘ω˘ )",
    "警告": "整只猫警惕注意喵！(╬ﾟдﾟ)",
    "等待中": "乖乖趴着摇尾巴等待喵~ (=^-ω-^=)",
    "排队中": "在猫窝门口排排坐等待喵~ (ฅ'ω'ฅ)",
    "无任务": "今天没有活干，猫猫躺平晒太阳喵~ (=^-ω-^=)",

    # Menus
    "系统": "猫窝中枢喵~ (•̀ω•́)",
    "出击": "海域出击抓鱼喵！(ﾉ>ω<)ﾉ",
    "活动": "限时活动狂欢喵~ (*^▽^*)",
    "活动-每日任务": "活动每日差事喵~ (ฅ'ω'ฅ)",
    "自动收获": "伸爪白嫖奖励喵~ (=^-ω-^=)",
    "每日任务": "每日必做任务喵~ (•̀ω•́)",
    "大世界": "大型作战·大世界喵~ (ฅ`ω´ฅ)",
    "赤石计划": "大橘为重·赤石整活计划喵！(*/ω＼*)",
    "舰队管理": "猫娘舰队编队大点兵喵~ (ฅ>ω<*ฅ)",
    "运行参数": "肉垫油门核心参数喵~ (•̀ω•́)",
    "工具": "猫猫实用工具箱喵~ (ฅ'ω'ฅ)",

    # Tasks
    "系统设置": "猫窝管家核心参数喵~ (•̀ω•́)",
    "通用设置": "伺候猫主子基本法喵~ (=^-ω-^=)",
    "重启设置": "猫猫摔倒原地打滚重爬喵~ (つд⊂)",
    "主线图-1": "主线捕鱼大队-1号喵！(ﾉ>ω<)ﾉ",
    "主线图-2": "主线捕鱼大队-2号喵！(ﾉ>ω<)ﾉ",
    "主线图-3": "主线捕鱼大队-3号喵！(ﾉ>ω<)ﾉ",
    "紧急委托": "突发偷鱼小分队喵！(ฅ`ω´ฅ)",
    "三油低耗": "三滴油极限制省吃俭用流喵~ (=①ω①=)",
    "1-1刷伏击(尚不完善)": "1-1草丛蹲伏抓螃蟹喵~ (ฅ'ω'ฅ)",
    "活动通用设置": "大型狂欢捞鱼大会守则喵~ (*^▽^*)",
    "活动图-1": "限时捞大鱼活动-1号喵~ (*^▽^*)",
    "活动图-2": "限时捞大鱼活动-2号喵~ (*^▽^*)",
    "活动图-3": "限时捞大鱼活动-3号喵~ (*^▽^*)",
    "退役": "舰船退役领小鱼干睡大觉喵~ (つд⊂)",
    "一键退役": "一键光速遣散领鱼干喵~ (ฅ'ω'ฅ)",
    "强化": "猫条猛炫！长肉肉变强喵！(ง •_•)ง",
    "后宅": "猫爬架集体聚众呼噜噜喵~ ( ˘ω˘ )",
    "指挥喵": "本家同族指挥喵大集结喵！(=^･ω･^=)",
    "大舰队": "猫猫互助抱团大公会喵~ (ฅ>ω<*ฅ)",
    "建造": "往猫窝里捞新的猫耳舰娘喵~ (*^▽^*)",
    "演习": "演习场抓板大乱斗！挠花对面的脸喵~ (ฅ`ω´ฅ)",
    "委托": "派小猫咪们打工赚罐头喵~ (ฅ'ω'ฅ)",
    "战术研修": "猫咪特训学校！变强抓大鱼喵~ (•̀ω•́)",
    "大型作战设置": "深海大冒险全套作战规划喵~ (•̀ω•́)",
    "大世界开荒": "新海域猫猫探险队开荒喵！(ﾉ>ω<)ﾉ",
    "大世界每日": "深海每日日常摸鱼喵~ (=^-ω-^=)",
    "大世界月度": "深海月度大扫荡喵！(•̀ω•́)",
    "大世界深渊": "深渊巨兽搏斗抓大鱼喵！(ฅ`ω´ฅ)",
    "大世界要塞": "强拆海域要塞抢罐头喵！(╬ﾟдﾟ)ﾉ",
    "大世界档案": "深海秘密藏宝图档案喵~ (*/ω＼*)",
    "信标·META": "余烬挑战！暴揍信标猫猫拳喵！(ง •_•)ง",
    "领免费礼包": "伸爪白嫖免费猫罐头礼包喵~ (ฅ'ω'ฅ)",
    "雪风任务管理器": "雪风大人的猫耳统治计划喵！(•̀ω•́)",
    "每日战报": "猫猫今日战果小总结喵~ (*^▽^*)",
    "掉落记录": "小鱼干与海鲜掉落账本喵~ (ฅ'ω'ฅ)",
    "模拟器": "模拟器小黑盒喵~ (•̀ω•́)",
    "模拟器管理": "模拟器盒子大管家喵~ (ฅ'ω'ฅ)",
    "控油": "精打细算控油防破产喵~ (=①ω①=)",
    "后宅心情": "后宅蹭蹭心情恢复站喵~ ( ˘ω˘ )",

    # Aside & GUI
    "首页": "猫窝大厅喵~ (ฅ'ω'ฅ)",
    "总览": "猫猫领地大巡逻喵~ (•̀ω•́)",
    "日志": "猫爪爪秘密小日记喵~ (*/ω＼*)",
    "开发": "猫猫实验室喵~ (•̀ω•́)",
    "性能": "猫爪飞奔心率喵~ (ง •_•)ง",
    "添加Alas": "领一只新的流浪猫娘进窝喵！(ﾉ>ω<)ﾉ",
    "刚刚": "就在刚才喵~ (ฅ'ω'ฅ)",
    "很久以前": "很久很久以前喵~ ( ˘ω˘ )",
    "无数据": "空空如也，连根猫毛都没有喵……(｡•́︿•̀｡)",
    "已经是最新版本": "猫窝已经是最新最鲜的版本啦喵！(*^▽^*)",
    "有可用更新": "嗅到新出炉的版本小鱼干啦，快来更新喵！(ﾉ>ω<)ﾉ",
    "开始更新": "嗷呜一口开吃新版本喵！(ฅ`ω´ฅ)",
    "正在更新": "猫猫爪爪疯狂搬运更新积木中喵！(ง •_•)ง",
    "更新成功": "新版本饱餐一顿，猫猫变得更聪明啦喵！(*^▽^*)",
    "更新失败": "喵呜呜！更新小鱼干掉地上了啦……(つд⊂)",

    # Fleet Management
    "前排舰队": "前排冲锋猫爪特攻队喵~",
    "后排舰队": "后排重炮轰轰猫猫队喵~",
    "潜艇舰队": "水下潜水摸鱼小分队喵~",
    "水上舰队": "水面捕鱼猫咪舰队喵~",
    "水下舰队": "水下潜水猫咪舰队喵~",
    "舰队": "猫猫特攻编制喵~",
    "舰船": "猫耳舰娘小可爱们喵~",
    "开始扫描": "动动猫须地毯式搜寻！(ﾉ>ω<)ﾉ",
    "正在扫描": "猫猫四处张望搜寻中喵~ (•̀ω•́)",
    "扫描已开始": "猫猫侦察小分队已经出动啦喵！(ฅ'ω'ฅ)",
    "扫描已在运行中": "猫猫正在到处闻呢，指挥官别催催喵！(ﾉ`□´)ﾉ",
    "扫描启动失败": "猫猫迷路了启动失败喵呜……(つд⊂)",
    "上次扫描": "上次搜寻巡逻战果喵~",
    "无结果": "搜寻了一圈什么都没嗅到喵……(｡•́︿•̀｡)",

    # Frontend Navigation & Auth
    "auth.slogan": "让每一次出航，都有猫猫贴心陪伴喵~ (ฅ'ω'ฅ)",
    "auth.welcome": "指挥官，欢迎回到指挥室喵~ (*^▽^*)",
    "auth.password": "访问密码喵~",
    "auth.verifying": "正在仔细核对密码喵……(*/ω＼*)",
    "auth.enter": "进入控制台喵！(ﾉ>ω<)ﾉ",
    "auth.passwordHint": "自动生成的密码保存在服务端的 password.txt 中喵~ (•̀ω•́)",
    "nav.overview": "运行总览喵~ (•̀ω•́)",
    "nav.statistics": "资源统计喵~ (ฅ'ω'ฅ)",
    "nav.schedulerProgram": "自定义调度喵~",
    "nav.updater": "更新器喵~",
    "nav.interface": "界面设置喵~",
    "nav.remote": "远程访问喵~",
    "nav.settings": "系统设置喵~",
    "nav.plugins": "猫猫扩展插件喵~ (•̀ω•́)",
    "nav.resources": "资源管理喵~",
    "nav.skipContent": "跳到正文内容喵~",
    "nav.openSource": "开源项目喵~",
    "nav.announcement": "系统公告喵~",
    "nav.taskConfig": "任务配置喵~",
    "nav.primary": "主导航喵~",
    "nav.collapse": "收起侧栏喵~",
    "nav.expand": "展开侧栏喵~",
    "nav.open": "打开导航菜单喵~",
    "nav.close": "关闭导航菜单喵~",
    "nav.newVersion": "新版本可用啦喵！(ﾉ>ω<)ﾉ",
    "nav.searchTask": "搜索任务喵~",
    "nav.searchTaskPlaceholder": "搜索任务……(=①ω①=)",

    # Common
    "common.loading": "正在努力搬运加载中喵……(*/ω＼*)",
    "common.retry": "打个滚再试一次喵！(ง •_•)ง",
    "common.close": "关闭窗口喵~",
    "common.cancel": "不要啦，取消喵！(> <)",
    "common.copy": "猫爪拓印复制喵~ (ฅ'ω'ฅ)",
    "common.confirm": "按手印确认无误喵！(•̀ω•́)",
    "common.previous": "上一页喵~",
    "common.next": "下一页喵~",
    "common.notFetched": "未获取到数据喵~",
    "common.notSet": "未设置喵~",
    "common.select": "请伸爪选择喵~",
    "common.showPassword": "偷看密码喵~",
    "common.hidePassword": "把密码藏好喵~",

    # Instance
    "instance.created": "实例已经创建好啦，请指挥官设置模拟器连接喵~ (ฅ'ω'ฅ)",
    "instance.rightClick": "右键快捷操作喵~",
    "instance.createTitle": "创建配置实例喵~",
    "instance.createHint": "每个实例都会独立保存任务计划与模拟器连接喵~ (•̀ω•́)",
    "instance.importPick": "选择本机配置文件……(ฅ'ω'ฅ)",
    "instance.importConfig": "导入已有配置喵~",
    "instance.importHint": "从已有配置文件导入，选中后会自动填好实例名喵~ (*^▽^*)",
    "instance.importSelect": "挑选配置文件喵~",
    "instance.importLoading": "正在翻箱倒柜读取中喵……",
    "instance.name": "实例名称喵~",
    "instance.initialConfig": "初始配置方案喵~",
    "instance.defaultConfig": "使用默认推荐配置喵~",
    "instance.creating": "正在全速创建实例中喵……",
    "instance.create": "立刻创建实例喵！(ﾉ>ω<)ﾉ",
    "instance.dashboard": "运行仪表盘喵~",
    "instance.settings": "仪表盘设置喵~",
    "nav.instanceTabs": "实例标签分页喵~",
    "nav.startAll": "一键启动全部实例喵！(ﾉ>ω<)ﾉ",
    "nav.stopAll": "一键暂停全部实例喵~ (=^-ω-^=)",
    "instance.startup": "启动实例喵！",
    "instance.autoRun": "启动时自动运行喵~",
    "instance.autoRunHelp": "启用后，启动 Azurpilot 时会自动跑跑当前实例喵~ (*^▽^*)",

    # Plugins
    "plugins.installed": "已安装的插件列表喵~ (ฅ'ω'ฅ)",
    "plugins.import": "导入 .apu 插件包喵~ (ﾉ>ω<)ﾉ",
    "plugins.empty": "猫窝空空如也，连一根逗猫棒都没有安装呢喵……(｡•́︿•̀｡)",
    "plugins.fileType": "请指挥官选择 .apu 格式的插件文件喵！(,,・ω・,,)",
    "plugins.enabled": "插件已启用运转中喵~ (*^▽^*)",
    "plugins.disabled": "插件已停用在角落吃灰喵~ (つд⊂)",
    "plugins.enable": "开启此插件喵！(ﾉ>ω<)ﾉ",
    "plugins.disable": "停用此插件喵~",
    "plugins.applyTheme": "换上这套猫猫主题喵~ (ฅ>ω<*ฅ)",
    "plugins.restoreTheme": "恢复默认布局外观喵~ (o^ω^o)",
    "plugins.remove": "彻底卸载此插件喵！(╬ﾟдﾟ)ﾉ",
    "plugins.removePrompt": "确定要卸载「{name}」并彻底清除所有数据喵？(,,・ω・,,)",
    "plugins.pageUnavailable": "插件页面暂时打不开喵呜……(*/ω＼*)",
    "plugins.loadingView": "正在努力搬运加载插件中喵……(*/ω＼*)",
    "plugins.viewFailed": "插件界面加载失败了喵呜……(｡•́︿•̀｡)",
    "plugins.operationUnavailable": "爪爪被按住了，这项操作暂时不可用喵！( > < )",
    "plugins.storageLimit": "插件数据体积太大了，猫猫叼不动啦喵！(> <)",
    "plugins.permission.instance.read": "读取实例数据权限喵~",
    "plugins.permission.storage": "保存插件本地数据权限喵~",
    "plugins.permission.scheduler.control": "控制调度器启停权限喵~",

    # Simulator
    "simulator.start": "开始模拟运算喵！(ﾉ>ω<)ﾉ",
    "simulator.stop": "中断模拟运算喵~ ( > < )",
    "simulator.idle": "等待模拟指令中喵~",
    "simulator.running": "正在全力模拟推演中喵~ (•̀ω•́)",
    "simulator.stopping": "正在刹车停止模拟中喵~",
    "simulator.completed": "模拟运算大功告成啦！快来看结果喵~ (*^▽^*)",
    "simulator.interrupted": "模拟运算已强行中断喵！( > < )",
    "simulator.failed": "模拟运算失败了喵呜……(つд⊂)",
    "simulator.results": "模拟运算报告单喵~ (ฅ'ω'ฅ)",
    "simulator.figure": "大世界模拟路线轨迹图喵~ (•̀ω•́)",
    "simulator.cl1Count": "侵蚀1踩坑次数喵",
    "simulator.meowCount": "猫猫头碰头次数喵",
    "simulator.crash": "翻车坠机概率喵",
    "simulator.cl1Time": "侵蚀1泡澡总时长喵",
    "simulator.meowTime": "猫猫相蹭总时长喵",
    "simulator.ap": "最终结余行动力喵",
    "simulator.coin": "最终搜刮黄币喵",

    # Resource flow
    "flow.food": "后宅口粮小鱼干喵~",
    "flow.urPt": "活动 UR 点数喵~",
    "flow.furnitureCoin": "后宅家具币喵~",
    "flow.gachaTicket": "建造猫粮券喵~",
    "flow.hint": "帮指挥官盯紧每一条小鱼干的来龙去脉，看看是谁偷偷吃掉啦喵！(ฅ`ω´ฅ)",
    "flow.range": "时间区间喵~",
    "flow.day": "最近 24 小时喵~",
    "flow.week": "最近 7 天喵~",
    "flow.month": "最近 30 天喵~",
    "flow.custom": "自定义时间段喵~",
    "flow.start": "开始时间喵~",
    "flow.end": "结束时间喵~",
    "flow.apply": "应用筛选区间喵！(•̀ω•́)",
    "flow.resource": "资源类型喵~",
    "flow.task": "对应任务喵~",
    "flow.allResources": "所有资源类型喵~",
    "flow.allTasks": "所有任务列表喵~",
    "flow.search": "搜索资源或物品名称喵~",
    "flow.current": "最新结余库存喵~",
    "flow.income": "收获进账喵！(*^▽^*)",
    "flow.expense": "支出消耗喵~ (*/ω＼*)",
    "flow.net": "净增减变化喵~",
    "flow.adjustment": "待归因变动喵~",
    "flow.unattributed": "未分类变动喵~",
    "flow.balance": "区间结余库存喵~",
    "flow.stock": "从库存支出喵~",
    "flow.sankey": "资源桑基流向图喵~ (•̀ω•́)",
    "flow.inventory": "猫窝存粮总览喵~ (*^▽^*)",
    "flow.details": "小鱼干收支明细手账喵~ (ฅ'ω'ฅ)",
    "flow.export": "导出全部筛选明细喵~",
    "flow.empty": "这段时间没有任何收支记录喵~ (｡•́︿•̀｡)",
    "flow.units": "每种资源独立缩放显示数量，不同流线的宽度不能直接比较价值喵~ (•̀ω•́)",
    "flow.evidence": "记录判定依据喵~",
    "flow.confirmed": "已确认记录喵~",
    "flow.recognition": "界面奖励识别喵~",
    "flow.observed": "任务内净观测变化喵~",
    "flow.time": "记录时刻喵~",
    "flow.operation": "收支用途与来源喵~",
    "flow.prev": "上一页记录喵~",
    "flow.next": "下一页记录喵~",
    "flow.count": "共 {count} 条收支记录喵~",
    "flow.oil": "石油自动控制喵~",
    "flow.oilEnable": "启用自动清油防溢出喵~",
    "flow.oilTarget": "石油控制警戒线喵~",
    "flow.oilHint": "仅原调度生效：先打急需的图，冷却时去后宅买粮，绝不浪费一滴油喵~ (=^-ω-^=)",
    "flow.saved": "控制设置已保存好啦喵~ (ฅ'ω'ฅ)",
    "flow.saving": "正在保存控制设置中喵……",
    "flow.save": "保存控制设置喵！(•̀ω•́)",
    "flow.targetInvalid": "控制线必须是 1000 到 24999 之间的整数喵~ ( > < )",

    # Settings Theme & Colors
    "settings.colorMode": "界面主题模式喵~ (=^-ω-^=)",
    "settings.colorModeHelp": "随昼夜光线自然变色喵！白天浅色模式、夜晚深色护眼，超贴心哒~ (*^▽^*)",
    "settings.modeAuto": "随系统自动变色喵~",
    "settings.themeMinimal": "清爽极简模式喵~",
    "settings.customPalette": "专属自定义配色喵~ (*^▽^*)",
    "settings.primaryColor": "主强调色喵~",
    "settings.secondaryColor": "副强调色喵~",
    "settings.colorPicker": "取色器工具喵~",
    "settings.paletteInvalid": "请指挥官使用标准的 #RRGGBB 颜色格式喵！(,,・ω・,,)",
    "settings.savePalette": "保存并应用配色喵！(ﾉ>ω<)ﾉ",
    "settings.addPalette": "添加新配色方案喵~ (ฅ'ω'ฅ)",
    "settings.editPalette": "编辑这套方案喵~ (•̀ω•́)",
    "settings.deletePalette": "删除这套配色方案喵！(╬ﾟдﾟ)ﾉ",
    "settings.modeTerminal": "极客程序员黑客模式喵~",
    "settings.modeRetroGray": "怀旧复古灰色折耳猫模式",
    "settings.modeRetroBlue": "优雅复古英短蓝猫模式",
    "settings.modeRetroRed": "热情复古红猫模式",
    "settings.palette": "配色方案选择喵~",
    "settings.paletteHelp": "主色用于主要操作与高亮选中，副色用于辅助信息呈现喵~ (•̀ω•́)",
    "settings.background": "自定义背景壁纸喵~",
    "settings.backgroundHelp": "可以使用在线图片或视频地址，也可以上传文件保存在当前浏览器喵~ (*^▽^*)",
    "settings.backgroundOff": "关闭自定义背景喵~",
    "settings.backgroundUrl": "输入图片或视频 URL喵~",
    "settings.backgroundUpload": "上传本地文件喵~",
    "settings.backgroundType": "背景类型选择喵~",
    "settings.backgroundImage": "静态图片喵~",
    "settings.backgroundVideo": "动态视频喵~",
    "settings.backgroundApply": "应用此背景喵！(ﾉ>ω<)ﾉ",
    "settings.backgroundSaving": "正在保存背景中喵……",
    "settings.backgroundLimit": "支持浏览器可播放的图片与视频，文件最大 200 MB 喵~",
    "settings.backgroundApplied": "背景已成功换上啦喵！(*^▽^*)",

    # Palette
    "settings.colorPalette": "猫猫自定义调色板喵~ (ฅ'ω'ฅ)",
    "settings.colorPaletteHelp": "逐项细调界面里的每一个颜色，改动立即生效，明暗两套分别保存好哒喵~ (*^▽^*)",
    "settings.colorPaletteOpen": "打开调色板喵！(ﾉ>ω<)ﾉ",
    "settings.colorPaletteCount": "已修改了 {count} 项颜色喵~ (ฅ'ω'ฅ)",
    "settings.colorPaletteSearch": "搜寻颜色代码或名称喵~ (=①ω①=)",
    "settings.colorPaletteEditing": "正在仔细调整编辑中喵~ (*/ω＼*)",
    "settings.colorPaletteResetAll": "全部恢复为默认原色喵！(つд⊂)",
    "settings.colorPaletteResetOne": "还原这一项颜色喵~",
    "settings.colorPaletteEmpty": "没有找到匹配的颜色喵呜……(｡•́︿•̀｡)",
    "settings.colorPaletteLive": "改动直接写入当前浏览器；点击还原即可回到主题自带颜色喵~ (*^▽^*)",
    "settings.colorGroupSurface": "画布与面板底色喵~",
    "settings.colorGroupText": "文字字体颜色喵~",
    "settings.colorGroupAccent": "重点强调颜色喵~",
    "settings.colorGroupStatus": "系统状态颜色喵~",
    "settings.colorGroupNav": "侧栏导航颜色喵~",
    "settings.colorGroupForm": "表单控件颜色喵~",
    "settings.colorGroupLog": "运行日志颜色喵~",
    "settings.colorGroupSyntax": "代码高亮颜色喵~",
    "settings.colorGroupChart": "统计图表颜色喵~",
    "settings.colorSlotBg": "页面背景底色喵~",
    "settings.colorSlotSurface": "面板卡片底色喵~",
    "settings.colorSlotSurfaceMuted": "次级面板底色喵~",
    "settings.colorSlotBorder": "边框描边颜色喵~",
    "settings.colorSlotText": "主文字颜色喵~",
    "settings.colorSlotMuted": "辅助说明文字颜色喵~",
    "settings.colorSlotOnAccent": "高光前景文字颜色喵~",
    "settings.colorSlotOnDanger": "危险警告前景文字颜色喵~",
    "settings.colorSlotAccent": "核心强调高亮色喵~",
    "settings.colorSlotAccentHover": "悬停高亮颜色喵~",
    "settings.colorSlotAccentSoft": "浅底柔和强调色喵~",
    "settings.colorSlotSecondary": "辅助次要颜色喵~",
    "settings.colorSlotSecondarySoft": "辅助浅底色喵~",
    "settings.colorSlotDanger": "危险警报红色喵！(╬ﾟдﾟ)",
    "settings.colorSlotSuccess": "成功绿灯颜色喵！(*^▽^*)",
    "settings.colorSlotSuccessSoft": "成功浅绿底色喵~",
    "settings.colorSlotDangerSoft": "警示浅红底色喵~",
    "settings.colorSlotWarning": "警戒提示黄颜色喵~ (•̀ω•́)",
    "settings.colorSlotWarningSoft": "警戒淡黄底色喵~",
    "settings.colorSlotNavIcon": "导航图标颜色喵~",
    "settings.colorSlotNavActiveBg": "导航项选中背景色喵~",
    "settings.colorSlotNavActiveText": "导航项选中文字色喵~",
    "settings.colorSlotNavHoverBg": "导航项悬停背景色喵~",
    "settings.colorSlotNavExpandedBg": "导航栏展开背景色喵~",
    "settings.colorSlotInputBorder": "输入框边框颜色喵~",
    "settings.colorSlotToggleOff": "开关关闭时颜色喵~",
    "settings.colorSlotToggleOn": "开关打开时颜色喵！",
    "settings.colorSlotToggleKnob": "开关圆滑块颜色喵~",
    "settings.colorSlotScrollbar": "滚动条滑块颜色喵~",
    "settings.colorSlotLogDebug": "调试日志颜色喵~ (•̀ω•́)",
    "settings.colorSlotLogInfo": "常规信息日志颜色喵~",
    "settings.colorSlotLogWarning": "警告日志颜色喵！(╬ﾟдﾟ)",
    "settings.colorSlotLogError": "错误日志颜色喵！(つд⊂)",
    "settings.colorSlotLogCritical": "严重错误日志颜色喵！(=`･ω･´=)",
    "settings.colorSlotLogTime": "时间戳标记颜色喵~",
    "settings.colorSlotLogTrue": "逻辑真值颜色喵~",
    "settings.colorSlotLogFalse": "逻辑假值颜色喵~",
    "settings.colorSlotLogNull": "空值颜色喵~",
    "settings.colorSlotLogPath": "路径文本颜色喵~",
    "settings.colorSlotLogAttr": "属性标识颜色喵~",
    "settings.colorSlotSyntaxKey": "代码键名颜色喵~",
    "settings.colorSlotSyntaxString": "字符串文本颜色喵~",
    "settings.colorSlotSyntaxValue": "代码数值颜色喵~",
    "settings.colorSlotSyntaxComment": "代码注释颜色喵~",
    "settings.colorSlotSyntaxPunctuation": "标点符号颜色喵~",
    "settings.colorSlotChartPrimary": "图表主数据序列颜色喵~",
    "settings.colorSlotChartSecondary": "图表次数据序列颜色喵~",
    "settings.colorSlotChartRise": "图表上涨曲线颜色喵~",
    "settings.colorSlotChartFall": "图表下跌曲线颜色喵~",

    # Stock
    "stock.name": "茗喵奸商黑心交易所 (=①ω①=)",

    # Task
    "task.clearExploreProgress": "清空开荒进度喵~",
    "task.clearExploreProgressHelp": "清空本任务的进度和断点喵；请指挥官先停止任务。本月的购买记录会好好保存哒 (ฅ'ω'ฅ)",
    "task.groupNav": "任务分类目录喵~",
    "task.started": "任务已经启动啦喵！(ﾉ>ω<)ﾉ",
    "task.runTool": "执行快捷工具喵！(•̀ω•́)",
}

def clean_preexisting_emojis(text: str) -> str:
    """Replace pre-existing emojis from base text with cute cat equivalent text."""
    if not isinstance(text, str):
        return text
    text = text.replace("\u26a0\ufe0f", "【猫猫警惕】")
    text = text.replace("\u26a0", "【竖起耳朵】")
    text = text.replace("\U0001f4c8", "[趋势图]")
    text = text.replace("\U0001f4ca", "[统计图]")
    text = text.replace("\u2713", "[已完成]")
    return EMOJI_PATTERN.sub('', text)

def is_literal_code(s: str) -> bool:
    """Check if the string is purely a number, identifier, version, or code."""
    s = s.strip()
    if not s:
        return True
    if re.fullmatch(r'[\d\.\-%xX: ]+', s):
        return True
    if re.fullmatch(r'#[0-9a-fA-F]{3,8}', s):
        return True
    if re.fullmatch(r'[\W_]+', s):
        return True
    if s in {'ADB', 'ADB_nc', 'uiautomator2', 'Nemug', 'MuMu64', 'LDPlayer', 'BlueStacks', 'Nox', 'true', 'false', 'null', 'True', 'False', 'None'}:
        return True
    return False

def make_catgirl_natural(sentence: str, seed: int) -> str:
    """Transform a sentence naturally into cute, charming catgirl voice without crude word-swapping."""
    s = sentence.strip()
    if not s:
        return sentence

    if is_literal_code(s):
        return sentence

    # Direct override check
    if s in SPECIAL_OVERRIDES:
        return SPECIAL_OVERRIDES[s]

    has_cjk = any('\u4e00' <= c <= '\u9fff' for c in s)
    if not has_cjk:
        if re.search(r'[a-zA-Z]{3,}', s) and ' ' in s:
            return s + " nya~ (ฅ'ω'ฅ)"
        return sentence

    # If sentence already has cute cat particles, leave it
    if s.endswith("喵！") or s.endswith("喵~") or s.endswith("哒喵~") or s.endswith("呢喵~") or s.endswith("喵嗷！") or s.endswith("喵呼呼~"):
        return s

    # Natural tone adjustments: gentle conversational tweaks
    s = s.replace("请勿", "请指挥官不要")
    s = s.replace("请确保", "请指挥官一定要确认好喵")
    s = s.replace("建议", "猫猫建议")
    s = s.replace("用户", "指挥官")
    s = s.replace("玩家", "指挥官")
    s = s.replace("指挥官指挥官", "指挥官")

    kaomoji = KAOMOJI_ALL[seed % len(KAOMOJI_ALL)]
    ending_style = seed % 5

    # Natural sentence endings
    if s.endswith("？") or s.endswith("?"):
        body = s[:-1].rstrip()
        if ending_style in (0, 1):
            s = f"{body}喵？指挥官知道了吗喵？(,,・ω・,,)"
        elif ending_style in (2, 3):
            s = f"{body}喵？是不是这样呢喵？(=^･ω･^=)"
        else:
            s = f"{body}喵？快告诉本喵嘛~ (・ω・=)？"
    elif s.endswith("！") or s.endswith("!"):
        body = s[:-1].rstrip()
        if ending_style in (0, 1):
            s = f"{body}喵！{kaomoji}"
        elif ending_style in (2, 3):
            s = f"{body}哒喵！(ﾉ>ω<)ﾉ"
        else:
            s = f"{body}喵呼呼！大获全胜~ (*^▽^*)"
    elif s.endswith("。"):
        body = s[:-1].rstrip()
        if ending_style == 0:
            s = f"{body}喵~ {kaomoji}"
        elif ending_style == 1:
            s = f"{body}哒喵！(•̀ω•́)"
        elif ending_style == 2:
            s = f"{body}呢喵~ (=^-ω-^=)"
        elif ending_style == 3:
            s = f"{body}的说喵~ (*^▽^*)"
        else:
            s = f"{body}喵~ (ฅ'ω'ฅ)"
    elif s.endswith("…") or s.endswith("..."):
        body = s.rstrip(".…")
        s = f"{body}喵呜……(つд⊂)"
    else:
        # Short titles, buttons, option labels
        if len(s) <= 8:
            if ending_style == 0:
                s = f"{s}喵~ (ฅ'ω'ฅ)"
            elif ending_style == 1:
                s = f"{s}哒喵！(ﾉ>ω<)ﾉ"
            elif ending_style == 2:
                s = f"{s}呢喵~ (=^-ω-^=)"
            elif ending_style == 3:
                s = f"{s}的说喵~ (*^▽^*)"
            else:
                s = f"{s}喵~"
        else:
            if ending_style == 0:
                s = f"{s}喵~ {kaomoji}"
            elif ending_style == 1:
                s = f"{s}哒喵！(ﾉ>ω<)ﾉ"
            elif ending_style == 2:
                s = f"{s}呢喵~ (=^-ω-^=)"
            elif ending_style == 3:
                s = f"{s}的说喵~ (*^▽^*)"
            else:
                s = f"{s}喵~ (ฅ'ω'ฅ)"

    s = re.sub(r'喵[~！。]*喵+', '喵', s)
    return s

def nekomize_text(text: str, path: str = "") -> str:
    """Nekomize a full text while preserving all placeholders."""
    if not isinstance(text, str) or not text:
        return text

    if path in BACKEND_OVERRIDES:
        return BACKEND_OVERRIDES[path]
    if path in ALL_FRONTEND_OVERRIDES:
        return ALL_FRONTEND_OVERRIDES[path]

    if is_literal_code(text):
        return text

    # Direct override check
    if text.strip() in SPECIAL_OVERRIDES:
        return SPECIAL_OVERRIDES[text.strip()]

    cleaned_text = clean_preexisting_emojis(text)

    # Extract all placeholders
    placeholders = []
    def placeholder_replacer(match):
        token = f"__PH_{len(placeholders)}__"
        placeholders.append(match.group(0))
        return token

    protected = PLACEHOLDER_REGEX.sub(placeholder_replacer, cleaned_text)

    seed = sum(ord(c) for c in (path + text))

    lines = protected.split("\n")
    transformed_lines = []
    for line_idx, line in enumerate(lines):
        if not line.strip():
            transformed_lines.append(line)
            continue

        # Split clauses by full-stop ONLY, preserving full-stop
        parts = re.split(r'([。])', line)
        transformed_parts = []
        for part_idx in range(0, len(parts), 2):
            clause = parts[part_idx]
            sep = parts[part_idx + 1] if part_idx + 1 < len(parts) else ""
            if not clause.strip():
                transformed_parts.append(clause + sep)
                continue

            full_clause = clause + sep
            transformed_clause = make_catgirl_natural(full_clause, seed + line_idx * 13 + part_idx * 7)
            transformed_parts.append(transformed_clause)

        transformed_lines.append("".join(transformed_parts))

    result = "\n".join(transformed_lines)

    for i, ph in enumerate(placeholders):
        result = result.replace(f"__PH_{i}__", ph)

    result = EMOJI_PATTERN.sub('', result)
    return result

# Compact dictionary for short UI controls (Buttons, Tabs, Column Headers, Badges)
COMPACT_DICTIONARY = {
    "保存": "盖章保存喵！",
    "取消": "算啦取消喵~",
    "确认": "好哒确认喵！",
    "确定": "确定好啦喵！",
    "删除": "一爪删除喵！",
    "重置": "推倒重置喵！",
    "运行": "立刻运行喵！",
    "停止": "停下休息喵~",
    "暂停": "稍等暂停喵~",
    "恢复": "继续跑跑喵！",
    "编辑": "修改编辑喵~",
    "复制": "抓取复制喵！",
    "搜索": "嗅嗅搜索喵~",
    "关闭": "关上小门喵~",
    "打开": "推门打开喵~",
    "刷新": "甩耳刷新喵！",
    "新建": "新建条目喵！",
    "导入": "搬进导入喵~",
    "导出": "打包导出喵！",
    "重试": "再试出爪喵！",
    "返回": "溜回上页喵~",
    "全选": "全部圈走喵！",
    "反选": "反向抓阄喵！",
    "下载": "叼走下载喵！",
    "上传": "递交上传喵！",
    "查看": "凑近瞧瞧喵~",
    "清除": "扫掉清除喵！",
    "清空": "全部清空喵！",
    "添加": "添置加入喵！",
    "移除": "请出移除喵~",
    "同步": "同步数据喵！",
    "是": "昂对哒喵！",
    "否": "才不是喵~",
    "有": "有哒喵！",
    "无": "空空如也喵",
    "全部": "全都都要喵！",
    "未知": "底细未知喵？",
    "普通": "普通猫猫喵~",
    "困难": "困难硬骨头喵",
    "成功": "大捷成功喵！",
    "失败": "翻车踩坑啦喵",
    "启用": "启用哒喵！",
    "停用": "停用喵~",
    "已启用": "已启用喵~",
    "已停用": "已停用喵~",
    "卸载": "卸载哒喵！",
    "运行中": "抓鱼运行中喵",
    "待命中": "趴着待命中喵",
    "需要处理": "卡爪需救助喵",
    "更新中": "正在换毛中喵",
    "未运行": "睡大觉中喵~",
    "排队中": "排排坐等待喵",
    "等待中": "摇尾等待中喵",
    "总览": "巡逻总览喵~",
    "任务": "抓鱼任务喵~",
    "设置": "猫窝设置喵~",
    "日志": "爪印日志喵~",
    "插件": "猫猫插件喵~",
    "主题": "猫窝主题喵~",
    "出击": "出海抓鱼喵！",
    "活动": "限时狂欢喵~",
    "工具": "百宝工具喵~",
    "远程访问": "远程通道喵~",
    "资源管理": "金库资源喵~",
    "资源统计": "存粮统计喵~",
    "舰队": "大队巡航喵~",
    "指挥喵": "指挥喵苗圃喵",
    "养成计算": "心智计算喵~",
    "换船调度": "轮换换船喵~",
    "换船装备": "换装更衣喵~",
    "舰队科技": "舰队科技喵~",
    "智能换船": "智能换船喵！",
    "我的舰船": "我的舰船喵~",
    "石油": "战舰黑油喵~",
    "物资": "金币物资喵！",
    "钻石": "红尖尖宝石喵",
    "魔方": "心智魔方喵~",
    "行动力": "出海行动力喵",
    "快速建造": "加速钻头喵！",
    "海里数": "巡航海里喵~",
    "活动 PT": "龙虾积分 PT喵",
    "核心数据": "核心数据喵~",
    "心智单元": "心智小金方喵",
    "家具币": "猫窝家具币喵",
    "建造券": "造船奖券喵！",
    "后宅粮食": "小猫口粮喵~",
    "调色板": "调色板喵！",
    "打开调色板": "打开调色板喵",
    "正在编辑": "正在涂鸦喵~",
    "全部还原": "全部还原喵！",
    "还原此项": "还原此项喵~",
    "画布与面": "画布底面喵~",
    "文字": "字迹墨水喵~",
    "强调": "焦点强调喵！",
    "状态": "运行状态喵~",
    "侧栏导航": "爬架导航喵~",
    "表单控件": "表单开关喵~",
    "运行日志": "抓鱼日记喵~",
    "代码高亮": "代码高亮喵~",
    "图表": "趋势图表喵~",
    "页面底色": "猫窝底色喵~",
    "面板底色": "软垫底色喵~",
    "次级底色": "次级底色喵~",
    "描边": "木纹描边喵~",
    "正文": "正文字迹喵~",
    "辅助文字": "辅助小字喵~",
    "强调前景": "焦点前景喵~",
    "危险前景": "警报前景喵~",
    "强调色": "焦点高光色喵",
    "强调悬停": "悬停高亮色喵",
    "强调浅底": "焦点浅底色喵",
    "辅助色": "辅助副色喵~",
    "辅助浅底": "辅助浅底色喵",
    "危险色": "警报危险色喵",
    "成功色": "大捷成功色喵",
    "警告色": "警觉警告色喵",
    "图标": "小猫图标色喵",
    "选中底色": "选中底色喵~",
    "选中文字": "选中字迹喵！",
    "悬停底色": "悬停底色喵~",
    "展开底色": "展开底色喵~",
    "输入描边": "输入描边喵~",
    "开关（关）": "合门关灯喵~",
    "开关（开）": "开门亮灯喵！",
    "开关滑块": "开关滑珠喵~",
    "滚动条": "滑梯滚动条喵",
    "调试": "显微调试喵~",
    "信息": "日常信息喵~",
    "警告": "警报字迹喵！",
    "错误": "错误红字喵呜",
    "严重": "致命红字喵！",
    "时间戳": "时钟刻度喵~",
    "真值": "真真切切喵~",
    "假值": "假冒伪劣喵~",
    "空值": "空空如也喵~",
    "路径": "秘密路径喵~",
    "属性": "属性徽章喵~",
    "键名": "钥匙键名喵~",
    "字符串": "字串长句喵~",
    "数值": "鱼干个数喵~",
    "注释": "悄悄话注释喵",
    "标点": "小石子标点喵",
    "主序列": "主力大波浪喵",
    "次序列": "辅助小波浪喵",
    "上涨": "鱼干暴涨喵！",
    "下跌": "零食下跌喵呜",
    "开始模拟": "放飞模拟喵！",
    "中断模拟": "按住中断喵！",
    "等待模拟": "打盹待命喵~",
    "正在模拟": "沙盘推演中喵",
    "等待中断": "减速刹车中喵",
    "模拟完成": "推演大捷喵！",
    "模拟已中断": "推演已中断喵",
    "模拟失败": "推演算崩啦喵",
    "模拟结果": "沙盘战报喵！",
    "大世界模拟轨迹图": "大世界轨迹图喵",
    "侵蚀1次数": "侵蚀1巡航喵",
    "耄耋相接次数": "相接亲亲数喵",
    "坠机概率": "坠机摔跤率喵",
    "侵蚀1总时长": "侵蚀1总耗时喵",
    "耄耋相接总时长": "相接总时长喵",
    "最终行动力": "最终行动力喵",
    "最终黄币": "最终小黄币喵",
    "卡片等宽": "卡片等宽排排坐",
    "字体适应": "文字缩放自适应",
    "紧凑视图": "抱团紧凑视图喵",
    "合并为单卡": "大锅炖合并单卡",
    "总行动力优先": "总行动力置顶喵",
    "大狗图标": "巡逻大狗图章喵",
    "立刻运行": "立刻出航喵！",
    "运行工具": "开工工具喵！",
    "清空开荒进度": "重置开荒脚印喵",
    "驱逐": "驱逐妹喵~",
    "轻巡": "轻巡姐喵！",
    "重巡": "帅气重巡喵",
    "战巡": "疾风战巡喵",
    "战列": "大战列舰喵",
    "轻航": "轻型航母喵",
    "航母": "航空母舰喵",
    "潜艇": "潜水小艇喵",
    "航战": "两栖航战喵",
    "维修": "维修白衣喵",
    "重炮": "巨炮重炮喵",
    "潜母": "潜水空母喵",
    "超巡": "超巡女王喵",
    "运输": "运输大包喵",
    "风帆": "风帆战舰喵",
    "白鹰": "白鹰大门派喵",
    "皇家": "皇家红茶派喵",
    "重樱": "重樱兽耳派喵",
    "铁血": "铁血黑科技喵",
    "东煌": "东煌美食派喵",
    "撒丁帝国": "撒丁披萨派喵",
    "北方联合": "北联猛猫派喵",
    "自由鸢尾": "自由鸢尾派喵",
    "维希教廷": "维希教廷派喵",
    "耐久": "厚厚耐久喵",
    "炮击": "巨炮炮击喵",
    "雷击": "鱼雷雷击喵",
    "防空": "严密防空喵",
    "航空": "海鸟航空喵",
    "装填": "神速装填喵",
    "命中": "神准命中喵",
    "机动": "泥鳅机动喵",
    "反潜": "水下反潜喵",
    "舰名": "战舰大名喵",
    "等级": "摸鱼等级喵",
    "稀有度": "稀有度喵~",
    "阵营": "阵营门派喵",
    "舰种": "战舰舰种喵",
    "星级": "闪耀星级喵",
    "数量": "数量清点喵",
    "时间": "打卡时间喵",
    "来源": "出海来源喵",
    "单位": "计量单位喵",
    "数值": "具体战果喵",
    "前排先锋": "前排先锋队喵",
    "后排主力": "后排主力队喵",
    "已满星": "已大满星啦喵",
    "未满星": "未满星继续喂喵",
    "已完成": "搞定完成喵！",
    "未完成": "未搞定摸鱼喵",
}

KAOMOJI_PATTERN = re.compile(r'\s*\([^\(\)]*[\^・ω\-_><\*\+;@~\\/]+\s*[^\(\)]*\)\s*')

def compactify_ui_text(key: str, base_val: str, neko_val: str) -> str:
    """Ensure short UI elements never overflow container boundaries while keeping catgirl charm."""
    b_clean = base_val.strip().rstrip("。！!？?")
    if b_clean in COMPACT_DICTIONARY:
        return COMPACT_DICTIONARY[b_clean]

    # Ultra-short UI (buttons, badges, tabs, column titles <= 4 chars)
    if len(b_clean) <= 4:
        no_kao = KAOMOJI_PATTERN.sub('', neko_val).strip()
        if len(no_kao) > 7:
            if not b_clean.endswith("喵") and not b_clean.endswith("喵~") and not b_clean.endswith("喵！"):
                if len(b_clean) <= 3:
                    return f"{b_clean}喵~"
                else:
                    return f"{b_clean}喵"
            return no_kao[:7]
        return no_kao

    # Mid-short UI (card titles, short dialog labels <= 8 chars)
    if 5 <= len(b_clean) <= 8:
        no_kao = KAOMOJI_PATTERN.sub('', neko_val).strip()
        if len(no_kao) > 12:
            if "喵" not in b_clean:
                return f"{b_clean}喵~"
            return b_clean
        return no_kao

    return neko_val

def transform_backend_dict(data: dict, prefix: str = "") -> dict:
    """Recursively transform backend json dictionary."""
    res = {}
    for k, v in data.items():
        curr_path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            res[k] = transform_backend_dict(v, curr_path)
        elif isinstance(v, str):
            res[k] = nekomize_text(v, curr_path)
        else:
            res[k] = v
    return res

def main():
    repo_root = Path(__file__).resolve().parent.parent

    # 1. Generate Backend zh-CN-neko.json
    zh_cn_path = repo_root / "module" / "config" / "i18n" / "zh-CN.json"
    neko_json_path = repo_root / "module" / "config" / "i18n" / "zh-CN-neko.json"

    print(f"Reading base backend translation from {zh_cn_path}...")
    with open(zh_cn_path, "r", encoding="utf-8") as f:
        base_backend = json.load(f)

    print("Transforming to Nekomimi tone for backend with natural phrasing...")
    neko_backend = transform_backend_dict(base_backend)

    print(f"Writing {neko_json_path}...")
    with open(neko_json_path, "w", encoding="utf-8") as f:
        json.dump(neko_backend, f, ensure_ascii=False, indent=2)
    print("Backend zh-CN-neko.json generated successfully!")

    # 2. Extract frontend keys from i18n.ts
    dump_script = """
import { zhCN } from "./src/i18n";
import * as fs from "fs";
fs.writeFileSync("./src/zhCN_dump.json", JSON.stringify(zhCN));
"""
    dump_file = repo_root / "frontend" / "temp_dump.ts"
    dump_file.write_text(dump_script, encoding="utf-8")
    subprocess.run(["npx", "tsx", "temp_dump.ts"], cwd=repo_root / "frontend", check=True, shell=True)
    dump_file.unlink()

    dump_json = repo_root / "frontend" / "src" / "zhCN_dump.json"
    with open(dump_json, "r", encoding="utf-8") as f:
        base_frontend = json.load(f)
    dump_json.unlink()

    print(f"Transforming {len(base_frontend)} frontend UI keys with natural phrasing and UI space constraints...")
    neko_frontend = {}
    for k, v in base_frontend.items():
        raw_val = ALL_FRONTEND_OVERRIDES[k] if k in ALL_FRONTEND_OVERRIDES else nekomize_text(v, k)
        clean_val = EMOJI_PATTERN.sub('', raw_val)
        neko_frontend[k] = compactify_ui_text(k, v, clean_val)

    # Format into TypeScript file
    lines = [
        "// 由 dev_tools.generate_neko_i18n 维护的猫娘语本地化词典喵~ (ฅ'ω'ฅ)",
        "// 包含全部 UI 词条，严格 0 Emoji，纯纯的可爱猫娘语气与颜表情！",
        'import type { UiKey } from "./i18n"',
        "",
        "export const zhCNNeko: Record<UiKey, string> = {"
    ]
    for k, v in neko_frontend.items():
        escaped_val = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        lines.append(f'  "{k}": "{escaped_val}",')
    lines.append("}\n")

    neko_ts_path = repo_root / "frontend" / "src" / "i18n.neko.ts"
    print(f"Writing {neko_ts_path}...")
    with open(neko_ts_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("Frontend i18n.neko.ts generated successfully!")

if __name__ == "__main__":
    main()
