interface ShortcutKey {
  key: string
  ctrlKey: boolean
  metaKey: boolean
  altKey: boolean
  shiftKey: boolean
  isComposing: boolean
}
interface ShortcutContext { editable: boolean; modal: boolean; busy: boolean; canReturn: boolean }

export function editableTarget(target: EventTarget | null) {
  return target instanceof HTMLElement && Boolean(target.closest('input,textarea,select,[contenteditable="true"]'))
}

export function shortcutIntent(event: ShortcutKey, context: ShortcutContext) {
  if (event.isComposing) return null
  const refresh = event.key === 'F5' || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'r')
  const browserBack = event.altKey && event.key === 'ArrowLeft'
  if (context.modal || context.busy) return refresh || browserBack ? 'blocked' : null
  if (event.key === 'F1') return 'help'
  if (event.key === 'F2' && !event.ctrlKey && !event.altKey && !event.metaKey) return 'search'
  if (event.key === 'F5' || ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'r' && !event.altKey && !event.shiftKey)) return 'refresh'
  if (event.altKey && event.key === 'ArrowLeft' && context.canReturn) return 'back'
  if (context.editable) return null
  if (event.key === 'Escape' && !event.ctrlKey && !event.altKey && !event.metaKey) return 'escape'
  return null
}
