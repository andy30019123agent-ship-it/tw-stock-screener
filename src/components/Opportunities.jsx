import { useState, useEffect, useMemo } from 'react'
import { TrendingUp, Calendar, AlertTriangle, ChevronRight, ChevronDown, Info, LayoutGrid, List, LineChart, Scale, ListChecks } from 'lucide-react'
import PositionPlan from './PositionPlan'
import OutcomeShape from './OutcomeShape'
import { usablePair, winDiffText, evDiffText, edgeSentence, edgeWinShort, edgeWinRateText, staleText, gateNote, biasNote, normalizeTier, evVerdictOf } from '../lib/tierVerdict'
import { fmtRange } from '../lib/fmtRange'
import { readView, writeView } from '../lib/viewPref'
import { signed, rankFront, beatPct, gapToHigh, gapText, maSide, dirOf, commonReasons, reasonView } from '../lib/cardFacts'

const isNum = v => typeof v === 'number' && Number.isFinite(v)

// 候選情報分類：tier 由後端 opportunities.py 依「當日候選池內百分位」算好，前端只負責分組顯示，
// 不重新排序、不重新判斷（舊檔的舊值經 normalizeTier 相容）。
// ⚠️ 名次沒有證據（2026-07-25 實測：前 3 名 vs 第 4~8 名 t=-0.22，第 2 名反而最差）——
// 每組清單一律照 JSON 給的原始順序顯示，不做任何「誰比較好」的二次排序。卡片與清單兩種檢視
// 吃同一個陣列、同一個切片（2026-11-13 可讀性改版），資料與順序完全相同。
// 🔴 2026-11-13 分類簡化（_reports/重算_候選池層級統計_2026-11-13.md「分類簡化」一節）：
// 只剩一個有證據的分類「相對優勢」（成交金額在當日候選池前 1/3）；「乖離排前段」是純描述標籤。
// 結論句不寫死：由 tierVerdict 讀 tier_stats.json 的 paired.cat_edge_vs_rest 決定；
// 缺欄位／null／stale 時退成不帶數字的中性句。
const NEUTRAL = '歷史上跟其他候選的比較數字暫時取不到，有分類也可能虧錢'

// ── 2026-11-13 可讀性改版（Andy 核准方向 3「先看股票」＋可切換清單）──────────────
// 🔴 MASTER.md 硬約束：誠實性內容不刪、不藏到要點兩下才看得到。做法是「縮短並貼在對應數字旁」：
//   ・候選區最上面一句：相對優勢比其他候選多多少（附誤差範圍）＋單檔賺錢機率不到一半＋這不是購買組合；
//   ・緊接一行：歷史回測、未必代表未來；
//   ・完整根據放在候選區之後的「這些數字怎麼來的」（結論／證據／限制三層），預設展開、不用點。

// 位置條：只是把同一個百分位畫出來（0＝最左、1＝最右），旁邊一定有一句寫清楚「跟誰比」。
function PosBar({ v }) {
  if (!isNum(v)) return null
  return (
    <span className="opp-bar" aria-hidden="true">
      <i style={{ left: `${Math.min(1, Math.max(0, v)) * 100}%` }} />
    </span>
  )
}

// 漲跌：SVG 三角＋紅漲綠跌（MASTER：行情箭頭一律 SVG，不用 Unicode）
function Tri({ dir }) {
  if (dir === 'flat') return null
  return (
    <svg className="opp-tri" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
      {dir === 'up' ? <polygon points="5,1 9.5,9 0.5,9" fill="currentColor" /> : <polygon points="0.5,1 9.5,1 5,9" fill="currentColor" />}
    </svg>
  )
}

