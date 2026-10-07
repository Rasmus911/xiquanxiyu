const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const { createPinnedExecutorClass } = require('./update-executor.cjs')

class Base {
  createRequest(options,callback) { this.requested=options; this.callback=callback; return new EventEmitter() }
  handleResponse(...args) { this.responseHandled=args[0] }
}
function executor() {
  const Pinned=createPinnedExecutorClass(Base)
  return new Pinned({origin:'https://api.pqxqxy.xyz',feedPath:'/updates/desktop/win7-x86/'})
}

test('only HTTPS target-directory requests reach the updater transport', () => {
  const ex=executor()
  ex.createRequest({protocol:'https:',hostname:'api.pqxqxy.xyz',path:'/updates/desktop/win7-x86/latest.yml?noCache=1'},()=>{})
  assert.equal(ex.requested.hostname,'api.pqxqxy.xyz')
  for(const options of [
    {protocol:'http:',hostname:'api.pqxqxy.xyz',path:'/updates/desktop/win7-x86/a.exe'},
    {protocol:'https:',hostname:'evil.invalid',path:'/updates/desktop/win7-x86/a.exe'},
    {protocol:'https:',hostname:'api.pqxqxy.xyz',path:'/updates/desktop/win7-x64/a.exe'},
    {protocol:'https:',hostname:'api.pqxqxy.xyz',path:'/updates/desktop/win7-x86/../win7-x64/a.exe'},
    {protocol:'https:',hostname:'api.pqxqxy.xyz',path:'/updates/desktop/win7-x86/%2e%2e/a.exe'},
    {protocol:'https:',hostname:'api.pqxqxy.xyz',auth:'user:secret',path:'/updates/desktop/win7-x86/a.exe'},
  ]) assert.throws(()=>ex.createRequest(options,()=>{}),/来源/)
})

test('redirect events abort rather than following another origin', () => {
  const ex=executor(),req=new EventEmitter(); let aborted=false,rejected
  req.abort=()=>{aborted=true}
  ex.addRedirectHandlers(req,{},error=>{rejected=error})
  req.emit('redirect',302,'GET','https://evil.invalid/a.exe')
  assert.equal(aborted,true); assert.match(rejected.message,/重定向/)
})

test('3xx responses are rejected and ordinary responses go to the base executor', () => {
  const ex=executor(); let rejected
  ex.handleResponse({statusCode:302,resume(){}},{},null,()=>{},error=>{rejected=error})
  assert.match(rejected.message,/重定向/); assert.equal(ex.responseHandled,undefined)
  const ok={statusCode:200}
  ex.handleResponse(ok,{},null,()=>{},()=>{}); assert.equal(ex.responseHandled,ok)
})
