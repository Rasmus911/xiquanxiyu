const pagesByPath: Record<string, string> = {
  '/': 'wristbands', '/members': 'members', '/print-jobs': 'print-jobs', '/catalog': 'catalog',
  '/inventory': 'inventory', '/reports': 'reports', '/audit': 'audit', '/employees': 'employees', '/settings': 'settings',
}

export function pageAllowed(pages: string[], path: string, caps: Record<string, boolean>): boolean {
  if (path === '/checkout') return pages.includes('wristbands') && caps.checkout_write === true
  if (/^\/visits\/[^/]+$/.test(path)) return pages.includes('wristbands')
  if (/^\/members\/[^/]+\/(recharge|pass-purchase)$/.test(path)) return pages.includes('members') && caps.member_write === true
  const page = pagesByPath[path]
  return !!page && pages.includes(page)
}

export function landingPath(pages: string[]): string {
  return Object.keys(pagesByPath).find(path => pages.includes(pagesByPath[path]!)) || '/login'
}

export function assertSessionUi(value: unknown): asserts value is { ui_pages: string[]; capabilities: Record<string, boolean> } {
  const state = value as { ui_pages?: unknown; capabilities?: unknown } | null
  if (!state || !Array.isArray(state.ui_pages) || state.ui_pages.some(page => typeof page !== 'string')
    || !state.capabilities || typeof state.capabilities !== 'object' || Array.isArray(state.capabilities)
    || Object.values(state.capabilities).some(value => typeof value !== 'boolean')) {
    throw new Error('服务器版本未提供页面授权，请先更新云端服务后重新登录')
  }
}