function Price({ p, full, compact = false }) {
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

// 一檔的事實區（卡片與清單展開共用）：強弱／成交金額／離前高，每一行都寫明在跟誰比。
// 不加任何「偏優」「加分」評語——high20_gap 重算後方向不穩定（硬性限制，見 OutcomeShape）。
function PickFacts({ p }) {
  const fp = p.feat_pct || {}
  const beat = beatPct(p.rs_pct_60)
  const turn = rankFront(fp.turnover)
  const gap = gapToHigh(p.close, p.recent_high20)
  const side = maSide(p.close, p.support_ma20)
  return (
    <>
      <div className="opp-facts">
        {beat != null && (
          <div className="opp-fact">
            <span className="opp-fact-k">強弱</span>
            <PosBar v={p.rs_pct_60} />
            <p className="opp-fact-v">近 60 天漲幅贏過全市場 <b className="mono">{beat}%</b> 的股票</p>
            {isNum(p.rs20) && (
              <p className="opp-fact-v opp-fact-sub">
                近 20 天報酬比大盤 <b className={`mono ${dirOf(p.rs20)}`}><Tri dir={dirOf(p.rs20)} />{signed(p.rs20)}</b> 個百分點
              </p>
            )}
          </div>
        )}
        {turn && (
          <div className="opp-fact">
            <span className="opp-fact-k">成交金額</span>
            <PosBar v={fp.turnover} />
            <p className="opp-fact-v">在今天的候選裡<b>{turn}</b></p>
          </div>
        )}
        {gap && (
          <div className="opp-fact">
            <span className="opp-fact-k">離前高</span>
            <PosBar v={fp.high20_gap} />
            <p className="opp-fact-v">
              {gap.atHigh
                ? <>已在近 20 日高點</>
                : <>離近 20 日前高還差 <b className="mono">{gapText(gap)}</b>{isNum(fp.high20_gap) && <>，比今天 {Math.round(fp.high20_gap * 100)}% 的候選遠</>}</>}
            </p>
          </div>
        )}
      </div>
      {(side || (gap && !gap.atHigh)) && (
        <dl className="opp-obs">
          {side && <div><dt>月線</dt><dd className="mono">{p.support_ma20}<small>{side}</small></dd></div>}
          {gap && !gap.atHigh && <div><dt>近 20 日前高</dt><dd className="mono">{p.recent_high20}<small>距 {gapText(gap)}</small></dd></div>}
        </dl>
      )}
    </>
  )
}

function PickTags({ p, showReasons }) {
  const bias = p.support_ma20 ? ((p.close - p.support_ma20) / p.support_ma20 * 100) : null
  const { biasHigh } = normalizeTier(p)
  const tags = []
  for (const f of (p.risk_flags || [])) {
    tags.push(<span className="opp-tag opp-tag-warn" key={`r-${f}`}><AlertTriangle size={14} strokeWidth={1.75} />{f}</span>)
  }
  if (p.earnings_date) tags.push(<span className="opp-tag" key="earn"><Calendar size={14} strokeWidth={1.75} />{p.earnings_date.slice(5)} 法說會</span>)
  // 「乖離排前段」＝純描述（當天候選池乖離前 1/3），不是加分、不用強調色
  if (biasHigh) tags.push(<span className="opp-tag opp-tag-dashed" key="bias" title="當天候選池裡 20 日乖離排前 1/3；只是描述，不代表比較好">乖離排前段</span>)
  if (bias != null && bias <= 15 && bias >= 8) tags.push(<span className="opp-tag" key="biasv">離月線 {signed(bias, 0)}%</span>)
  if (p.revenue_yoy != null) tags.push(<span className="opp-tag" key="rev">營收年增 <b className="mono">{signed(p.revenue_yoy)}%</b></span>)
  if (p.score > 0) tags.push(<span className="opp-tag" key="score" title="回測權重加總（透明化用，不是名次）">回測權重 <b className="mono">{p.score}</b> 分</span>)
  if (showReasons) for (const r of (p.reasons || [])) {
    const v = reasonView(r)
    tags.push(<span className={`opp-tag${v.warn ? ' opp-tag-warn' : ''}`} key={`why-${r}`}>{v.warn && <AlertTriangle size={14} strokeWidth={1.75} />}{v.text}</span>)
  }
  if (!tags.length) return null
  return <div className="opp-tags">{tags}</div>
}

// 卡片檢視：不放名次號碼、不做「領先卡」特殊放大——這批清單不是排行榜。點整張卡開 K 線。
function CandidateCard({ p, full, first, onOpen, showReasons }) {
  const onKey = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() } }
  return (
    <article className="opp-card" role="button" tabIndex={0} onClick={onOpen} onKeyDown={onKey}
      aria-label={`${p.name}（${p.id}），點開看 K 線圖`} {...(first ? { 'data-first-pick': '' } : {})}>
      <div className="opp-card-head">
        <div className="opp-card-id">
          <h3 className="opp-card-name" data-pick-name>{p.name}</h3>
          <div className="opp-card-sub">
            <span className="mono" data-pick-code>{p.id}</span>
            {full?.market && <>・{full.market}</>}
            {full?.industry && <>・{full.industry}</>}
          </div>
        </div>
        <Price p={p} full={full} />
      </div>
      <PickFacts p={p} />
      <PickTags p={p} showReasons={showReasons} />
    </article>
  )
}

