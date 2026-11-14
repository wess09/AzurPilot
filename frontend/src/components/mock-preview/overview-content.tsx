/**
 * 从 MockInstancePreview.tsx 原 276-388 行提取，纯搬迁未改动（仅新增导出）。
 * 全真预览主内容区样本：页面标题、资源卡、任务状态面板与实时日志，全部为写死样本数据。
 */
import { Award, Calendar, CheckCircle2, Clock, Fuel, Gem, RotateCcw, Settings, Shield, Sword } from 'lucide-react'

export function mockOverviewContent() {
  return (
          <main style={{flex: 1, padding: '24px 28px', overflowY: 'auto'}}>
            <div className="overview-page" style={{display: 'flex', flexDirection: 'column', gap: '20px'}}>
              {/* 页面标题 */}
              <div className="page-title" style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px'}}>
                <div style={{display: 'flex', alignItems: 'baseline', gap: '12px'}}>
                  <h1 style={{fontSize: '24px', fontWeight: 700, margin: 0}}>alas</h1>
                  <span style={{fontSize: '13px', color: 'var(--muted)'}}>碧蓝航线自动化实例 #1</span>
                </div>
                <div style={{display: 'flex', gap: '8px'}}>
                  <button type="button" className="button secondary" style={{height: '32px', padding: '0 12px', fontSize: '12px'}}>
                    <RotateCcw size={13} />
                    刷新
                  </button>
                  <button type="button" className="button secondary" style={{height: '32px', padding: '0 12px', fontSize: '12px'}}>
                    <Settings size={13} />
                    调度设置
                  </button>
                </div>
              </div>

              {/* 资源卡网格 (plate 托板区域) */}
              <div className="resource-grid" style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px'}}>
                <div className="resource-card" style={{padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '4px'}}>
                  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--muted)', fontSize: '12px'}}>
                    <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><Fuel size={14} style={{color: '#0284c7'}} />石油 (Oil)</span>
                    <span style={{fontSize: '11px', color: '#16a34a'}}>+450/h</span>
                  </div>
                  <strong style={{fontSize: '18px', fontWeight: 650, fontVariantNumeric: 'tabular-nums'}}>24,150</strong>
                  <span style={{fontSize: '11px', color: 'var(--muted)'}}>上限 25,000</span>
                </div>

                <div className="resource-card" style={{padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '4px'}}>
                  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--muted)', fontSize: '12px'}}>
                    <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><Award size={14} style={{color: '#eab308'}} />物资 (Gold)</span>
                    <span style={{fontSize: '11px', color: '#16a34a'}}>+3.8k/h</span>
                  </div>
                  <strong style={{fontSize: '18px', fontWeight: 650, fontVariantNumeric: 'tabular-nums'}}>289,400</strong>
                  <span style={{fontSize: '11px', color: 'var(--muted)'}}>上限 600,000</span>
                </div>

                <div className="resource-card" style={{padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '4px'}}>
                  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--muted)', fontSize: '12px'}}>
                    <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><Gem size={14} style={{color: '#f43f5e'}} />钻石 (Gem)</span>
                  </div>
                  <strong style={{fontSize: '18px', fontWeight: 650, fontVariantNumeric: 'tabular-nums'}}>3,420</strong>
                  <span style={{fontSize: '11px', color: 'var(--muted)'}}>储备充足</span>
                </div>

                <div className="resource-card" style={{padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '4px'}}>
                  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', color: 'var(--muted)', fontSize: '12px'}}>
                    <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><Shield size={14} style={{color: '#8b5cf6'}} />心智魔方 (Cube)</span>
                  </div>
                  <strong style={{fontSize: '18px', fontWeight: 650, fontVariantNumeric: 'tabular-nums'}}>1,280</strong>
                  <span style={{fontSize: '11px', color: 'var(--muted)'}}>快速建造券 856</span>
                </div>
              </div>

              {/* 正在运行的任务状态卡片 (surface 底板区域) */}
              <div className="panel" style={{padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: '14px'}}>
                <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
                  <div style={{display: 'flex', alignItems: 'center', gap: '12px'}}>
                    <div style={{padding: '8px', borderRadius: '10px', background: 'var(--accent-soft, #ede9fe)', color: 'var(--accent)'}}>
                      <Sword size={20} />
                    </div>
                    <div>
                      <h3 style={{margin: 0, fontSize: '16px', fontWeight: 650}}>12-4 鸟海捞船 · 正在出击</h3>
                      <p style={{margin: '2px 0 0', fontSize: '12.5px', color: 'var(--muted)'}}>
                        第 4 战 / 共 6 战 (道中主力队战斗完毕，正在寻敌大型主力舰队)
                      </p>
                    </div>
                  </div>
                  <span style={{padding: '4px 10px', borderRadius: '8px', fontSize: '12px', background: 'var(--accent-soft)', color: 'var(--accent)', fontWeight: 600}}>
                    进行中 65%
                  </span>
                </div>

                {/* 进度条与指标 */}
                <div style={{width: '100%', height: '7px', borderRadius: '999px', background: 'var(--surface-muted, #f1f5f9)', overflow: 'hidden'}}>
                  <div style={{width: '65%', height: '100%', borderRadius: '999px', background: 'var(--accent, #6366f1)', transition: 'width 0.3s ease'}} />
                </div>

                <div style={{display: 'flex', flexWrap: 'wrap', gap: '24px', fontSize: '12.5px', color: 'var(--muted)', paddingTop: '4px'}}>
                  <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><Clock size={14} />运行耗时: 00:14:28</span>
                  <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><Calendar size={14} />预计剩余: 00:04:12</span>
                  <span style={{display: 'flex', alignItems: 'center', gap: '6px'}}><CheckCircle2 size={14} style={{color: '#16a34a'}} />战果: S胜×3 (鸟海搜寻中)</span>
                </div>
              </div>

              {/* 实时日志面板 (plate 托板 + control 控件区域) */}
              <div className="panel monitor-panel" style={{display: 'flex', flexDirection: 'column'}}>
                <div className="panel-heading" style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 20px'}}>
                  <div style={{display: 'flex', alignItems: 'center', gap: '10px'}}>
                    <span style={{fontWeight: 650, fontSize: '14px'}}>实时运行日志</span>
                    <span style={{fontSize: '11px', color: 'var(--muted)'}}>实时流已就绪</span>
                  </div>
                  <div style={{display: 'flex', alignItems: 'center', gap: '6px'}}>
                    <button type="button" className="button secondary" style={{height: '28px', padding: '0 8px', fontSize: '11px'}}>全部</button>
                    <button type="button" className="button secondary" style={{height: '28px', padding: '0 8px', fontSize: '11px', color: '#0ea5e9'}}>INFO</button>
                    <button type="button" className="button secondary" style={{height: '28px', padding: '0 8px', fontSize: '11px', color: '#eab308'}}>WARN</button>
                  </div>
                </div>

                <div className="log-content" style={{height: '180px', minHeight: '160px', padding: '12px 18px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '4px'}}>
                  <div><span style={{color: 'var(--muted)'}}>[14:11:42]</span> <span style={{color: '#0ea5e9'}}>[INFO]</span> [Campaign] Enter campaign: 12-4 鸟海捞船模式</div>
                  <div><span style={{color: 'var(--muted)'}}>[14:11:45]</span> <span style={{color: '#0ea5e9'}}>[INFO]</span> [Combat] Fleet 1 moving to ambush grid (D, 3)</div>
                  <div><span style={{color: 'var(--muted)'}}>[14:11:50]</span> <span style={{color: '#0ea5e9'}}>[INFO]</span> [Combat] Auto combat round started. S-Rank achieved.</div>
                  <div><span style={{color: 'var(--muted)'}}>[14:12:12]</span> <span style={{color: '#22c55e'}}>[SUCCESS]</span> [Drop] Got Choukai (SSR) drop confirmed!</div>
                  <div><span style={{color: 'var(--muted)'}}>[14:12:15]</span> <span style={{color: '#0ea5e9'}}>[INFO]</span> [Emotion] Fleet 1 average emotion: 138 (Exp +20%)</div>
                  <div><span style={{color: 'var(--muted)'}}>[14:12:20]</span> <span style={{color: 'var(--accent)'}}>[Scheduler]</span> Next scheduled queue: 委托收获 in 00:07:40</div>
                </div>
              </div>
            </div>
          </main>
  )
}
