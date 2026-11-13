// 「各條停損線的代價」表的資料整理（純函式，有單測）。
// 來源：public/data/exit_rules_summary.json ＝ pipeline/exit_rules_summary.json 的複製，
// 由 pipeline/research_exit_rules.py 手動重跑產出（數字與 _reports/研究_出場規則_2026-11-13.md 主表同一份）。
// 任何欄位缺漏／非有限數字 → 回 null，畫面整塊不顯示表格（改顯示一句中性說明），不得出現 NaN／undefined。

const isNum = v => typeof v === 'number' && Number.isFinite(v)
const isDate = v => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)

const ROW_NUM_KEYS = ['stop_rate', 'miscut_winners', 'win_rate', 'p5', 'worst']

export function normalizeExitSummary(raw) {
  if (!raw || typeof raw !== 'object' || !Array.isArray(raw.rows)) return null
  if (!isNum(raw.n) || !isNum(raw.batches) || !isDate(raw.first_date) || !isDate(raw.last_date)) return null
  const rows = []
  for (const r of raw.rows) {
    if (!r || typeof r.label !== 'string' || !r.label) return null
    for (const k of ROW_NUM_KEYS) if (!isNum(r[k])) return null
    rows.push(r)
  }
  if (rows.length < 2) return null
  return {
    asOf: isDate(raw.as_of) ? raw.as_of : null,
    n: raw.n, batches: raw.batches, first: raw.first_date, last: raw.last_date,
    holdDays: isNum(raw.hold_days) ? raw.hold_days : 20,
    rows,
  }
}

/** 0.502 → "50.2%"；負數用全形減號 "−25.7%" */
export function fmtPct(v) {
  if (!isNum(v)) return '—'
  const s = (Math.abs(v) * 100).toFixed(1)
  return `${v < 0 && Number(s) !== 0 ? '−' : ''}${s}%`
}

export function siteRow(sum) {
  return sum?.rows?.find(r => r.key === 'site15ma') || null
}
