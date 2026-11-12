// @vitest-environment jsdom
import {afterEach, describe, expect, it, vi} from 'vitest'
import {cleanup, fireEvent, render, screen, within} from '@testing-library/react'
import {MemoryRouter} from 'react-router-dom'
import {TechnologyTable} from '../pages/FleetTechnology'
import {translateFleetTech} from './i18n'
import type {Row} from './types'

const row: Row = {group_type: 100, code: 1, handbook_type: 0, blueprint: false, full_star_rule: 'ordinary_level_cap', name: 'Enterprise', names: {}, nationality: 1, rarity: 'SSR', type: 7, owned: true, full_star: false, lv120: false, awakening_pending: false, current_count: 0, current_level: null, evidence: {owned: [], full_star: [], lv120: []}, points: 3, status: 'unfinished', technology: {pt_get: 3, pt_upgrage: 7, pt_level: 5, max_star: 5, add_get_shiptype: [7], add_get_attr: 5, add_get_value: 1, add_level_shiptype: [7], add_level_attr: 5, add_level_value: 2}}
// 固定用英文语言渲染：列名与按钮的 aria 名都是英文，断言才能直接按英文查找。
function table(value: Row = row, props: Partial<Parameters<typeof TechnologyTable>[0]> = {}) {
  return render(<MemoryRouter><TechnologyTable rows={[value]} language="en-US" tr={key => translateFleetTech('en-US', key)} {...props}/></MemoryRouter>)
}
afterEach(cleanup)

describe('technology catalog table', () => {
  it('groups point and bonus columns and exposes read-only milestone states', () => {
    table()
    const headers = within(screen.getByRole('table'))
    expect(headers.getByRole<HTMLTableCellElement>('columnheader', {name: 'Tech points'}).colSpan).toBe(4)
    expect(headers.getByRole<HTMLTableCellElement>('columnheader', {name: 'Stat bonuses'}).colSpan).toBe(2)
    for (const [stage, completed] of [['Obtain', true], ['Max stars', false], ['Lv.120', false]] as const) {
      const button = screen.getByRole<HTMLButtonElement>('button', {name: `Enterprise · ${stage} · ${completed ? 'Completed' : 'Not completed'}`})
      expect(button.disabled).toBe(true)
      expect(button.getAttribute('aria-pressed')).toBe(String(completed))
    }
    expect(screen.getByRole('button', {name: 'Enterprise · Unlock · Completed'}).textContent).toContain('CV AVI+1')
    expect(screen.getByRole('button', {name: 'Enterprise · Lv.120 bonus · Not completed'}).textContent).toContain('CV AVI+2')
    expect(screen.queryByRole('spinbutton')).toBeNull()
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('dispatches milestone edits and sorting only through enabled controls', () => {
    const onChange = vi.fn(), onSort = vi.fn()
    table(row, {editing: true, onChange, onSort})
    fireEvent.click(screen.getByRole('button', {name: 'Enterprise · Max stars · Not completed'}))
    expect(onChange).toHaveBeenCalledExactlyOnceWith(row, 'full_star', true)
    fireEvent.click(screen.getByRole('button', {name: 'Name'}))
    expect(onSort).toHaveBeenCalledExactlyOnceWith('name')
  })

  it('links names to held ships and marks fully completed rows', () => {
    table({...row, full_star: true, lv120: true, current_count: 2, current_level: 125})
    const link = screen.getByRole('link', {name: 'Enterprise'})
    expect(link.getAttribute('title')).toBe('Currently held: 2 · Lv.125')
    expect(new URL((link as HTMLAnchorElement).href).searchParams.get('group')).toBe('100')
    expect(new URL((link as HTMLAnchorElement).href).searchParams.get('tab')).toBe('data')
    expect(link.closest('tr')?.classList.contains('ft-complete')).toBe(true)
  })
})
