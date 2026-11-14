/**
 * @fileoverview 全真模拟实例预览组件 (MockInstancePreview)。
 * 允许用户在真实的实例全景环境（包含顶栏、侧栏、资源卡、运行卡片、日志、右栏调度器以及菜单与弹窗）中，
 * 逐区域实时调整材质并获得即时视觉反馈。
 */

/*
 * 样式索引（混合分层 L2：复刻整套外壳并带 122 处内联样式，横跨多域文件，无法 colocate）。
 * - styles/mock-preview.css   本组件私有域：mock-preview-shell / mock-preview-rail / mock-preview-sidebar / mock-preview-inspector / mock-instance-preview-overlay，及 inspector-* 段（与 MaterialInspector 共用）
 * - styles/layout.css         复刻外壳骨架段：main-shell / topbar / sidebar / primary-nav / breadcrumb / task-group-button / task-submenu-item / rail-task-item / scheduler-widget / instance-menu / connection-label 等
 * - styles/panels.css         面板域：panel / panel-heading
 * - styles/resource-card.css  资源卡域：resource-card / resource-grid
 * - styles/insights.css       monitor 段：monitor-panel / overview-page
 * - styles/log.css            log-content
 * - styles/feedback.css       modal
 * 主题/皮肤对上述共享类的变量绑定（theme-primitives.css / theme-legacy.css 等）随主题系统生效，不逐处列出。
 * 归属说明：已核实全库无 app 侧消费方（仅 MockInstancePreview.test.tsx:4 引用），非 entry 静态树；不 colocate 属保守原则——
 * 无生产消费者时搬迁虽计算等价（生产无元素命中），但会使规则脱离常规加载路径，留 L2 待确认归属。
 */

export { MockInstancePreview } from './mock-preview/mock-instance-preview'
