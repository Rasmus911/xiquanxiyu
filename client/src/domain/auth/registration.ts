export const registrationRoles = [
  { value: 'male_scrubber', label: '男搓澡' },
  { value: 'female_scrubber', label: '女搓澡' },
  { value: 'floor_attendant', label: '楼层服务员' },
] as const
export interface RegistrationForm { username: string; display_name: string; role: string; password: string; confirmation: string; code: string }
export function registrationPayload(form: RegistrationForm, terminal: string) {
  const username = form.username.trim(), display_name = form.display_name.trim(), code = form.code.trim()
  if (!/^1[0-9]{10}$/.test(username)) throw new Error('请输入 11 位手机号，仅限数字')
  if (!display_name || form.display_name.length > 80 || /[\u0000-\u001f]/.test(form.display_name)) throw new Error('姓名不能为空，最多 80 字')
  if (!registrationRoles.some(role => role.value === form.role)) throw new Error('请选择员工岗位')
  if (form.password.length < 8 || form.password.length > 128) throw new Error('密码需要 8–128 位')
  if (form.password !== form.confirmation) throw new Error('两次密码不一致')
  if (!/^[0-9]{6}$/.test(code)) throw new Error('请输入管理员提供的六位注册授权码')
  if (!terminal.trim() || terminal.trim().length > 80) throw new Error('请先配置并注册当前桌面终端')
  return { username, display_name, role: form.role, password: form.password, code, terminal_code: terminal.trim(), client_channel: 'desktop' as const }
}
export function registrationIdentity(value: unknown, body: ReturnType<typeof registrationPayload>) {
  const identity = value as Record<string, unknown> | null
  const fields = ['id', 'username', 'display_name', 'role', 'is_active', 'allowed_channels']
  if (!identity || Object.keys(identity).length !== fields.length || Object.keys(identity).some(key => !fields.includes(key))
    || typeof identity.id !== 'string' || !identity.id || identity.username !== body.username || identity.display_name !== body.display_name
    || identity.role !== body.role || identity.is_active !== true || !Array.isArray(identity.allowed_channels)
    || identity.allowed_channels.length !== 1 || identity.allowed_channels[0] !== 'desktop') throw new Error('注册结果无法确认，请使用相同信息重试')
  return body.username
}
// Memory only: never use the business-request storage helper for passwords/code.
export class RegistrationRetry {
  private fingerprint = ''
  private requestKey = ''
  key(body: ReturnType<typeof registrationPayload>) {
    const fingerprint = JSON.stringify(body)
    if (fingerprint !== this.fingerprint || !this.requestKey) { this.fingerprint = fingerprint; this.requestKey = crypto.randomUUID() }
    return this.requestKey
  }
  clear() { this.fingerprint = ''; this.requestKey = '' }
}
