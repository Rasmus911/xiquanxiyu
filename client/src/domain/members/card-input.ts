/** Readers terminate a digit string with CR/LF; whitespace inside is never a UID. */
export function normalizeCardInput(value: string): string | null {
  const uid = value.replace(/[\r\n]+$/, '')
  return /^[0-9]{1,64}$/.test(uid) ? uid : null
}
