import { describe, expect, it } from 'vitest'
import { menuGroupsForPermissions, menuGroupsForRole } from './menu'

describe('menuGroupsForRole', () => {
  it('shows only cashier work areas to a cashier', () => {
    expect(menuGroupsForRole('cashier').flatMap((group) => group.items.map((item) => item.path)))
      .toEqual(['/', '/members', '/print-jobs'])
  })

  it('groups all administrator tools predictably', () => {
    expect(menuGroupsForRole('admin').map((group) => group.label))
      .toEqual(['前台营业', '商品运营', '经营管理', '系统'])
  })
})
it('server scope drives navigation without employee roles', () => {
  expect(menuGroupsForPermissions(['*']).flatMap(group => group.items.map(item => item.path))).toContain('/settings')
  expect(menuGroupsForPermissions(['inventory:read']).flatMap(group => group.items.map(item => item.path))).toEqual(['/inventory'])
  expect(menuGroupsForPermissions([])).toEqual([])
})
