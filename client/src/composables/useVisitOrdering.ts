import { ref, shallowReactive } from 'vue'
import { apiData, apiErrorMessage, http } from '../api/http'
import { assertCurrent, businessGeneration, onBusinessSessionClear } from '../business/state'
import { createVisitLoadGate } from '../domain/orders/load-gate'
import { VisitDraftBook, type SubmissionSnapshot } from '../domain/orders/visit-drafts'
import { orderFingerprint } from '../domain/orders/selection'
import { buildManualConsumption } from '../domain/orders/consumption'
import { clearPendingRequestKey, pendingRequestKey } from '../domain/requests/pending-key'
import type { Visit } from '../types'

interface PendingVisitRequest {
  target: SubmissionSnapshot
  key: string
  fingerprint: string
  generation: number
  body: Readonly<Record<string, unknown>>
}
const pending = shallowReactive(new Map<string, PendingVisitRequest>())
onBusinessSessionClear(() => pending.clear())
export function useVisitOrdering() {
  const ownerGeneration = businessGeneration.capture()
  const currentVisit = ref<Visit | null>(null)
  const loading = ref(false)
  const error = ref('')
  const gate = createVisitLoadGate()
  const drafts = new VisitDraftBook()
  onBusinessSessionClear(() => {
    gate.reset(); drafts.clear(); pending.clear(); currentVisit.value = null; loading.value = false; error.value = ''
  })
  async function load(id: string) {
    const generation = businessGeneration.capture()
    const ticket = gate.begin(id)
    const current = () => businessGeneration.isCurrent(generation) && gate.current(ticket)
    loading.value = true; error.value = ''
    try {
      const result = apiData<Visit>(await http.get(`/visits/${id}`))
      if (current()) currentVisit.value = result
    } catch (cause) {
      if (current()) error.value = apiErrorMessage(cause)
    } finally { if (current()) loading.value = false }
  }
  async function submitSnapshot(target: SubmissionSnapshot) {
    assertCurrent(ownerGeneration)
    const generation = businessGeneration.capture()
    const scope = `visit:${target.visitId}:batch-add`
    const fingerprint = orderFingerprint(target.visitId, target.quantities) + '|replace:' + !!target.confirmReplace + '|stock:' + JSON.stringify(target.consumptions || null)
    const previous = pending.get(target.visitId)
    if (previous && previous.fingerprint !== fingerprint) throw new Error('上一笔加单尚未确认，请先重试原选择')
    const snapshot = previous?.target || Object.freeze({ ...target,
      quantities: Object.freeze({ ...target.quantities }),
      ...(target.consumptions ? { consumptions: Object.freeze(Object.fromEntries(
        Object.entries(target.consumptions).map(([id, rows]) => [id,
          Object.freeze(buildManualConsumption(rows).inventory_consumption.map(row => Object.freeze(row))),
        ]),
      )) } : {}),
    })
    const key = previous?.key || pendingRequestKey(scope, `${target.visitVersion}|${fingerprint}`)
    const request = previous || { target: snapshot, fingerprint, key, generation,
      body: Object.freeze({
        version: snapshot.visitVersion,
        items: Object.freeze(Object.entries(snapshot.quantities).map(([catalog_item_id, quantity]) => Object.freeze({
          catalog_item_id, quantity,
          ...(snapshot.consumptions ? { inventory_mode: 'manual', inventory_consumption: snapshot.consumptions[catalog_item_id] || Object.freeze([]) } : {}),
        }))),
        idempotency_key: key,
        ...(snapshot.confirmReplace ? { confirm_replace: true } : {}),
      }),
    }
    pending.set(target.visitId, request)
    return sendRequest(request)
  }
  function pendingTarget(visitId: string) {
    if (!businessGeneration.isCurrent(ownerGeneration)) return undefined
    const request = pending.get(visitId)
    return request && businessGeneration.isCurrent(request.generation) ? request.target : undefined
  }
  async function retryPending(visitId: string) {
    assertCurrent(ownerGeneration)
    const request = pending.get(visitId)
    if (!request) throw new Error('当前手牌没有待确认操作，请重新选择项目')
    return sendRequest(request)
  }
  async function sendRequest(request: PendingVisitRequest) {
    assertCurrent(request.generation)
    const scope = `visit:${request.target.visitId}:batch-add`
    try {
      await http.post(`/visits/${request.target.visitId}/items/batch`, request.body, { headers: { 'Idempotency-Key': request.key } })
      assertCurrent(request.generation)
      if (pending.get(request.target.visitId) === request) {
        pending.delete(request.target.visitId); clearPendingRequestKey(scope, request.key)
      }
      return request.target
    } catch (cause) {
      assertCurrent(request.generation)
      const status = (cause as { response?: { status: number } })?.response?.status
      // Definitive rejection permits editing. A lost response must retain its original payload.
      if (status && status >= 400 && status < 500 && pending.get(request.target.visitId) === request) {
        pending.delete(request.target.visitId); clearPendingRequestKey(scope, request.key)
      }
      throw cause
    }
  }
  return { currentVisit, loading, error, drafts, load, submitSnapshot, pendingTarget, retryPending }
}
