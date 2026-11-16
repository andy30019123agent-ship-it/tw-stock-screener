import { useState, useMemo } from 'react'
import { AlertTriangle, ChevronRight, ChevronDown, LayoutGrid, List } from 'lucide-react'
import { CandidateCard, CandidateRow } from './PassCard'
import { edgeWinHeadline, staleText, gateNote } from '../lib/tierVerdict'
import { readView, writeView } from '../lib/viewPref'
import { commonReasons, sortRuleText, splitMain, smallPoolText } from '../lib/cardFacts'

// 「今天」分頁的候選清單（2026-11-16 三分頁改版，Andy 核准方向 A＋C、卡片改方向 B）。
// 這裡只放股票：一句關鍵事實＋狀態型警示（一律首屏可見）＋卡片／清單切換＋兩組候選。
// 原本同一個元件裡的「這些數字怎麼來的」、成績單搬到 BasisTab；權重表、持有口徑與停損代價搬到工具分頁。
//
// 2026-11-16 改（Andy 核准「小改＋觀察」）：不再按 tier 分「相對優勢／其他候選」兩組，
// 改成照 JSON 原始順序切兩段——前 main_n 檔是主名單、其餘收進預設收合的「第 main_n+1 名以後」
// （不叫「其他候選」：那個詞在「依據」分頁的證據表專指沒排進相對優勢的候選，避免撞名）。
// 後端排序已經是「分數 → 相對優勢先 → 60 日強弱」，相對優勢自然排在前面，前端不重新排序。
// 原本每組各有一層「再看 N 檔」（preview_n）的分頁，跟主名單／其他候選重疊，拿掉，只留一層收合。
// 卡片與清單兩種檢視吃同一個陣列、同一個切片。
const NEUTRAL = '歷史數字暫時取不到，有分類也可能虧錢'

