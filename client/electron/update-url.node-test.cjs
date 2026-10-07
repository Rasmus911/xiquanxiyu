const test = require('node:test')
const assert = require('node:assert/strict')

const { derivePolicyUrl, deriveUpdateUrl } = require('./update-url.cjs')
const { deriveTargetUrls } = require('./update-url.cjs')

test('derives updater feed and release policy from the HTTPS API URL', () => {
  const serverUrl = 'https://api.pqxqxy.xyz/api'
  assert.equal(deriveUpdateUrl(serverUrl), 'https://api.pqxqxy.xyz/updates/')
  assert.equal(derivePolicyUrl(serverUrl), 'https://api.pqxqxy.xyz/releases/client-policy.json')
})

test('rejects non-HTTPS, credentialed and non-api server URLs', () => {
  assert.equal(deriveUpdateUrl('http://api.pqxqxy.xyz/api'), null)
  assert.equal(derivePolicyUrl('https://user:pass@api.pqxqxy.xyz/api'), null)
  assert.equal(derivePolicyUrl('https://api.pqxqxy.xyz/v1'), null)
})

test('new profiles use only their compiled release source and never the global feed', () => {
  assert.deepEqual(deriveTargetUrls('https://api.pqxqxy.xyz/api', 'win7-x86'), {
    feedUrl:'https://api.pqxqxy.xyz/updates/desktop/win7-x86/',
    policyUrl:'https://api.pqxqxy.xyz/releases/desktop/win7-x86.json',
    origin:'https://api.pqxqxy.xyz',
  })
  for (const server of ['http://api.pqxqxy.xyz/api','https://evil.invalid/api','https://u:p@api.pqxqxy.xyz/api','https://api.pqxqxy.xyz/api?feed=evil']) {
    assert.equal(deriveTargetUrls(server,'win7-x86'),null)
  }
  assert.equal(deriveTargetUrls('https://api.pqxqxy.xyz/api','../bad'),null)
})
