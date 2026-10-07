import { ref } from 'vue'
import { apiData, apiErrorMessage, http } from '../api/http'
import { businessGeneration, onBusinessSessionClear } from '../business/state'
import { moveBefore } from '../domain/catalog/layout'

interface CatalogLayout { revision: number; ids: string[] }
export function useCatalogLayout() {
  const editing = ref(false); const ids = ref<string[]>([]); const revision = ref(0)
  const busy = ref(false); const error = ref('')
  let operation = 0
  onBusinessSessionClear(() => { operation++; editing.value = false; ids.value = []; busy.value = false; error.value = ''; revision.value = 0 })
  async function begin() {
    if (busy.value) return
    const generation = businessGeneration.capture(); const owned = ++operation
    busy.value = true; error.value = ''
    try {
      const result = apiData<CatalogLayout>(await http.get('/catalog/layout'))
      if (!businessGeneration.isCurrent(generation) || owned !== operation) return
      ids.value = [...result.ids]; revision.value = result.revision; editing.value = true
    } catch (cause) {
      if (businessGeneration.isCurrent(generation) && owned === operation) error.value = apiErrorMessage(cause)
    } finally { if (businessGeneration.isCurrent(generation) && owned === operation) busy.value = false }
  }
  function cancel() { if (busy.value) return; operation++; editing.value = false; ids.value = []; error.value = '' }
  function move(source: string, target: string) { if (editing.value && !busy.value) ids.value = moveBefore(ids.value, source, target) }
  async function save() {
    if (!editing.value || busy.value) return
    const generation = businessGeneration.capture(); const owned = ++operation
    const payload = { revision: revision.value, ids: [...ids.value] }
    busy.value = true; error.value = ''
    try {
      const result = apiData<CatalogLayout>(await http.put('/catalog/layout', payload))
      if (!businessGeneration.isCurrent(generation) || owned !== operation) return
      ids.value = [...result.ids]; revision.value = result.revision; editing.value = false
    } catch (cause) {
      if (businessGeneration.isCurrent(generation) && owned === operation) error.value = apiErrorMessage(cause)
    } finally { if (businessGeneration.isCurrent(generation) && owned === operation) busy.value = false }
  }
  function membersChanged() { if (editing.value) error.value = '可售目录已变化，请取消后重新载入完整排列' }
  return { editing, ids, revision, busy, error, begin, cancel, move, save, membersChanged }
}
