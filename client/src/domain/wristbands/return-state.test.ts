import { expect, it } from 'vitest'
import { clearBusinessSession } from '../../business/state'
import { readDashboardReturn, saveDashboardReturn } from './return-state'

it('keeps return position within this session only', () => {
  saveDashboardReturn({ area: 'female', keyword: '051', scrollTop: 640 })
  expect(readDashboardReturn()).toEqual({ area: 'female', keyword: '051', scrollTop: 640 })
  clearBusinessSession()
  expect(readDashboardReturn()).toBeNull()
})
