interface BackRouteLike {
  query?: Record<string, unknown>
  meta?: Record<string, unknown>
}

function safeInternalPath(value: unknown): string | null {
  const path = Array.isArray(value) ? value[0] : value
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//')) return null
  return path
}

export function resolveBackTarget(route: BackRouteLike, fallback = '/') {
  return safeInternalPath(route.query?.returnTo)
    || safeInternalPath(route.meta?.parentRoute)
    || safeInternalPath(fallback)
    || '/'
}