// 清單檢視：一行一檔、可快速掃過；點一下就地展開同一份說明（不跳頁），K 線另外一顆鈕。
function CandidateRow({ p, full, first, open, onToggle, onOpen, showReasons }) {
  const risk = (p.risk_flags || [])[0]
  const beat = beatPct(p.rs_pct_60)
  const detailId = `opp-row-${p.id}`
  return (
    <li className={`opp-row${open ? ' open' : ''}`} data-pick-row {...(first ? { 'data-first-pick': '' } : {})}>
      <button className="opp-row-btn" onClick={onToggle} aria-expanded={open} aria-controls={detailId}>
        <span className="opp-row-main">
          <span className="opp-row-name" data-pick-name>{p.name}</span>
          {risk && <span className="opp-mk">{risk}</span>}
          <span className="opp-row-bar">
            <span className="mono opp-row-code" data-pick-code>{p.id}</span>
            <PosBar v={p.rs_pct_60} />
            {beat != null && <b className="mono">{beat}%</b>}
          </span>
        </span>
        <Price p={p} full={full} compact />
        <ChevronDown className={`opp-row-chev${open ? ' is-open' : ''}`} size={18} strokeWidth={2} aria-hidden="true" />
      </button>
      {open && (
        <div className="opp-row-detail" id={detailId}>
          <PickFacts p={p} />
          <PickTags p={p} showReasons={showReasons} />
          <button className="opp-row-chart" onClick={onOpen}><LineChart size={16} strokeWidth={1.75} />看 K 線圖</button>
        </div>
      )}
    </li>
  )
}

