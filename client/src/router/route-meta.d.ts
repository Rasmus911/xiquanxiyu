import 'vue-router'
import type { Employee } from '../types'

export {}

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    section?: string
    parentRoute?: string
    roles?: Employee['role'][]
  }
}
