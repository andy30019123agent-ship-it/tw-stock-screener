import { useState, useEffect } from 'react'
import { Target, TrendingUp, Calendar, AlertTriangle, ChevronRight, ChevronDown, Sparkles, Award, Coins, Info } from 'lucide-react'
import PositionPlan from './PositionPlan'
import OutcomeShape from './OutcomeShape'

// 候選情報三分類（2026-07-26 誠實化）：tier 由後端 opportunities.py 依「當日候選池內百分位」算好，
// 前端只負責分組顯示，不重新排序、不重新判斷。
// ⚠️ 名次沒有證據（2026-07-25 實測：前 3 名 vs 第 4~8 名 t=-0.22，第 2 名反而最差）——
// 每組清單一律照 JSON 給的原始順序顯示，不做任何「誰比較好」的二次排序。
const TIER_META = {
  // 「雙優」是全站唯一的視覺主角（2026-07-26 單欄故事線核准方向第 2 條）：
  // _reports/驗證_雙優分類_2026-07-26.md 實測它是三個分類裡唯一同時拿到最高賺錢機率、
  // 最高上檔幅度、且中位數不是負的一組。lede 刻意不寫死那次測出的百分比——數字有效期只到
  // 下次重新回測，精確數字交給下方「這些數字怎麼來的」一律讀 tier_stats.json 現算，這裡只講結論。
  both: {
    label: '雙優', Icon: Sparkles, blurb: '成交金額與 20 日乖離都排在候選池前段',
    // lede 刻意短——完整根據（實測賺錢機率／上檔幅度／中位數）放在下方「這些數字怎麼來的」，
    // 這裡只給結論，不然首屏會被長文字擋住看不到卡片（2026-07-26 審計主要抱怨）。
    lede: '三個分類裡最有根據的一組：兩個條件都排前段，唯一同時賺得勤又賺得多的一類（見下方「這些數字怎麼來的」）。',
  },
  win: { label: '勝率偏優', Icon: Award, blurb: '成交金額排在候選池前段——歷史上這組單檔賺錢機率較高' },
  // ⚠️ 2026-07-26 實測（_reports/驗證_雙優分類_2026-07-26.md）：「只有乖離高」的賺錢機率 42.5%，
  // 比「兩個條件都不符合」的 42.6% 還低一點——乖離單獨看只增加賺賠「幅度」，不增加「頻率」。
  // 所以這個分類的說明**絕對不可以**暗示勝率比較好，只能講幅度。
  return: { label: '報酬偏優', Icon: Coins, blurb: '20 日乖離排在候選池前段、成交金額不在後段——歷史上這組賺的時候賺比較多（+13.4% vs 未分類的 +11.4%），但賺錢的「次數」並沒有比較多' },
}
const TIER_ORDER = ['both', 'win', 'return']

const fmtPct01 = v => (v == null ? '—' : `${Math.round(v * 100)}%`)

// feat_pct 的四個特徵怎麼標：turnover／bias20_pct 是分類真正依據，可以講「排在前段」；
// high20_gap 重算後方向與舊研究相反（不穩定特徵），rs_pct_60 目前也沒進分類——
// 這兩個只顯示數值當事實，UI 不可加「偏優」「加分」之類的字眼（硬性限制，見實作計畫 Task 8）。
const FEAT_LABELS = {
  turnover: '成交金額位階',
  bias20_pct: '乖離位階',
  high20_gap: '距前高位階',
  rs_pct_60: '相對強弱位階',
}

