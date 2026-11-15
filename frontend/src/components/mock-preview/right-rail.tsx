/**
 * @fileoverview 全真预览右栏样本：调度计划与任务队列，用于 right-rail 材质区域调节。
 * 从 MockInstancePreview.tsx 原 391-424 行提取，纯搬迁未改动（仅新增导出）。
 */
import { Clock } from 'lucide-react'

/** 渲染预览右栏样本。 */
export function mockRightRail() {
  return (
        <aside className="right-rail mock-preview-rail" style={{display: 'flex', flexDirection: 'column'}}>
          <div className="right-rail-header" style={{padding: '16px 18px', borderBottom: '1px solid var(--border)'}}>
            <h4 style={{margin: 0, fontSize: '14px', fontWeight: 650, display: 'flex', alignItems: 'center', gap: '8px'}}>
              <Clock size={16} style={{color: 'var(--accent)'}} />
              调度计划 (Scheduler)
            </h4>
          </div>

          <div style={{padding: '14px', display: 'flex', flexDirection: 'column', gap: '10px'}}>
            <div className="scheduler-widget" style={{padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: '6px'}}>
              <span style={{fontSize: '11.5px', color: 'var(--muted)'}}>下个调度任务</span>
              <strong style={{fontSize: '15px', color: 'var(--accent)', fontWeight: 650}}>14:20 委托收获</strong>
              <span style={{fontSize: '11.5px', color: 'var(--muted)'}}>预计倒计时: 00:07:38</span>
            </div>

            <div style={{fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--muted)', marginTop: '8px', padding: '0 4px'}}>
              队列序列 (Queue)
            </div>

            <div className="rail-task-item" style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
              <span style={{fontSize: '13px', fontWeight: 500}}>14:35 演习出击</span>
              <small style={{color: 'var(--muted)'}}>00:22:38</small>
            </div>
            <div className="rail-task-item" style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
              <span style={{fontSize: '13px', fontWeight: 500}}>15:00 战术研修</span>
              <small style={{color: 'var(--muted)'}}>00:47:38</small>
            </div>
            <div className="rail-task-item" style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
              <span style={{fontSize: '13px', fontWeight: 500}}>16:00 后宅喂食</span>
              <small style={{color: 'var(--muted)'}}>01:47:38</small>
            </div>
          </div>
        </aside>
  )
}
