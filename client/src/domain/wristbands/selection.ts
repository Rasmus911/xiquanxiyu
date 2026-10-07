export interface WristbandSelectionState {
  active: boolean
  selectedIds: string[]
}

export function beginBatch(_state: WristbandSelectionState): WristbandSelectionState {
  return { active: true, selectedIds: [] }
}

export function toggleSelected(state: WristbandSelectionState, id: string): WristbandSelectionState {
  if (!state.active) return state
  const selectedIds = state.selectedIds.includes(id)
    ? state.selectedIds.filter((selectedId) => selectedId !== id)
    : [...state.selectedIds, id]
  return { ...state, selectedIds }
}

export function cancelBatch(_state: WristbandSelectionState): WristbandSelectionState {
  return { active: false, selectedIds: [] }
}

export function finishBatch(state: WristbandSelectionState): WristbandSelectionState {
  return cancelBatch(state)
}
