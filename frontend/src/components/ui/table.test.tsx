// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { TableViewport } from './table'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('TableViewport', () => {
  it('shows a synchronized control only while content overflows', () => {
    let width = 300
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(300)
    vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockImplementation(() => width)
    render(<TableViewport scrollLabel="Log table"><table><tbody><tr><td>Data</td></tr></tbody></table></TableViewport>)
    const region = screen.getByRole('region', {name: 'Log table'})
    expect(screen.queryByRole('slider')).toBeNull()
    expect(region.tabIndex).toBe(0)

    width = 600
    fireEvent(window, new Event('resize'))
    const slider = screen.getByRole('slider') as HTMLInputElement
    expect(slider.max).toBe('300')
    fireEvent.change(slider, {target: {value: '180'}})
    expect(region.scrollLeft).toBe(180)
    region.scrollLeft = 90
    fireEvent.scroll(region)
    expect(slider.value).toBe('90')

    width = 300
    region.scrollLeft = 0
    fireEvent(window, new Event('resize'))
    expect(screen.queryByRole('slider')).toBeNull()
  })
})
