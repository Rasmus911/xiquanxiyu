const {test} = require('node:test')
const assert = require('node:assert/strict')
const {serviceReceiptHtml} = require('./service-receipt.cjs')
const {receiptHtml} = require('./receipt.cjs')

test('58mm order slip highlights band and escapes every user-provided field', () => {
  const input = {receipt_kind:'order',wristband_number:'001',employee_name:'<script>bad()</script>',
    employee_username:'13800000001',created_at:'2026-10-11T01:00:00Z',
    items:[{name:'搓澡 <img src=x>',quantity:'1',total_amount:'10.00'}]}
  const html = serviceReceiptHtml(input)
  assert.match(html,/手牌\s*001/)
  assert.match(html,/非收款凭证/)
  assert.match(html,/开单员工/)
  assert.match(html,/13800000001/)
  assert.match(html,/&lt;script&gt;/)
  assert.doesNotMatch(html,/<script>|<img src=x>/)
  assert.match(html,/size:\s*58mm auto/)
  assert.match(html,/width:\s*54mm/)
  assert.match(html,/font-size:\s*28px/)
  assert.equal(receiptHtml(input),html)
})
test('settlement receipt still uses the original total and payment layout', () => {
  const html = receiptHtml({settlement:{number:'TEST-001',total_amount:'40.00'},visits:[],
    payments:[{method:'cash',amount:'40.00'}],print_attempts:1})
  assert.match(html,/TEST-001/); assert.match(html,/现金/); assert.match(html,/40.00/)
  assert.match(html,/补打小票/); assert.doesNotMatch(html,/非收款凭证/)
})