// 「這套的優勢在賺賠幅度、不是勝率」——今天重算後的頭條數字，一律從 tier_stats.json 算，不寫死。
// 用 turnover 這個特徵（真正拿來分「勝率偏優」的依據）算：高／低兩層的賺錢機率、以及高層的期望值。
function HonestyCallout({ tierStats }) {
  const t = tierStats?.features?.turnover
  // 🔴 2026-07-26 Codex 複查：原本只檢查「三層物件存不存在」，但零樣本的層**物件存在、
  // 欄位全是 null**（tier_stats.py 的 _tier_summary 在 n==0 時如此）。下面直接做
  // `v.win_rate * 100`、`hi.ci90[0]`，遇到那種層會丟 TypeError，被 ErrorBoundary 攔成
  // 「整個候選區變錯誤卡」——使用者連候選清單都看不到，只因為一張說明卡的統計缺樣本。
  // 這裡改成檢查「真的算得出數字」，缺樣本就走上面那條溫和降級。
  const usable = v => v && v.win_rate != null && v.avg_win_pct != null
    && v.avg_loss_pct != null && Array.isArray(v.ci90)
  if (!usable(t?.high) || !usable(t?.mid) || !usable(t?.low)) {
    return (
      <p className="opp-honesty">
        <Info size={15} strokeWidth={1.75} />
        <span>條件層級的歷史分佈暫時取不到，候選清單本身仍正常——買哪幾檔、買不買由你決定。</span>
      </p>
    )
  }
  const { high: hi, mid, low: lo } = t
  const winPct = v => (v.win_rate * 100).toFixed(1)
  const allBelowHalf = [hi, mid, lo].every(x => x.win_rate < 0.5)
  const ev = hi.win_rate * hi.avg_win_pct + (1 - hi.win_rate) * hi.avg_loss_pct
  return (
    <p className="opp-honesty">
      <Info size={15} strokeWidth={1.75} />
      <span>
        成交金額最高的三分之一，單檔歷史賺錢機率 <b>{winPct(hi)}%</b>；最低的三分之一 <b>{winPct(lo)}%</b>
        {allBelowHalf
          ? <>——<b>三層都不到一半</b></>
          : <>（中段 {winPct(mid)}%）</>}
        。這套的優勢在賺賠幅度（賺時 <b className="good">+{hi.avg_win_pct.toFixed(1)}%</b>、
        賠時 <b className="bad">−{Math.abs(hi.avg_loss_pct).toFixed(1)}%</b>，
        期望值 <b className={ev >= 0 ? 'good' : 'bad'}>{ev >= 0 ? '+' : ''}{ev.toFixed(2)}%</b>），不是在勝率。
        <small className="opp-ci-note">
          （{hi.blocks} 批獨立樣本，90% CI 高層 {hi.ci90[0]}–{hi.ci90[1]}% ／ 低層 {lo.ci90[0]}–{lo.ci90[1]}%）
        </small>
      </span>
    </p>
  )
}

// 一張候選卡：不放名次號碼、不做「領先卡」特殊放大——這批清單不是排行榜（見上方 TIER_META 註解）。
function CandidateCard({ p, onClick }) {
  const bias = p.support_ma20 ? ((p.close - p.support_ma20) / p.support_ma20 * 100) : null
  const fp = p.feat_pct || {}
  return (
    <div className="opp-card" onClick={onClick}>
      <div className="opp-card-top">
        <div className="opp-name">
          <span className="opp-sid">{p.id}</span>
          <span className="opp-sname">{p.name}</span>
        </div>
        {p.score > 0 && <span className="opp-score" title="回測權重加總（透明化用，不是名次）">{p.score}<small>分</small></span>}
      </div>

      <div className="opp-reasons">
        {(p.reasons || []).map(r => <span className="opp-reason" key={r}>{r}</span>)}
      </div>

      <div className="opp-refs">
        <span>現價 <b>{p.close}</b></span>
        {p.support_ma20 && (
          <span>MA20 <b>{p.support_ma20}</b>{p.close >= p.support_ma20 ? '撐' : '壓'}</span>
        )}
        {p.recent_high20 && <span>近高 <b>{p.recent_high20}</b></span>}
        {p.rs20 != null && (
          <span className={`opp-rs ${p.rs20 >= 0 ? 'pos' : 'neg'}`}>
            RS {p.rs20 >= 0 ? '+' : ''}{p.rs20}
          </span>
        )}
        {p.revenue_yoy != null && (
          <span>營收 YoY <b className={p.revenue_yoy >= 0 ? 'good' : ''}>{p.revenue_yoy >= 0 ? '+' : ''}{p.revenue_yoy}%</b></span>
        )}
      </div>

      {/* 候選池內百分位——事實，不是評語。high20_gap 不可標「偏優」（重算後方向不穩定）。 */}
      <div className="opp-featpct">
        {(['turnover', 'bias20_pct', 'high20_gap', 'rs_pct_60']).map(k => (
          fp[k] != null && (
            <span className="opp-fp" key={k}>{FEAT_LABELS[k]} <b>{fmtPct01(fp[k])}</b></span>
          )
        ))}
      </div>

      <div className="opp-flags">
        {p.earnings_date && (
          <span className="opp-earn"><Calendar size={12} strokeWidth={1.75} />{p.earnings_date.slice(5)} 法說會</span>
        )}
        {(p.risk_flags || []).map(f => (
          <span className="opp-risk" key={f}><AlertTriangle size={12} strokeWidth={1.75} />{f}</span>
        ))}
        {bias != null && bias <= 15 && bias >= 8 && (
          <span className="opp-muted">乖離 {bias.toFixed(0)}%</span>
        )}
      </div>
    </div>
  )
}

