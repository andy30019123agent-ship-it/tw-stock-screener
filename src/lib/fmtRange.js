// 全站共用的區間格式（2026-11-13）：「−4.06%～+3.39%」——全形減號、全形波浪號，缺值回 "—"。
// 之前各處各寫各的，出現過「-4.06–3.39%」這種負號與連字號分不清的寫法。
// sign=true：每個端點都帶 +/−（報酬、差距類，會跨 0）；sign=false：只有負數帶 −（勝率這類不會是負的）。
const isNum = v => typeof v === 'number' && Number.isFinite(v)

export function fmtRange(ci, { digits = 2, unit = '%', sign = true } = {}) {
  if (!Array.isArray(ci) || ci.length !== 2 || !isNum(ci[0]) || !isNum(ci[1])) return '—'
  const one = v => {
    const s = Math.abs(v).toFixed(digits)
    const zero = Number(s) === 0
    return `${v < 0 && !zero ? '−' : sign && !zero && v > 0 ? '+' : ''}${s}${unit}`
  }
  return `${one(ci[0])}～${one(ci[1])}`
}
