import { ref } from 'vue'
export function useCatalogPointer(move: (source: string, target: string) => void, enabled: () => boolean) {
  const source = ref<string | null>(null)
  let pointerId: number | null = null
  function start(event: PointerEvent, id: string) {
    if (!enabled() || (event.button !== 0 && event.pointerType !== 'touch')) return
    source.value = id; pointerId = event.pointerId
    ;(event.currentTarget as HTMLElement)?.setPointerCapture?.(event.pointerId)
  }
  function finish(event: PointerEvent) {
    const id = source.value
    if (id === null || pointerId !== event.pointerId) return
    source.value = null; pointerId = null
    const target = document.elementFromPoint?.(event.clientX, event.clientY)?.closest('[data-catalog-id]')?.getAttribute('data-catalog-id')
    if (target && enabled()) move(id, target)
    ;(event.currentTarget as HTMLElement)?.releasePointerCapture?.(event.pointerId)
  }
  function cancel() { source.value = null; pointerId = null }
  return { source, start, finish, cancel }
}
