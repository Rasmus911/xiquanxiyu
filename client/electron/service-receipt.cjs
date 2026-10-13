const { escapeHtml } = require('./receipt-escape.cjs')

function serviceReceiptHtml(receipt) {
  const items = Array.isArray(receipt.items) ? receipt.items : []
  const attempts = Number(receipt.print_attempts || 0)
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    @page { size: 58mm auto; margin: 2mm; }
    body { width: 54mm; margin: 0; color: #000; font-family: "Microsoft YaHei", sans-serif; font-size: 11px; }
    h1 { font-size: 16px; margin: 2px 0 6px; text-align: center; }
    .band { font-size: 28px; font-weight: 900; text-align: center; margin: 10px 0; }
    .divider { border-top: 1px dashed #000; margin: 7px 0; }
    .line { display: flex; justify-content: space-between; gap: 6px; margin: 5px 0; }
    .line span:first-child { flex: 1; word-break: break-all; }
    .center { text-align: center; } .reprint { border: 1px solid #000; padding: 2px; text-align: center; }
  </style></head><body>
    <h1>${escapeHtml(receipt.store_name || '平泉市溪泉洗浴')}</h1>
    <div class="center">下单小票 · 非收款凭证</div>
    ${attempts > 0 ? `<div class="reprint">补打小票 第 ${attempts + 1} 次</div>` : ''}
    <div class="band">手牌 ${escapeHtml(receipt.wristband_number)}</div>
    <div>开单员工：${escapeHtml(receipt.employee_name)} (${escapeHtml(receipt.employee_username)})</div>
    <div>开单时间：${escapeHtml(receipt.created_at)}</div>
    <div class="divider"></div>
    ${items.map(item => `<div class="line"><span>${escapeHtml(item.name)} × ${escapeHtml(item.quantity)}</span><span>¥${escapeHtml(item.total_amount)}</span></div>`).join('')}
    <div class="divider"></div><div class="center">仅本次下单项目，离店统一结账</div>
  </body></html>`
}
module.exports = { serviceReceiptHtml }
