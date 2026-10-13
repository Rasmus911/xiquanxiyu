export interface ChipReceiverOptions {
  onRead: (uid: string) => void
  canRead: () => boolean
  clock?: () => number
  maxGapMs?: number
  minDigits?: number
}

export function createChipReceiver(options: ChipReceiverOptions) {
  const clock = options.clock || (() => performance.now())
  const gap = options.maxGapMs ?? 80
  const minimum = options.minDigits ?? 4
  let buffer = ''; let previous = 0; let overflow = false
  function reset() { buffer = ''; previous = 0; overflow = false }
  function keydown(event: KeyboardEvent) {
    if (!options.canRead() || event.isComposing || event.repeat || event.ctrlKey || event.altKey || event.metaKey) { reset(); return }
    const now = clock()
    if ((buffer || overflow) && now - previous > gap) reset()
    if (/^[0-9]$/.test(event.key)) {
      previous = now
      if (!overflow) {
        buffer += event.key
        if (buffer.length > 64) { overflow = true; buffer = '' }
      }
      return
    }
    if (event.key === 'Enter' && !overflow && buffer.length >= minimum) {
      const uid = buffer; reset()
      event.preventDefault(); event.stopPropagation()
      options.onRead(uid)
    } else reset()
  }
  return { keydown, reset }
}

export function isEditingTarget(target: EventTarget | null): boolean {
  return target instanceof Element && !!target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="textbox"]')
}
