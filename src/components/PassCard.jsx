import { AlertTriangle, CircleCheck, CircleMinus, ChevronDown, LineChart, TrendingUp } from 'lucide-react'
import { signed, beatPct, dirOf, reasonView, passChecks, strengthLine, cautionList, hasCaution, highGapLine } from '../lib/cardFacts'

// 「過關清單」卡片（2026-11-16 Andy 核准：分頁照方向 C、卡片改方向 B）。
// 卡片檢視的每張卡、清單展開後的內容都用 PassBody 這同一個元件：
//   過關清單（每關一行、帶這檔的實際數字）→ 強在哪（只有相對優勢）→ 要小心（有才出現）
//   → 離前高（中性事實）→ 看 K 線。
// 事實全部由 lib/cardFacts.js 的純函式組裝（有單測）；新欄位缺時那幾行自動省略或改成不帶數字的說法。
// 卡片本體不再可點（審計 U1：卡片點了開 K 線、清單點了展開，行為不一致），K 線只由按鈕開。

const isNum = v => typeof v === 'number' && Number.isFinite(v)

// 漲跌：SVG 三角＋紅漲綠跌（MASTER：行情箭頭一律 SVG，不用 Unicode）
export function Tri({ dir }) {
  if (dir === 'flat') return null
  return (
    <svg className="opp-tri" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
      {dir === 'up' ? <polygon points="5,1 9.5,9 0.5,9" fill="currentColor" /> : <polygon points="0.5,1 9.5,1 5,9" fill="currentColor" />}
    </svg>
  )
}

export function Price({ p, full, compact = false }) {
  const close = p.close ?? full?.close
  const chg = full?.change, pct = full?.change_pct
  const dir = dirOf(isNum(pct) ? pct : chg)
  return (
    <div className="opp-price">
      <span className="opp-price-close mono">{close ?? '—'}</span>
      {isNum(pct) && (
        <span className={`opp-chg ${dir}`}>
          <Tri dir={dir} />
          {compact ? `${signed(pct)}%` : <>{isNum(chg) ? signed(chg, Math.abs(chg) < 10 ? 2 : 1) : ''}（{signed(pct)}%）</>}
        </span>
      )}
    </div>
  )
}

// 一檔的內容（卡片與清單展開共用）
export function PassBody({ p, gate, onChart, showReasons }) {
  const checks = passChecks(p, gate)
  const strong = strengthLine(p)
  const cautions = cautionList(p)
  const gap = highGapLine(p.close, p.recent_high20)
  // 每檔理由不一樣時才列（理由全同的那天，「依據」分頁講一次就好）；回測權重分 > 0 才列
  const extra = []
  if (p.score > 0) extra.push(<span className="opp-tag" key="score" title="回測權重加總（透明化用，不是名次）">回測權重 <b className="mono">{p.score}</b> 分</span>)
  if (showReasons) for (const r of (p.reasons || [])) {
    const v = reasonView(r)
    extra.push(<span className={`opp-tag${v.warn ? ' opp-tag-warn' : ''}`} key={`why-${r}`}>{v.warn && <AlertTriangle size={14} strokeWidth={1.75} />}{v.text}</span>)
  }
  return (
    <div className="pc-body">
      <ul className="pc-checks" aria-label="過了哪幾關">
        {checks.map(c => (
          <li key={c.key} className={`pc-check${c.ok ? '' : ' is-neutral'}`}>
            {c.ok
              ? <CircleCheck className="pc-ico" size={20} strokeWidth={1.75} aria-hidden="true" />
              : <CircleMinus className="pc-ico" size={20} strokeWidth={1.75} aria-hidden="true" />}
            <span className="sr-only">{c.ok ? '過關：' : '未打勾：'}</span>
            <span className="pc-check-k">{c.label}</span>
            <span className="pc-check-v">{c.text}</span>
          </li>
        ))}
      </ul>
      {strong && (
        <p className="pc-line pc-strong"><TrendingUp size={16} strokeWidth={2} aria-hidden="true" /><span><b>強在哪：</b>{strong}</span></p>
      )}
      {cautions.length > 0 && (
        <p className="pc-line pc-caution"><AlertTriangle size={16} strokeWidth={2} aria-hidden="true" /><span><b>要小心：</b>{cautions.join('、')}</span></p>
      )}
      {gap && <p className="pc-gap">{gap}</p>}
      {extra.length > 0 && <div className="opp-tags">{extra}</div>}
      <button className="opp-row-chart" onClick={onChart}><LineChart size={16} strokeWidth={1.75} aria-hidden="true" />看 K 線</button>
    </div>
  )
}

// 卡片檢視：不放名次號碼、不做「領先卡」特殊放大——這批清單不是排行榜。
export function CandidateCard({ p, full, gate, first, onOpen, showReasons }) {
  const edge = !!strengthLine(p)
  return (
    <article className="opp-card" aria-label={`${p.name}（${p.id}）`} {...(first ? { 'data-first-pick': '' } : {})}>
      <div className="opp-card-head">
        <div className="opp-card-id">
          <h3 className="opp-card-name" data-pick-name>{p.name}</h3>
          <div className="opp-card-sub">
            <span className="mono" data-pick-code>{p.id}</span>
            {full?.market && <>・{full.market}</>}
            {full?.industry && <>・{full.industry}</>}
          </div>
          {edge && <span className="pc-edge">相對優勢</span>}
        </div>
        <Price p={p} full={full} />
      </div>
      <PassBody p={p} gate={gate} onChart={onOpen} showReasons={showReasons} />
    </article>
  )
}

// 清單檢視：一行一檔＝名稱、代號、60 天贏過 X%、現價漲跌；「要小心」有內容時名稱旁一個橘點。
// 點一下就地展開同一份 PassBody（不跳頁），再點收合。
export function CandidateRow({ p, full, gate, first, open, onToggle, onOpen, showReasons }) {
  const beat = beatPct(p.rs_pct_60)
  const dot = hasCaution(p)
  const edge = !!strengthLine(p)
  const detailId = `opp-row-${p.id}`
  return (
    <li className={`opp-row${open ? ' open' : ''}`} data-pick-row {...(first ? { 'data-first-pick': '' } : {})}>
      <button className="opp-row-btn" onClick={onToggle} aria-expanded={open} aria-controls={detailId}>
        <span className="opp-row-main">
          <span className="opp-row-top">
            <span className="opp-row-name" data-pick-name>{p.name}</span>
            {dot && <><span className="opp-dot" aria-hidden="true" data-risk-dot /><span className="sr-only">（有要小心的地方）</span></>}
          </span>
          <span className="opp-row-sub">
            <span className="mono opp-row-code" data-pick-code>{p.id}</span>
            {beat != null && <> · 60 天贏過 <b className="mono">{beat}%</b></>}
          </span>
        </span>
        <Price p={p} full={full} compact />
        <ChevronDown className={`opp-row-chev${open ? ' is-open' : ''}`} size={18} strokeWidth={2} aria-hidden="true" />
      </button>
      {open && (
        <div className="opp-row-detail" id={detailId}>
          <p className="opp-card-sub">
            {[full?.market, full?.industry].filter(Boolean).join('・')}
            {edge && <span className="pc-edge pc-edge-inline">相對優勢</span>}
          </p>
          <PassBody p={p} gate={gate} onChart={onOpen} showReasons={showReasons} />
        </div>
      )}
    </li>
  )
}
