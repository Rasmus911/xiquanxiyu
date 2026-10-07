export type MemberCardKind = 'stored' | 'pass' | 'none'

export interface MemberCardPresentation {
  has_stored_value?: boolean
  has_pass?: boolean
  balance?: string
  pass_remaining?: number
  pass_total?: number
}

export function memberCardKinds(member: MemberCardPresentation): MemberCardKind[] {
  const kinds: MemberCardKind[] = []
  if (member.has_stored_value) kinds.push('stored')
  if (member.has_pass) kinds.push('pass')
  return kinds.length ? kinds : ['none']
}

export function memberPrimaryValue(member: MemberCardPresentation) {
  if (member.has_stored_value) return `¥${member.balance || '0.00'}`
  if (member.has_pass) return `${member.pass_remaining || 0} / ${member.pass_total || member.pass_remaining || 0} 次`
  return '尚未开卡'
}
