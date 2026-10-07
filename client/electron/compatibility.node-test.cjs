const test = require('node:test')
const assert = require('node:assert/strict')
const { windowBounds, diagnostics, readRenderingPreference } = require('./compatibility.cjs')

test('initial and minimum window dimensions fit a scaled work area', () => {
  for (const workArea of [{width:819,height:580},{width:1024,height:728},{width:1920,height:1040}]) {
    const result=windowBounds(workArea)
    assert.ok(result.width<=workArea.width && result.height<=workArea.height)
    assert.ok(result.minWidth<=result.width && result.minHeight<=result.height)
  }
  assert.deepEqual(windowBounds({width:1920,height:1040}),{width:1440,height:900,minWidth:1024,minHeight:700})
})

test('diagnostics are cloneable and exclude configuration/authentication secrets', () => {
  const result=diagnostics({profile:{targetId:'win7-x86',arch:'ia32',buildId:'fixture',releaseTrust:{testOnly:true}},
    versions:{electron:'22.3.27',chrome:'108',node:'16.17.1'},osRelease:'6.1.7601',softwareRendering:true,password:'secret'})
  assert.equal(result.targetId,'win7-x86'); assert.equal(result.appArch,'ia32')
  assert.equal(result.softwareRendering,true); assert.equal(result.testOnly,true)
  assert.equal(JSON.stringify(result).includes('secret'),false)
  assert.deepEqual(structuredClone(result),result)
})

test('only an explicit boolean preference enables software rendering', () => {
  assert.equal(readRenderingPreference('{"softwareRendering":true}'),true)
  for(const text of ['{"softwareRendering":"true"}','{"softwareRendering":false}','{','null','{}']) {
    assert.equal(readRenderingPreference(text),false)
  }
})
