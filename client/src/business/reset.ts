export interface ResetState {
  period_id: string; business_revision: number; policy_version: number
  maintenance: boolean; owner_reset_allowed: boolean
}
export interface ResetPreview {
  state: ResetState; confirmation_token: string; expires_at: string
  summary: { members: number; stored_balance: string; remaining_passes: number; active_visits: number; unsettled_amount: string; stock_items: number; stock_quantity: string }
}
export interface ResetTask {
  id: string; idempotency_key: string
  status: 'queued' | 'waiting' | 'backing_up' | 'resetting' | 'completed' | 'failed'
  stage: string; old_period_id: string; new_period_id?: string; error_code?: string; message?: string
  backup?: { sha256: string; size: number }
}
export interface Archive {
  period_id: string; reset_id: string; closed_at: string; summary: Record<string, unknown>; backup?: { sha256: string; size: number }
}
export interface Evidence { period_id: string; table: string; page: number; has_more: boolean; rows: Record<string, unknown>[] }
interface ResetOptions {
  request(method: 'GET' | 'POST', path: string, body?: unknown, params?: Record<string, unknown>): Promise<unknown>
  capture(): number; isCurrent(generation: number): boolean; clear(task: ResetTask): void
  readKey(): string; saveKey(key: string): void; createKey(): string; now(): number
  errorMessage?(error: unknown): string
}
export class ResetWorkflow {
  preview: ResetPreview | null = null
  task: ResetTask | null = null
  message = ''
  busy = false
  archives: Archive[] = []
  evidence: Evidence | null = null
  archivePage = 1
  private operation = 0
  constructor(private options: ResetOptions) {}
  get needsRecovery() {
    const key = this.options.readKey()
    return !!key && (this.task?.idempotency_key !== key || !['completed', 'failed'].includes(this.task.status))
  }
  private describe(error: unknown) {
    return this.options.errorMessage?.(error) || (error instanceof Error ? error.message : '查询失败')
  }
  private current(generation: number, operation: number) {
    return this.options.isCurrent(generation) && this.operation === operation
  }
  private async read<T>(request: () => Promise<unknown>, assign: (data: T) => void) {
    if (this.busy) return
    const generation = this.options.capture(); const operation = ++this.operation
    this.busy = true; this.message = ''
    try {
      const result = await request() as T
      if (this.current(generation, operation)) assign(result)
    } catch (error) {
      if (this.current(generation, operation)) this.message = this.describe(error)
    } finally { if (this.current(generation, operation)) this.busy = false }
  }
  async loadPreview() {
    if (this.needsRecovery) {
      this.message = '已有重置查询编号，请先查询原任务结果'; return
    }
    await this.read<ResetPreview>(() => this.options.request('GET', '/business/reset/preview'), data => { this.preview = data })
  }
  async submit(username: string, password: string, confirmation: string) {
    if (this.busy) return
    if (this.needsRecovery) { this.message = '已有重置查询编号，请先查询原任务结果'; return }
    if (!username.trim() || !password || confirmation !== '重置当前经营数据') {
      this.message = '请填写账号、密码，并完整输入“重置当前经营数据”'; return
    }
    const preview = this.preview
    if (!preview || !Number.isFinite(Date.parse(preview.expires_at)) || Date.parse(preview.expires_at) <= this.options.now()) {
      this.preview = null; this.message = '预览已过期，请重新预览（有效期5分钟）'; return
    }
    const generation = this.options.capture(); const operation = ++this.operation
    this.busy = true; this.message = ''; this.preview = null; this.task = null
    const key = this.options.createKey()
    try {
      this.options.saveKey(key)
      const result = await this.options.request('POST', '/business/reset/tasks', {
        username: username.trim(), password, confirmation, confirmation_token: preview.confirmation_token, idempotency_key: key,
      }) as ResetTask
      if (this.current(generation, operation)) this.applyTask(result)
    } catch (error) {
      if (this.current(generation, operation)) {
        const denied = error as { response?: { data?: { message?: string; error?: { code?: string } } } }
        if (['REAUTH_FAILED', 'ACCOUNT_LOCKED', 'RESET_PREVIEW_STALE', 'RESET_CONFIRMATION_INVALID'].includes(denied.response?.data?.error?.code || '')) {
          this.options.saveKey('')
          this.message = denied.response?.data?.message || '确认失败，请重新预览并核对账号密码'
          return
        }
        this.message = `${this.describe(error)}；请按已保存编号查询，未确认服务端结果`
        // A failed HTTP response does not establish whether the destructive task ran.
        await this.query(generation, operation)
      }
    } finally { if (this.current(generation, operation)) this.busy = false }
  }
  private applyTask(task: ResetTask) {
    this.task = task
    if (task.status === 'completed') {
      this.message = '重置已完成，请重新登录核对新经营期；此编号可继续查询归档结果'
      this.busy = false
      this.options.clear(task)
    } else if (task.status === 'failed') this.message = task.message || `重置失败：${task.error_code || task.stage}`
    else this.message = '任务在后台执行；关闭页面不会撤销服务端任务'
  }
  private async query(generation: number, operation: number) {
    const key = this.options.readKey()
    if (!key) return
    try {
      const tasks = await this.options.request('GET', '/business/reset/tasks', undefined, { idempotency_key: key }) as ResetTask[]
      if (!this.current(generation, operation)) return
      const task = tasks.find(row => row.idempotency_key === key)
      if (task) this.applyTask(task)
      else this.message = '尚未查到此编号；结果未确认，请稍后查询或重新登录后继续查询'
    } catch (error) {
      if (this.current(generation, operation)) this.message = `${this.describe(error)}；结果未确认，重新登录后可继续按编号查询`
    }
  }
  async recover() {
    if (this.busy || !this.options.readKey()) return
    const generation = this.options.capture(); const operation = ++this.operation
    this.busy = true
    try { await this.query(generation, operation) }
    finally { if (this.current(generation, operation)) this.busy = false }
  }
  async loadArchives(page = 1) {
    if (!Number.isInteger(page) || page < 1) return
    await this.read<Archive[]>(() => this.options.request('GET', '/business/archives', undefined, { page }), data => { this.archives = data; this.archivePage = page })
  }
  async loadEvidence(period: string, table = 'members', page = 1) {
    if (!period || !['members', 'audit_logs'].includes(table) || !Number.isInteger(page) || page < 1) return
    await this.read<Evidence>(() => this.options.request('GET', `/business/archives/${encodeURIComponent(period)}/evidence`, undefined, { table, page, page_size: 100 }), data => { this.evidence = data })
  }
}
