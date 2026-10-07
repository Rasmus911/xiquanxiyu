import { describe, expect, it } from 'vitest'
import { editableTarget, shortcutIntent } from './shortcuts'

const context = { editable: false, modal: false, busy: false, canReturn: true }
const key = (value: string, extra = {}) => ({ key: value, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, isComposing: false, ...extra })

describe('cashier keyboard shortcuts', () => {
  it('accepts a window-targeted help event without treating it as an input', () => {
    expect(editableTarget(window)).toBe(false)
    expect(editableTarget(document.createElement('input'))).toBe(true)
  })
  it('never consumes native editing or IME shortcuts', () => {
    for (const value of ['a', 'c', 'v', 'x', 'z', 'y']) expect(shortcutIntent(key(value, { ctrlKey: true }), context)).toBeNull()
    expect(shortcutIntent(key('Enter', { isComposing: true }), context)).toBeNull()
  })
  it('focuses search and refreshes business data without reloading the app', () => {
    expect(shortcutIntent(key('F2'), context)).toBe('search')
    expect(shortcutIntent(key('F5'), context)).toBe('refresh')
    expect(shortcutIntent(key('r', { ctrlKey: true }), context)).toBe('refresh')
  })
  it('lets dialogs handle Escape and never interrupts financial writes', () => {
    expect(shortcutIntent(key('Escape'), { ...context, modal: true })).toBeNull()
    expect(shortcutIntent(key('ArrowLeft', { altKey: true }), { ...context, busy: true })).toBe('blocked')
    expect(shortcutIntent(key('F5'), { ...context, busy: true })).toBe('blocked')
    expect(shortcutIntent(key('Escape'), context)).toBe('escape')
  })
  it('returns to the parent without stealing text editing keys', () => {
    expect(shortcutIntent(key('ArrowLeft', { altKey: true }), context)).toBe('back')
    expect(shortcutIntent(key('ArrowLeft', { altKey: true }), { ...context, editable: true })).toBe('back')
    expect(shortcutIntent(key('Enter'), context)).toBeNull()
  })
})