function PickList({ list, view, byId, onPick, showReasons, markFirst }) {
  const [openIds, setOpenIds] = useState(() => new Set())
  const toggle = id => setOpenIds(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  if (view === 'list') {
    return (
      <div className="opp-rows-wrap">
        <div className="opp-rows-h" aria-hidden="true"><span>代號・近 60 天漲幅贏過全市場幾 %</span><span>現價・漲跌</span></div>
        <ul className="opp-rows">
          {list.map((p, i) => (
            <CandidateRow key={p.id} p={p} full={byId.get(p.id)} first={markFirst && i === 0}
              open={openIds.has(p.id)} onToggle={() => toggle(p.id)} onOpen={() => onPick(p)} showReasons={showReasons} />
          ))}
        </ul>
      </div>
    )
  }
  return (
    <div className="opp-cards">
      {list.map((p, i) => (
        <CandidateCard key={p.id} p={p} full={byId.get(p.id)} first={markFirst && i === 0}
          onOpen={() => onPick(p)} showReasons={showReasons} />
      ))}
    </div>
  )
}

function ViewToggle({ view, onChange }) {
  return (
    <div className="opp-view" role="group" aria-label="候選顯示方式">
      {[['cards', '卡片', LayoutGrid], ['list', '清單', List]].map(([k, label, Icon]) => (
        <button key={k} data-view-btn={k} className={`opp-view-btn${view === k ? ' on' : ''}`}
          aria-pressed={view === k} onClick={() => onChange(k)}>
          <Icon size={16} strokeWidth={1.75} aria-hidden="true" />{label}
        </button>
      ))}
    </div>
  )
}

// ── 這些數字怎麼來的：結論／證據／限制三層（審計 B1/B2/D1：一個數字只當一次主角、
// 「跟其他候選比」與「單看這群自己」並排講清楚是兩種比較）。內容沿用舊 HonestyCallout，一字不少地分層。
const pct1 = v => (isNum(v) ? `${(v * 100).toFixed(1)}%` : '—')
const sPct = (v, d = 1) => (isNum(v) ? `${signed(v, d)}%` : '—')

function usableTier(v) {
  return v && v.win_rate != null && v.avg_win_pct != null && v.avg_loss_pct != null && Array.isArray(v.ci90)
}

function selfVerdict(s) {
  const ev = Number.isFinite(s.ev_pct) ? s.ev_pct : s.win_rate * s.avg_win_pct + (1 - s.win_rate) * s.avg_loss_pct
  const okEvCi = Array.isArray(s.ci90_ev) && isNum(s.ci90_ev[0]) && isNum(s.ci90_ev[1])
  const r = okEvCi ? `（誤差範圍 ${fmtRange(s.ci90_ev)}）` : ''
  // 幅度宣稱規則（tierVerdict 檔頭）：下限 ≥0.5 才講優勢、0~0.5 用保守說法，一律附誤差範圍
  let tail
  if (ev <= 0) tail = `扣完成本平均沒有賺${r}`
  else {
    const v = okEvCi ? evVerdictOf(s.ci90_ev) : null
    if (v === 'better') tail = `平均每筆是正的${r}，優勢在賺賠幅度，不是在勝率`
    else if (v === 'marginal') tail = `平均每筆略正${r}，但接近量不出`
    else tail = `平均看起來略正，但誤差範圍跨過 0${r}，還不能說這群自己會賺`
  }
  return { ev, tail }
}

function Basis({ tierStats, gate }) {
  const t = tierStats?.features?.turnover
  const edge = usableTier(tierStats?.categories?.edge) ? tierStats.categories.edge : t?.high
  const rest = tierStats?.categories?.rest
  const ready = usableTier(t?.high) && usableTier(t?.mid) && usableTier(t?.low) && usableTier(edge)
  const stale = staleText(tierStats)
  const head = edgeSentence(tierStats)
  const meta = tierStats?.meta || {}
  const fb = tierStats?.by_gate?.fallback
  const fbE = fb?.categories?.edge?.win_rate, fbR = fb?.categories?.rest?.win_rate
  const notReplayed = Array.isArray(meta.not_replayed) ? meta.not_replayed.map(x => x?.item).filter(Boolean) : []

  let conclusion, evidence
  if (!ready || tierStats?.stale) {
    conclusion = (
      <p>
        條件層級的歷史分佈{stale ? `${stale}，先不引用數字` : '暫時取不到'}，候選清單本身仍正常——買哪幾檔、買不買由你決定。
      </p>
    )
  } else {
    const { high: hi, mid, low: lo } = t
    const hp = usablePair(tierStats, 'turnover_high_vs_low')
    const hpWin = winDiffText(hp), hpEv = evDiffText(hp)
    const allBelowHalf = [hi, mid, lo].every(x => x.win_rate < 0.5)
    const sv = selfVerdict(edge)
    conclusion = (<>
      {head && (
        <p><b>跟同一天其他候選比</b>：{head}。
          <span className="opp-basis-aside">（這是每個交易日各算一次差距再平均；下面「證據」是全部筆數合起來算，兩者本來就不同。）</span>
        </p>
      )}
      <p>
        <b>單看這群自己</b>：單檔賺錢機率 <b className="mono">{pct1(edge.win_rate)}</b>{edge.win_rate < 0.5 ? '，不到一半' : '，過半也不代表穩賺'}；
        平均每筆 <b className="mono">{sPct(sv.ev, 2)}</b>，{sv.tail}。兩句講的是不同的比較，不矛盾。
      </p>
      <p className="opp-basis-def">
        <Info size={16} strokeWidth={1.75} aria-hidden="true" />
        <span><b>誤差範圍</b>＝把運氣算進去後，真正的數字大概落在這一段。整段都在 0 以上，才算量得出差別。</span>
      </p>
    </>)
    // 手機 390 寬放得下：誤差範圍放在主數字下一行（一位小數），不另開一列（審計 B1：小數位統一）
    const rng = (c, sign) => fmtRange(c, { digits: 1, sign })
    const rows = [
      ['單檔賺錢機率', s => pct1(s.win_rate), s => rng(s.ci90, false)],
      ['平均每筆', s => sPct(s.ev_pct, 2), s => rng(s.ci90_ev, true)],
      ['賺的時候平均', s => sPct(s.avg_win_pct)],
      ['賠的時候平均', s => sPct(s.avg_loss_pct)],
      ['中位數（典型）', s => sPct(s.median_pct, 2)],
    ]
    const cell = (f, r, s) => (
      <td className={r ? 'big' : ''}>{f(s)}{r && <small>{r(s)}</small>}</td>
    )
    evidence = (<>
      <div className="opp-basis-scroll">
        <table className="opp-basis-table" aria-label="相對優勢與其他候選的歷史對照">
          <caption>歷史上持有 20 個交易日、已扣成本；小字＝誤差範圍</caption>
          <thead><tr><th scope="col"><span className="sr-only">項目</span></th><th scope="col">相對優勢</th>{rest && <th scope="col">其他候選</th>}</tr></thead>
          <tbody>
            {rows.map(([label, f, r]) => (
              <tr key={label}>
                <th scope="row">{label}</th>
                {cell(f, r, edge)}
                {rest && cell(f, r, rest)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        再細看成交金額：候選池裡最高的三分之一，單檔歷史賺錢機率 <b className="mono">{pct1(hi.win_rate)}</b>；最低的三分之一 <b className="mono">{pct1(lo.win_rate)}</b>
        {allBelowHalf ? <>——<b>三層都不到一半</b></> : <>（中段 {pct1(mid.win_rate)}）</>}。
        {hpWin && <>同一天比，高層比低層{hpWin}{hpEv ? `、${hpEv}` : ''}。</>}
      </p>
      <p className="opp-basis-note">
        樣本：歷史上每天重播同一套選股流程後的候選池{meta.date_from && meta.date_to ? `（${meta.date_from}～${meta.date_to}）` : ''}，
        相對優勢共 <b className="mono">{isNum(edge.samples) ? edge.samples.toLocaleString('en-US') : '—'}</b> 筆；
        持有 {tierStats.forward_days ?? 20} 個交易日互相重疊，約等於 <b className="mono">{edge.blocks ?? '—'}</b> 批獨立進場，所以誤差範圍很寬。
        {isNum(tierStats.cost_pct) && <>已扣來回交易成本 {tierStats.cost_pct}%。</>}
        這是整群的統計，<b>不是任何一檔自己的勝率</b>。（{tierStats.date || '—'} 重算）
      </p>
    </>)
  }

  return (
    <section className="opp-basis" id="basis" data-region="這些數字怎麼來的">
      <div className="opp-basis-head">
        <span className="badge-pill"><Scale size={14} strokeWidth={1.75} />依據與限制</span>
        <h2 className="opp-section-title">這些數字怎麼來的</h2>
      </div>

      <div className="opp-layer">
        <span className="opp-layer-k">結論</span>
        {conclusion}
      </div>

      <div className="opp-layer">
        <span className="opp-layer-k">證據</span>
        {evidence || <p>歷史對照表暫時取不到。</p>}
        {stale && (
          <p className="opp-basis-warn"><AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" />{stale}，數字可能過時</p>
        )}
        <OutcomeShape tierStats={tierStats} />
      </div>

      <div className="opp-layer">
        <span className="opp-layer-k">限制</span>
        <ul className="opp-limits">
          {!tierStats?.stale && isNum(fbE) && isNum(fbR) && (
            <li>
              <b>門檻放寬的弱勢日</b>：過「強勢雙確認」的候選不足 {gate?.min_pool ?? 20} 檔、系統放寬門檻的日子
              {isNum(fb?.meta?.days_total) ? `（歷史 ${fb.meta.days_total} 天）` : ''}，相對優勢 {pct1(fbE)}、其他候選 {pct1(fbR)}
              {fbE < fbR ? '，方向反而相反' : '，差距跟平常不一樣'}。今天門檻{gate?.applied === false ? '沒有' : '有'}套用。
            </li>
          )}
          {notReplayed.length > 0 && (
            <li><b>歷史重播不了的條件</b>：{notReplayed.join('、')}——回測裡都沒套用。</li>
          )}
          <li><b>「離前高」方向不穩定</b>：重算後跟舊研究方向相反，卡片上只當位置看，不代表離前高越遠或越近越好。卡片上的「近 20 日前高」也只是技術觀察位，不是目標價或預期報酬。</li>
          <li><b>大盤狀態</b>是市場廣度代理（站上月線的比例），不是大盤指數，不會改變選股結果。</li>
          <li><b>這些都是歷史回測</b>，未必代表未來；僅供研究參考，非投資建議。</li>
        </ul>
      </div>
    </section>
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

function TierBlock({ list, view, byId, onPick, previewN, showReasons, markFirst, moreLabel }) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? list : list.slice(0, previewN)
  const hasMore = list.length > shown.length
  return (<>
    <PickList list={shown} view={view} byId={byId} onPick={onPick} showReasons={showReasons} markFirst={markFirst} />
    {hasMore && (
      <button className="opp-more" onClick={() => setExpanded(true)}>
        再看 {list.length - shown.length} 檔{moreLabel}<ChevronDown size={16} strokeWidth={2} />
      </button>
    )}
    {expanded && list.length > previewN && (
      <button className="opp-more" onClick={() => setExpanded(false)}>收合，只看前 {previewN} 檔</button>
    )}
  </>)
}

// 候選情報區塊：讀 opportunities.json（跨 repo 契約）＋ scoreboard.json ＋ signal_weights/windows.json。
// 2026-07-26 誠實化：從「每天固定推 N 檔」改成「輸出全部合格候選＋分類，交給 Andy 自己選」
// （Andy 拍板：不用幫我配好購買組合）。picks 不再截斷，檔數一律讀 opp.pool_n，不寫死。
// 都採「抓不到就靜默省略該部分」，不讓這區拖垮既有選股頁。
export default function Opportunities({ stocks, onPick, onCount, engineStatus, tierStats, exitSummary }) {
  const [opp, setOpp] = useState(null)
  const [board, setBoard] = useState(null)
  const [weights, setWeights] = useState(null)
  const [windows, setWindows] = useState(null)   // 多時間窗勝率榜（signal_windows.json）
  const [sortWin, setSortWin] = useState('all')   // 目前聚焦／排序的時間窗欄
  const [showWeights, setShowWeights] = useState(false)
  const [showOther, setShowOther] = useState(false)   // 「其他候選（沒有分類稱號）」收合區
  // 卡片／清單檢視（記住上次選擇；讀寫失敗一律退回卡片，見 lib/viewPref.js）
  const [view, setView] = useState(() => readView())
  const changeView = v => { setView(v); writeView(v) }

  const byId = useMemo(() => new Map((stocks || []).map(s => [s.id, s])), [stocks])

  // 點卡片開 K 線彈窗：優先用 screener.json 的完整資料（欄位齊全），
  // 抓不到（如尚未載入）才用 pick 本身的欄位墊底，讓彈窗至少開得起來。
  const handlePick = p => {
    const full = byId.get(p.id)
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
  const tiered = { edge: [], other: [] }
  for (const p of opp.picks) (normalizeTier(p).tier === 'edge' ? tiered.edge : tiered.other).push(p)
  const gNote = gateNote(opp.gate, tierStats)
  const stale = staleText(tierStats)
  const anyBias = opp.picks.some(p => normalizeTier(p).biasHigh)
  const common = commonReasons(opp.picks)
  const short = edgeWinShort(tierStats)
  const wr = edgeWinRateText(tierStats)
  const hist = tierStats?.stale ? null : tierStats?.categories?.edge

  return (
    <section className="opp" data-region="候選情報">
      {/* 首屏一句話：數字＋誤差範圍＋不到一半＋不是購買組合，全部貼在一起（MASTER 2026-11-13 核准第 3 條）。
          卡片與清單兩種檢視都在這句之下，所以清單上方同樣看得到。 */}
      <div className="opp-today">
        <p className="opp-today-main">
          <b className="mono">{tiered.edge.length}</b> 檔相對優勢
          {short ? <>：{short}</> : <>（成交金額排在當天候選前 1/3）：{NEUTRAL}</>}
          {wr ? <>，{wr}</> : ''}。
          <b>這不是購買組合</b>，買哪幾檔、買不買，由你決定。
        </p>
        <p className="opp-today-src">
          <Info size={16} strokeWidth={1.75} aria-hidden="true" />
          <span>
            歷史回測{tierStats?.date && !tierStats.stale ? `（${tierStats.date} 重算${isNum(hist?.blocks) ? `，約 ${hist.blocks} 批獨立進場` : ''}）` : ''}，未必代表未來。
            <a className="opp-basis-link" href="#basis">看依據與限制</a>
          </span>
        </p>
        {/* 門檻沒套上時要看得出來，不能靜默（降級警示留在最上面）；正常日的門檻說明挪到清單下方 */}
        {opp.gate && !opp.gate.applied && (opp.gate.reason === 'rs_unavailable' || opp.gate.reason === 'pool_too_small') && (
          <p className="opp-sub">
            {opp.gate.reason === 'rs_unavailable'
              ? <b className="opp-degraded"><AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" />相對強弱資料今日不可用，「{opp.gate.label}」門檻未套用（改為全市場）</b>
              : <b className="opp-degraded"><AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" />今日符合「{opp.gate.label}」的候選僅 {opp.gate.pool} 檔（不足 {opp.gate.min_pool}），門檻未套用</b>}
          </p>
        )}
        {gNote && (
          <p className="opp-sub"><b className="opp-degraded"><AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" />{gNote}</b></p>
        )}
        {stale && (
          <p className="opp-sub"><b className="opp-degraded"><AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" />{stale}，上面先不引用數字</b></p>
        )}
      </div>

      <div className="opp-listhead">
        <h2 className="opp-listtitle">相對優勢 <span className="mono">{tiered.edge.length}</span> 檔</h2>
        <ViewToggle view={view} onChange={changeView} />
      </div>
      <p className="opp-legend">
        <ListChecks size={16} strokeWidth={1.75} aria-hidden="true" />
        <span>成交金額排今天候選前 1/3・照候選清單原始順序，<b>不是好壞排名</b></span>
      </p>

      {tiered.edge.length > 0
        ? <TierBlock list={tiered.edge} view={view} byId={byId} onPick={handlePick} previewN={previewN}
            showReasons={!common} markFirst moreLabel="相對優勢" />
        : <p className="opp-legend">今天沒有候選落在「相對優勢」。</p>}

      <div className="opp-notes">
          {/* 有入場門檻時要講清楚這批的來歷——「強勢股裡的技術面最佳」與「全市場技術面最佳」
              是兩件事，數字一樣但意義不同，不說會讓人誤讀候選清單的範圍。 */}
          <p className="opp-legend">
            <Info size={16} strokeWidth={1.75} aria-hidden="true" />
            <span>
              {opp.gate?.applied
                ? <>今天共 {poolN} 檔候選，都先過「{opp.gate.label}」（全市場漲幅前段、回測最穩的門檻）</>
                : <>今天共 {poolN} 檔候選（{opp.gate?.label ? `「${opp.gate.label}」門檻未套用，` : ''}當日有訊號者）</>}
              ，已過濾營收年減／低量；清單順序主要看近 60 天漲幅在全市場的排名。
            </span>
          </p>
          {common && (
            <p className="opp-legend">
              <Info size={16} strokeWidth={1.75} aria-hidden="true" />
              <span>今天 {poolN} 檔候選的理由都一樣：「{common.map(r => reasonView(r).text).join('、')}」，所以卡片上不重複列。</span>
            </p>
          )}
          {anyBias && (
            <p className="opp-legend"><Info size={16} strokeWidth={1.75} aria-hidden="true" /><span>{biasNote(tierStats)}</span></p>
          )}
      </div>

      {tiered.other.length > 0 && (
        <div className="opp-other">
          <button className="opp-fold" onClick={() => setShowOther(v => !v)} aria-expanded={showOther}>
            <span>其他候選（沒有分類稱號）共 {tiered.other.length} 檔<small>同樣過了門檻，只是成交金額沒排進今天前 1/3</small></span>
            {showOther ? <ChevronDown size={20} strokeWidth={2} /> : <ChevronRight size={20} strokeWidth={2} />}
          </button>
          {showOther && (<>
            <p className="opp-legend">照候選清單原始順序，<b>不是好壞排名</b>。歷史數字見下面「證據」表的「其他候選」欄。</p>
            <TierBlock list={tiered.other} view={view} byId={byId} onPick={handlePick} previewN={previewN}
              showReasons={!common} markFirst={false} moreLabel="其他候選" />
          </>)}
        </div>
      )}

      <Basis tierStats={tierStats} gate={opp.gate} />

      {/* 個股觀察位（2026-07-25 加，2026-07-26 誠實化）：2026-11-13 前高已放進每張卡，
          這裡只留集中度警示、績效檢視日與防守價代價表（審計 A2：原本 46 列表格在手機切掉關鍵欄）。
          picks 本身沒有產業，從 screener.json 併回來（集中度警示要用）。 */}
      <PositionPlan dataDate={opp.date} exitSummary={exitSummary} picks={tiered.edge.map(p => {
        const full = byId.get(p.id)
        return { id: p.id, name: p.name, close: p.close ?? full?.close ?? null, industry: full?.industry ?? null }
      })} />

      {(board || win || weights?.signals) && <h2 className="opp-section-title opp-tools-title">成績單與訊號戰績</h2>}
      {board && (
        <div className="opp-board">
          <span className="opp-board-title"><TrendingUp size={16} strokeWidth={1.75} />候選情報成績單</span>
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
          <button className="opp-weights-toggle" onClick={() => setShowWeights(v => !v)} aria-expanded={showWeights}>
            {showWeights ? <ChevronDown size={16} strokeWidth={2} /> : <ChevronRight size={16} strokeWidth={2} />}
            各訊號回測勝率（權重依據，透明化）
          </button>
          {showWeights && (win ? (
            <div className="opp-weights-body">
              <p className="opp-muted">
                每格＝訊號成立後 {win.forward_days} 交易日的<b>平均超額報酬</b>（減去同日全市場平均，
                衡量「有沒有比隨便買強」）。<b>點欄位標題</b>可切換排序聚焦；三角形＝近半年比歷史變強／變弱；
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
    </section>
  )
}
