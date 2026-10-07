function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

const paymentNames = { cash: '现金', wechat: '微信', alipay: '支付宝', balance: '会员储值' }

function receiptHtml(receipt) {
  const settlement = receipt.settlement || {}
  const visits = Array.isArray(receipt.visits) ? receipt.visits : []
  const attempts = Number(receipt.print_attempts || 0)
  const visitHtml = visits.map((visit) => `
    <section>
      <div class="line strong"><span>手牌 ${escapeHtml(visit.wristband_number)}</span><span>¥${escapeHtml(visit.amount)}</span></div>
      ${(visit.items || []).map((item) => `
        <div class="line item"><span>${escapeHtml(item.name)} × ${escapeHtml(item.quantity)}${Number(item.covered_quantity) > 0 ? `<small> · 套票包含 ${escapeHtml(Number(item.covered_quantity))} 份</small>` : ''}</span><span>¥${escapeHtml(item.total_amount)}</span></div>
      `).join('')}
    </section>
  `).join('')
  const paymentHtml = (receipt.payments || []).map((payment) => `
    <div class="line"><span>${escapeHtml(paymentNames[payment.method] || payment.method)}</span><span>¥${escapeHtml(payment.amount)}</span></div>
  `).join('')
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    @page { size: 58mm auto; margin: 2mm; }
    body { width: 54mm; margin: 0; color: #000; font-family: "Microsoft YaHei", sans-serif; font-size: 11px; }
    h1 { font-size: 17px; text-align: center; margin: 2px 0 6px; }
    .center { text-align: center; }
    .line { display: flex; justify-content: space-between; gap: 6px; margin: 3px 0; }
    .line span:first-child { flex: 1; word-break: break-all; }
    .strong { font-weight: 700; }
    .item { padding-left: 3px; }
    .divider { border-top: 1px dashed #000; margin: 6px 0; }
    .total { font-size: 15px; font-weight: 700; }
    .reprint { border: 1px solid #000; padding: 2px; text-align: center; font-weight: 700; }
  </style></head><body>
    <h1>${escapeHtml(receipt.store_name || '溪泉洗浴')}</h1>
    ${attempts > 0 ? `<div class="reprint">补打小票 第 ${attempts + 1} 次</div>` : ''}
    <div>单号：${escapeHtml(settlement.number)}</div>
    <div>时间：${escapeHtml(settlement.completed_at)}</div>
    <div class="divider"></div>
    ${visitHtml}
    <div class="divider"></div>
    <div class="line total"><span>合计</span><span>¥${escapeHtml(settlement.total_amount)}</span></div>
    ${paymentHtml}
    <div class="divider"></div>
    <div class="center">谢谢惠顾，请携带好随身物品</div>
  </body></html>`
}

module.exports = { receiptHtml }
