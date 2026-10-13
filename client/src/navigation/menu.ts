import type { Employee } from '../types'
import { pageAllowed } from './access'

export type DesktopRole = Employee['role']

export interface MenuItem {
  label: string
  path: string
  icon: 'home' | 'member' | 'print' | 'catalog' | 'inventory' | 'report' | 'audit' | 'employee' | 'settings'
  roles: DesktopRole[]
}

export interface MenuGroup {
  label: string
  items: MenuItem[]
}

const cashierRoles: DesktopRole[] = ['cashier', 'manager', 'admin']
const managerRoles: DesktopRole[] = ['manager', 'admin']

const groups: MenuGroup[] = [
  {
    label: '前台营业',
    items: [
      { label: '前台手牌', path: '/', icon: 'home', roles: cashierRoles },
      { label: '会员管理', path: '/members', icon: 'member', roles: cashierRoles },
      { label: '小票补打', path: '/print-jobs', icon: 'print', roles: ['cashier','inventory','manager','admin','male_scrubber','female_scrubber','floor_attendant'] },
    ],
  },
  {
    label: '商品运营',
    items: [
      { label: '项目商品', path: '/catalog', icon: 'catalog', roles: managerRoles },
      { label: '库存管理', path: '/inventory', icon: 'inventory', roles: ['inventory', 'manager', 'admin'] },
    ],
  },
  {
    label: '经营管理',
    items: [
      { label: '经营报表', path: '/reports', icon: 'report', roles: managerRoles },
      { label: '操作记录', path: '/audit', icon: 'audit', roles: managerRoles },
    ],
  },
  {
    label: '系统',
    items: [
      { label: '员工账号', path: '/employees', icon: 'employee', roles: ['admin'] },
      { label: '系统设置', path: '/settings', icon: 'settings', roles: ['admin'] },
      { label: '手牌ID录入', path: '/wristband-bindings', icon: 'settings', roles: ['cashier', 'admin'] },
      { label: '账号密码修改', path: '/account-password', icon: 'settings', roles: ['cashier', 'inventory', 'male_scrubber', 'female_scrubber', 'floor_attendant', 'manager', 'admin'] },
    ],
  },
]

export function menuGroupsForRole(role: DesktopRole | string | null | undefined): MenuGroup[] {
  return groups
    .map((group) => ({ ...group, items: group.items.filter((item) => item.roles.includes(role as DesktopRole)) }))
    .filter((group) => group.items.length > 0)
}
const routePermissions: Record<string, string> = {
  '/': 'visit:read', '/members': 'member:read', '/print-jobs': 'print:write', '/catalog': 'catalog:read',
  '/inventory': 'inventory:read', '/reports': 'report:read', '/audit': 'audit:read', '/employees': 'employee:read', '/settings': 'settings:read',
  '/account-password': 'account:self',
  '/wristband-bindings': 'wristband:bind',
}
export function permissionForPath(path: string) {
  if (path.startsWith('/visits/')) return 'visit:read'
  if (path.startsWith('/members/')) return 'member:write'
  if (path === '/checkout') return 'checkout:write'
  return routePermissions[path] || ''
}
export function menuGroupsForPermissions(permissions: string[]): MenuGroup[] {
  return groups.map(group => ({ ...group, items: group.items.filter(item => permissions.includes('*') || permissions.includes(permissionForPath(item.path)) || (item.path==='/print-jobs'&&permissions.includes('print:order'))) })).filter(group => group.items.length)
}
export function menuGroupsForPages(pages: string[], capabilities: Record<string, boolean>): MenuGroup[] {
  return groups.map(group => ({ ...group, items: group.items.filter(item => pageAllowed(pages, item.path, capabilities)) }))
    .filter(group => group.items.length > 0)
}
