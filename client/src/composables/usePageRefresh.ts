import { onBeforeUnmount, onMounted } from 'vue'

export function usePageRefresh(refresh: () => unknown) {
  const listener = () => { void refresh() }
  onMounted(() => window.addEventListener('xiquan:refresh-page', listener))
  onBeforeUnmount(() => window.removeEventListener('xiquan:refresh-page', listener))
}