// 一個分類分區（雙優／勝率偏優／報酬偏優／其他候選）：標題講清楚共幾檔、列前幾檔，
// 旁邊一律附「不是好壞排名」的提醒——這是 2026-07-25 實測推翻過的東西，不可回歸。
function TierSection({ tierKey, label, Icon, blurb, lede, variant = 'secondary', list, previewN, onPick }) {
  const [expanded, setExpanded] = useState(false)
  if (!list.length) return null
  const shown = expanded ? list : list.slice(0, previewN)
  const hasMore = list.length > shown.length
  return (
    <div className={`opp-tier opp-tier--${variant}`} data-tier={tierKey}>
      <div className="opp-tier-head">
        <span className="opp-tier-title">
          {Icon && <Icon size={variant === 'primary' ? 17 : 15} strokeWidth={1.75} />}{label}
          <span className="opp-tier-count">
            共 {list.length} 檔{list.length > previewN && !expanded ? `，這裡列前 ${previewN} 檔` : '（已全部列出）'}
          </span>
        </span>
      </div>
      {lede
        ? <p className="opp-tier-lede">{lede}</p>
        : blurb && <p className="opp-tier-blurb">{blurb}</p>}
      <p className="opp-tier-note">照候選清單原始順序，不是好壞排名</p>
      <div className="opp-cards">
        {shown.map(p => <CandidateCard key={p.id} p={p} onClick={() => onPick(p)} />)}
      </div>
      {hasMore && (
        <button className="opp-more" onClick={() => setExpanded(true)}>
          展開全部 {list.length} 檔<ChevronDown size={14} strokeWidth={2} />
        </button>
      )}
      {expanded && list.length > previewN && (
        <button className="opp-more" onClick={() => setExpanded(false)}>收合</button>
      )}
    </div>
  )
}

// 勝率榜一格：主數字＝平均超額（pp，權重依據），次行＝超額勝率與樣本。
// 樣本不足（validated=false）整格轉灰＋提示，提醒「別信這個數字」；無資料顯示「—」。
function WinCell({ c, minS, active }) {
  const cls = `wq-cell${active ? ' wq-active' : ''}`
  if (!c || !c.samples || c.avg_excess == null) return <td className={`${cls} wq-empty`}>—</td>
  const weak = !c.validated
  const exc = c.avg_excess
  const excCls = weak ? '' : exc > 0 ? 'good' : exc < 0 ? 'bad' : ''
  const wr = c.excess_win_rate != null ? Math.round(c.excess_win_rate * 100) : null
  return (
    <td className={`${cls}${weak ? ' wq-weak' : ''}`}
      title={weak ? `樣本 ${c.samples}，不足 ${minS}，僅供參考` : `超額勝率 ${wr}%、樣本 ${c.samples}`}>
      <span className={`wq-exc ${excCls}`}>{exc >= 0 ? '+' : ''}{exc}<small>pp</small></span>
      <span className="wq-sub">勝 {wr != null ? `${wr}%` : '—'} · {c.samples}</span>
    </td>
  )
}

