import type { MobileRole } from './types'

const allowedMobileRoles = new Set<MobileRole>([
  'admin',
  'male_scrubber',
  'female_scrubber',
  'floor_attendant',
  'inventory',
])

export function isAllowedMobileRole(role: string): role is MobileRole {
  return allowedMobileRoles.has(role as MobileRole)
}

export function canFilterBathAreas(role: string | undefined) {
  return role === 'admin' || role === 'floor_attendant'
}