function PickList({ list, view, byId, gate, onPick, showReasons, markFirst }) {
  const [openIds, setOpenIds] = useState(() => new Set())
  const toggle = id => setOpenIds(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  if (view === 'list') {
    return (
      <ul className="opp-rows">
        {list.map((p, i) => (
          <CandidateRow key={p.id} p={p} full={byId.get(p.id)} gate={gate} first={markFirst && i === 0}
            open={openIds.has(p.id)} onToggle={() => toggle(p.id)} onOpen={() => onPick(p)} showReasons={showReasons} />
        ))}
      </ul>
    )
  }
  return (
    <div className="opp-cards">
      {list.map((p, i) => (
        <CandidateCard key={p.id} p={p} full={byId.get(p.id)} gate={gate} first={markFirst && i === 0}
          onOpen={() => onPick(p)} showReasons={showReasons} />
      ))}
    </div>
  )
}

function ViewToggle({ view, onChange }) {
  return (
    <div className="opp-view" role="group" aria-label="候選顯示方式">
      {[['list', '清單', List], ['cards', '卡片', LayoutGrid]].map(([k, label, Icon]) => (
        <button key={k} data-view-btn={k} className={`opp-view-btn${view === k ? ' on' : ''}`}
          aria-pressed={view === k} onClick={() => onChange(k)}>
          <Icon size={16} strokeWidth={1.75} aria-hidden="true" />{label}
        </button>
      ))}
    </div>
  )
}

// opp＝opportunities.json（App 抓好傳進來；undefined＝還在載入、null＝抓不到）
export default function Opportunities({ opp, stocks, onPick, tierStats, onGoBasis, engineStatus }) {
  const [showOther, setShowOther] = useState(false)   // 「其他候選」收合區
  // 卡片／清單檢視（記住上次選擇；2026-11-16 起沒存過偏好的預設是清單，見 lib/viewPref.js）
  const [view, setView] = useState(() => readView())
  const changeView = v => { setView(v); writeView(v) }

  const byId = useMemo(() => new Map((stocks || []).map(s => [s.id, s])), [stocks])

  // 開 K 線彈窗：優先用 screener.json 的完整資料（欄位齊全），
  // 抓不到（如尚未載入）才用 pick 本身的欄位墊底，讓彈窗至少開得起來。pick 一併傳出（視窗要它的月線／前高）。
  const handlePick = p => {
    const full = byId.get(p.id)
    onPick?.(full || {
      ...p,
      ma20: p.support_ma20 ?? null,
      change: 0, change_pct: 0,
      foreign_streak: 0, trust_streak: 0,
      avg_vol_lots: null,
    }, p)
  }

  if (opp === undefined) return null   // 還在載入：App 那層已經有「載入資料中」
  // ⚠️ 2026-07-25：抓不到 opportunities.json 不能靜默省略（那是主功能，不是裝飾）。
  // 分三種情況：檔案缺（管線問題）／有檔但零檔（真的沒選到）／正常。
  if (!opp) return (
    <section className="opp opp-fail" data-region="候選情報">
      <p>
        <b>今日候選情報暫時取不到</b>——這通常是資料管線出問題（不是「今天沒選到股」）。
        {engineStatus && engineStatus !== 'ok' && <><br />管線回報：<code>{engineStatus}</code></>}
        <br />其他選股條件與戰績仍可正常使用；隔天自動更新後會恢復。
      </p>
    </section>
  )
  if (!opp.picks || opp.picks.length === 0) return (
    <section className="opp opp-fail" data-region="候選情報">
      {smallPoolText(opp.gate, 0)
        ? <p><b>{smallPoolText(opp.gate, 0)}</b>（過「{opp.gate.label}」的股票太少，名單產出正常、就是零檔）——這是有效結論，可以觀望。</p>
        : <p><b>今天沒有個股通過門檻</b>（名單產出正常、就是零檔）——這是正常結果，不必找原因。</p>}
    </section>
  )

  const { main, other } = splitMain(opp.picks, opp.main_n)
  const otherFrom = main.length + 1   // 收合區從第幾名開始（＝main_n+1；不寫死 21）
  const smallPool = smallPoolText(opp.gate, opp.picks.length)
  const gNote = gateNote(opp.gate, tierStats)
  const stale = staleText(tierStats)
  const common = commonReasons(opp.picks)
  const headline = edgeWinHeadline(tierStats)
  const sortRule = sortRuleText(opp.picks)
  const anyDot = view === 'list'

  return (
    <section className="opp" data-region="候選情報">
      {/* 一句關鍵事實（數字讀 tier_stats.json）＋狀態型警示。狀態型警示（門檻沒套用、統計過期）
          不屬於可收合的說明，出現時一律在這裡、首屏可見（MASTER 2026-11-16 第 4 點）。 */}
      <div className="opp-today">
        <p className="opp-today-main">
          {headline || NEUTRAL}；<b>排前面不代表比較會賺，買不買你決定</b>。
          <a className="opp-basis-link" href="#basis" onClick={onGoBasis}>看依據</a>
        </p>
        {opp.gate && !opp.gate.applied && (opp.gate.reason === 'rs_unavailable' || opp.gate.reason === 'pool_too_small') && (
          <p className="opp-sub">
            {opp.gate.reason === 'rs_unavailable'
              ? <b className="opp-degraded"><AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" />相對強弱資料今日不可用，「{opp.gate.label}」門檻未套用（改為全市場）</b>
              : <b className="opp-degraded"><AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" />今日符合「{opp.gate.label}」的候選僅 {opp.gate.pool} 檔（不足 {opp.gate.min_pool}），門檻未套用</b>}
          </p>
        )}
        {smallPool && (
          <p className="opp-sub"><b className="opp-degraded"><AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" />{smallPool}</b></p>
        )}
        {gNote && (
          <p className="opp-sub"><b className="opp-degraded"><AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" />{gNote}</b></p>
        )}
        {stale && (
          <p className="opp-sub"><b className="opp-degraded"><AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" />{stale}，上面先不引用數字</b></p>
        )}
      </div>

      <div className="opp-listhead">
        <h2 className="opp-listtitle">主名單 <span className="mono">{main.length}</span> 檔</h2>
        <ViewToggle view={view} onChange={changeView} />
      </div>
      {/* 圖例一句：排序依據（不寫戰績數字，會被每週重算推翻）＋（清單檢視才有的）橘點說明 */}
      <p className="opp-legend opp-legend-sm">
        <span>
          {sortRule}。
          {anyDot && <span className="opp-dot-legend"><span className="opp-dot" aria-hidden="true" />橘點＝有風險標記，點開看</span>}
        </span>
      </p>

      <PickList list={main} view={view} byId={byId} gate={opp.gate} onPick={handlePick} showReasons={!common} markFirst />

      {other.length > 0 && (
        <div className="opp-other">
          <button className="opp-fold" onClick={() => setShowOther(v => !v)} aria-expanded={showOther}>
            <span>第 {otherFrom} 名以後（{other.length} 檔）<small>同樣過了所有關卡，排在主名單後面</small></span>
            {showOther ? <ChevronDown size={20} strokeWidth={2} /> : <ChevronRight size={20} strokeWidth={2} />}
          </button>
          {showOther && (
            <PickList list={other} view={view} byId={byId} gate={opp.gate} onPick={handlePick} showReasons={!common} markFirst={false} />
          )}
        </div>
      )}
    </section>
  )
}