// 趨勢符號：SVG 三角（取代 Unicode ↑↓→，MASTER 第 4 節第 6 點——表格內行情箭頭一律用 SVG）。
function TrendGlyph({ t }) {
  if (t === 'flat') return <span className="wq-trend-flat" aria-hidden="true">─</span>
  return (
    <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      {t === 'up' ? <polygon points="12 3 22 20 2 20" /> : <polygon points="12 21 2 4 22 4" />}
    </svg>
  )
}

// 趨勢箭頭：近半年 vs 歷史的平均超額（兩者都要夠樣本才判，否則不顯示，避免拿雜訊嚇人）。
function trendOf(row) {
  const r = row['6m'], h = row['all']
  if (!r?.validated || !h?.validated || r.avg_excess == null || h.avg_excess == null) return null
  const d = r.avg_excess - h.avg_excess
  return d >= 0.1 ? 'up' : d <= -0.1 ? 'down' : 'flat'
}

// 候選情報區塊：讀 opportunities.json（跨 repo 契約）＋ scoreboard.json ＋ signal_weights/windows.json。
// 2026-07-26 誠實化：從「每天固定推 N 檔」改成「輸出全部合格候選＋三分類，交給 Andy 自己選」
// （Andy 拍板：不用幫我配好購買組合）。picks 不再截斷，檔數一律讀 opp.pool_n，不寫死。
// 都採「抓不到就靜默省略該部分」，不讓這區拖垮既有選股頁。
export default function Opportunities({ stocks, onPick, onCount, engineStatus, tierStats }) {
  const [opp, setOpp] = useState(null)
  const [board, setBoard] = useState(null)
  const [weights, setWeights] = useState(null)
  const [windows, setWindows] = useState(null)   // 多時間窗勝率榜（signal_windows.json）
  const [sortWin, setSortWin] = useState('all')   // 目前聚焦／排序的時間窗欄
  const [showWeights, setShowWeights] = useState(false)
  const [showOther, setShowOther] = useState(false)   // 「其他候選（未達分類門檻）」收合區
  // 2026-07-26 單欄故事線改版：候選情報是全站主角，手機也預設展開——原本手機收合＋要點「展開」
  // 才看得到第一檔股票，審計實測要多捲 1 屏＋多點 1 次，跟「故事線」的敘事順序互相矛盾。
  // 收合鈕還留著（供看完想收起來的人用），只是初始狀態全斷點都是 open。
  const [open, setOpen] = useState(true)

  // 點卡片開 K 線彈窗：優先用 screener.json 的完整資料（欄位齊全），
  // 抓不到（如尚未載入）才用 pick 本身的欄位墊底，讓彈窗至少開得起來。
  const handlePick = p => {
    const full = stocks?.find(s => s.id === p.id)
    onPick?.(full || {
      ...p,
      ma20: p.support_ma20 ?? null,
      change: 0, change_pct: 0,
      foreign_streak: 0, trust_streak: 0,
      avg_vol_lots: null,
    })
  }

  useEffect(() => {
    const base = import.meta.env.BASE_URL
    const grab = (name, set) =>
      fetch(`${base}data/${name}.json`)
        .then(r => (r.ok ? r.json() : null)).then(set).catch(() => set(null))
    grab('opportunities', d => { setOpp(d); onCount?.(d?.pool_n ?? d?.picks?.length ?? 0) })
    grab('scoreboard', setBoard)
    grab('signal_weights', setWeights)
    grab('signal_windows', setWindows)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])


  // ⚠️ 2026-07-25：原本這裡 `return null`＝抓不到就整塊消失，看起來像「今天沒選到股」。
  // 實際上 2026-07-25 晚間就是管線的引擎掛掉、`opportunities.json` 根本沒產出，
  // 而畫面完全沒有異狀 → 靜默省略在這裡是錯的（那是主功能，不是裝飾）。
  // 現在分三種情況：檔案缺（管線問題）／有檔但零檔（真的沒選到）／正常。
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
      <p><b>今天沒有個股通過門檻</b>（名單產出正常、就是零檔）——這是正常結果，不必找原因。</p>
    </section>
  )

  // 勝率榜（多時間窗）衍生值：優先用 signal_windows.json，缺了才退回舊的單欄 signal_weights.json。
  const win = windows?.signals ? windows : null
  const winCols = win?.windows || []
  const minS = win?.min_sample || weights?.min_sample || 30
  const sortedRows = win
    ? Object.entries(win.signals).slice().sort((a, b) => {
        const av = a[1][sortWin], bv = b[1][sortWin]
        const ax = av?.validated && av.avg_excess != null ? av.avg_excess : -Infinity
        const bx = bv?.validated && bv.avg_excess != null ? bv.avg_excess : -Infinity
        return bx - ax
      })
    : []
  const activeWeights = win
    ? Object.values(win.signals).map(r => ({ label: r.label, w: r.all?.weight || 0 }))
        .filter(x => x.w > 0).sort((a, b) => b.w - a.w)
    : []

  const poolN = opp.pool_n ?? opp.picks.length
  const previewN = opp.preview_n || 10
  const tiered = { both: [], win: [], return: [], other: [] }
  for (const p of opp.picks) (tiered[p.tier] || tiered.other).push(p)

  return (
    <section className={`opp ${open ? 'opp-open' : 'opp-collapsed'}`} data-region="候選情報">
      <div className="opp-head">
        {/* 徽章／日期／收合鈕同一列（2026-07-26 改版）：原本收合鈕跟徽章分屬 flex 兩端、
            中間文字區塊佔滿寬度時鈕會被擠到自己獨立一行，手機上白白多一段高度。 */}
        <div className="opp-head-top">
          <span className="badge-pill"><Target size={14} strokeWidth={1.75} />候選情報 · 共 {poolN} 檔</span>
          <span className="opp-date">{opp.date || '—'}</span>
          <button className="opp-toggle" onClick={() => setOpen(v => !v)}
            aria-expanded={open} aria-label={open ? '收合候選情報' : '展開候選情報'}>
            {open ? <ChevronDown size={18} strokeWidth={2} /> : <ChevronRight size={18} strokeWidth={2} />}
            <span>{open ? '收合' : `展開 ${poolN} 檔`}</span>
          </button>
        </div>
        {/* 有入場門檻時要講清楚這批的來歷——「強勢股裡的技術面最佳」與「全市場技術面最佳」
            是兩件事，數字一樣但意義不同，不說會讓人誤讀候選清單的範圍。 */}
        <p className="opp-tagline">這不是購買組合，是候選情報。買哪幾檔、買不買，由你決定。</p>
        {/* 2026-07-26 精簡：「今日 N 檔」「僅供參考，非投資建議」跟上面 hero 的「今日候選」數字、
            下面 banner／footer 的免責聲明重複，這裡只留「篩了什麼」這個不重複的資訊，
            讓 hero 到第一檔候選卡片的距離不被複誦的字句拉長。門檻退化警語（真正的誠實內容）原樣保留。 */}
        <p className="opp-sub">
          {opp.gate?.applied
            ? <>先篩「{opp.gate.label}」（全市場漲幅前段、回測最穩的門檻）</>
            : opp.gate?.reason === 'rs_unavailable'
              ? <b className="opp-degraded"><AlertTriangle size={13} strokeWidth={2} className="inline-warn-icon" />相對強弱資料今日不可用，「{opp.gate.label}」門檻未套用（改為全市場）</b>
              : opp.gate?.reason === 'pool_too_small'
                ? <b className="opp-degraded"><AlertTriangle size={13} strokeWidth={2} className="inline-warn-icon" />今日符合「{opp.gate.label}」的候選僅 {opp.gate.pool} 檔（不足 {opp.gate.min_pool}），門檻未套用</b>
                : '當日有訊號者'}
          ，已過濾營收年減／低量
        </p>
      </div>

      {open && (<>
      {TIER_ORDER.map(key => (
        <TierSection key={key} tierKey={key} label={TIER_META[key].label} Icon={TIER_META[key].Icon}
          blurb={TIER_META[key].blurb} lede={TIER_META[key].lede}
          variant={key === 'both' ? 'primary' : 'secondary'}
          list={tiered[key]} previewN={previewN} onPick={handlePick} />
      ))}

      {tiered.other.length > 0 && (
        <div className="opp-tier opp-tier-other">
          <button className="opp-tier-other-toggle" onClick={() => setShowOther(v => !v)} aria-expanded={showOther}>
            {showOther ? <ChevronDown size={14} strokeWidth={2} /> : <ChevronRight size={14} strokeWidth={2} />}
            其他候選（未達分類門檻）共 {tiered.other.length} 檔
          </button>
          {showOther && (<>
            <p className="opp-tier-note">照候選清單原始順序，不是好壞排名</p>
            <div className="opp-cards">
              {tiered.other.map(p => <CandidateCard key={p.id} p={p} onClick={() => handlePick(p)} />)}
            </div>
          </>)}
        </div>
      )}

      {/* 「這些數字怎麼來的」：核准的單欄故事線順序是「其他候選 → 這些數字怎麼來的 → 進階篩選」，
          中間不該插別的東西。2026-07-26 對抗審查發現這裡被搬到 PositionPlan（個股觀察位表，
          高達 3954px）之後，害這段誠實內容從第 14 屏才出現——挪回 PositionPlan 之前，
          恢復核准的敘事順序（觀察位表是輔助工具，不該卡在敘事中間）。 */}
      <h2 className="opp-section-title">這些數字怎麼來的</h2>
      <HonestyCallout tierStats={tierStats} />
      <OutcomeShape tierStats={tierStats} />

      {/* 個股觀察位（2026-07-25 加，2026-07-26 誠實化：拿掉購買組合語意，只留近 20 日前高與績效檢視日）。
          只帶「雙優／勝率偏優／報酬偏優」三類進觀察位表——候選池全開後常有百餘檔，「其他候選」
          全塞進表格會讓這張表長到失去用途；三類本身就是畫面上特別標出來的那批，適合放觀察位。
          picks 本身沒有產業，從 screener.json 併回來（集中度警示要用）。 */}
      <PositionPlan dataDate={opp.date} picks={[...tiered.both, ...tiered.win, ...tiered.return].map(p => {
        const full = stocks?.find(s => s.id === p.id)
        return {
          id: p.id, name: p.name,
          close: p.close ?? full?.close ?? null,
          industry: full?.industry ?? null,
          recent_high20: p.recent_high20 ?? full?.recent_high20 ?? null,   // 近 20 日前高（觀察位）要用
        }
      })} />

      {board && (
        <div className="opp-board">
          <span className="opp-board-title"><TrendingUp size={14} strokeWidth={1.75} />候選情報成績單</span>
          {board.samples > 0 ? (
            <div className="opp-board-stats">
              <span>勝率 <b>{Math.round(board.win_rate * 100)}%</b></span>
              <span>平均報酬 <b className={board.avg_ret >= 0 ? 'good' : 'bad'}>{board.avg_ret >= 0 ? '+' : ''}{board.avg_ret}%</b></span>
              <span>樣本 <b>{board.samples}</b></span>
              <span className="opp-muted">（入選後 {board.forward_days} 交易日）</span>
              {board.samples < 20 && <span className="opp-muted">樣本尚少，參考即可</span>}
            </div>
          ) : (
            <span className="opp-muted">樣本累積中——每天留檔，滿 {board.forward_days || 20} 交易日的舊 picks 才計入實績。</span>
          )}
        </div>
      )}

      {(win || weights?.signals) && (
        <div className="opp-weights">
          <button className="opp-weights-toggle" onClick={() => setShowWeights(v => !v)}>
            {showWeights ? <ChevronDown size={14} strokeWidth={2} /> : <ChevronRight size={14} strokeWidth={2} />}
            各訊號回測勝率（權重依據，透明化）
          </button>
          {showWeights && (win ? (
            <div className="opp-weights-body">
              <p className="opp-muted">
                每格＝訊號成立後 {win.forward_days} 交易日的<b>平均超額報酬</b>（減去同日全市場平均，
                衡量「有沒有比隨便買強」）。<b>點欄位標題</b>可切換排序聚焦；↑↓＝近半年比歷史變強／變弱；
                <span className="wq-weak-inline">灰字</span>＝樣本不足 {minS}，僅供參考。
                權重 = 平均超額 ×2 取 1~5（≤0 或樣本不足＝0）。
              </p>
              <div className="opp-weights-scroll">
                <table className="opp-weights-table wq-table">
                  <thead>
                    <tr>
                      <th className="wq-sig">訊號</th>
                      {winCols.map(w => (
                        <th key={w.key} className={`wq-h${sortWin === w.key ? ' wq-active' : ''}`}
                          role="button" tabIndex={0} aria-sort={sortWin === w.key ? 'descending' : 'none'}
                          onClick={() => setSortWin(w.key)}
                          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSortWin(w.key) } }}>
                          {w.label}{sortWin === w.key && <span className="wq-caret">▾</span>}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sortedRows.map(([key, row]) => {
                      const t = trendOf(row)
                      return (
                        <tr key={key}>
                          <td className="wq-sig">
                            {row.label}
                            {t && <span className={`wq-trend wq-${t}`} title={
                              t === 'up' ? '近半年比歷史更強' : t === 'down' ? '近半年比歷史轉弱' : '近半年與歷史相當'
                            }><TrendGlyph t={t} /></span>}
                          </td>
                          {winCols.map(w => (
                            <WinCell key={w.key} c={row[w.key]} minS={minS} active={sortWin === w.key} />
                          ))}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              {activeWeights.length > 0 && (
                <p className="opp-muted opp-weights-note">
                  目前候選情報引擎採用「歷史」欄權重排序：
                  {activeWeights.map(x => `${x.label} ${x.w}`).join('、')}。
                  其餘（含外資／投信連買、千張大戶、同業低估）平均超額 ≤0 或樣本不足 → 權重 0。
                  回測母體＝約兩年長歷史（{win.as_of} 為止）。
                </p>
              )}
            </div>
          ) : (
            <div className="opp-weights-body">
              <p className="opp-muted">
                回測訊號成立日的下 {weights.forward_days} 交易日報酬，並減去「同一天全市場的平均報酬」
                得到超額報酬——只看有沒有漲，多頭時亂選也會贏，那是大盤的功勞不是訊號的。
                權重 = 平均超額（百分點）×2，取 1~5；平均超額 ≤ 0 或樣本 &lt; {weights.min_sample || 30} 一律 0。
              </p>
              <div className="opp-weights-scroll">
                <table className="opp-weights-table">
                  <thead>
                    <tr><th>訊號</th><th>勝率</th><th>平均報酬</th><th>平均超額</th><th>樣本</th><th>權重</th></tr>
                  </thead>
                  <tbody>
                    {Object.values(weights.signals)
                      .sort((a, b) => b.weight - a.weight || b.samples - a.samples)
                      .map(s => (
                        <tr key={s.label}>
                          <td>{s.label}</td>
                          <td>{s.win_rate != null ? `${Math.round(s.win_rate * 100)}%` : '—'}</td>
                          <td className={s.avg_ret >= 0 ? 'good' : ''}>{s.avg_ret != null ? `${s.avg_ret >= 0 ? '+' : ''}${s.avg_ret}%` : '—'}</td>
                          <td className={s.avg_excess > 0 ? 'good' : ''}>{s.avg_excess != null ? `${s.avg_excess >= 0 ? '+' : ''}${s.avg_excess}pp` : '—'}</td>
                          <td>{s.samples || '—'}</td>
                          <td><b>{s.weight}</b></td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
      </>)}
    </section>
  )
}
