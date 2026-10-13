const test=require('node:test'),assert=require('node:assert/strict')
test('0.5.0 exact targets and changelog retain original update trust',()=>{
  const candidate=require('./desktop-050.cjs'),original=require('./operations-release.cjs').trust
  assert.equal(candidate.releaseVersion,'0.5.0')
  assert.deepEqual(candidate.targets,['win10-x86','win10-x64','win11-x86','win11-x64'])
  assert.deepEqual(candidate.releaseNotes,['优化主登录页面','新增账号密码修改功能','新增搓澡师下单打印小票的功能','新增每天小票补打的功能'])
  assert.deepEqual(candidate.trust,original)
  assert.equal(original.keyId,'b26477a9ed540ad0')
})
