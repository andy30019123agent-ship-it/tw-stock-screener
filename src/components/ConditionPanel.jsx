import { useState } from 'react'
import {
  SlidersHorizontal, Search, ChevronDown,
  Rocket, BookOpen, Gem, Sparkles, Landmark, TrendingUp,
} from 'lucide-react'
import ComboBoard from './ComboBoard'
import { oosBadge, sigTier, TIER_MARK } from '../lib/oos'

const isMobile = () =>
  typeof window !== 'undefined' && window.matchMedia('(max-width: 720px)').matches

// 一鍵套用的常用組合（會覆蓋現有勾選，但保留搜尋關鍵字）
const BLANK = {
  signalMa: false, breakout: false, bullAligned: false, goldenCross: false,
  maRising: false, strongerThanMarket: false, bigHolderRising: false, foreignDays: 0, trustDays: 0,
  shishiAny: false, snSqueezeBreakout: false, snLowerReversal: false,
  snBreakLowRecover: false, snImmortalGuide: false, snVolumeSupport: false,
  minYield: 0, maxPe: 0, maxPb: 0, undervalued: false,
  divFill: 'all', maxFillDays: 0,
  // 橫斷面 RS 也要列進 BLANK，否則切換快速套用時舊的勾選會殘留（清單被上一個 preset 的
  // 條件偷偷限縮，使用者看不出原因）
  rsStrong60: false, rsConfirmed: false, industryHot: false,
  // ⚠️ 2026-07-25 補齊（Codex 指出漏了 7 個）：BLANK 少任何一個欄位，套用快速套用時該條件就會
  // **從舊狀態殘留下來**，於是按鈕標示的策略與實際篩選條件不符（例如先選了「上櫃＋半導體」，
  // 再點「爆量突破」，清單其實還被市場與產業限縮著，但按鈕上的戰績是全市場的）。
  // 這裡必須涵蓋 DEFAULT_CONDITIONS 的每一個鍵（keyword 例外，見 applyPreset 刻意保留搜尋字）。
  breakoutMult: 1.8, breakoutLookback: 3,
  market: 'all', industry: 'all', chipLogic: 'and',
  minMoney: 0, excludeRunaway: false,
}
const PRESETS = [
  // 強勢雙確認擺第一位不是寫死順序——下面 orderedPresets 會依平均超額重排；但它目前確實是
  // 唯一「去極值後仍為正 ＋ 樣本外 robust」的訊號（2026-07-25 全樣本驗證）。
  { key: 'rsdual', label: '強勢雙確認', icon: TrendingUp, patch: { ...BLANK, rsConfirmed: true } },
  { key: 'breakout', label: '爆量突破', icon: Rocket, patch: { ...BLANK, breakout: true } },
  { key: 'shishi', label: '小詩選股', icon: BookOpen, patch: { ...BLANK, shishiAny: true } },
  { key: 'value', label: '同業低估', icon: Gem, patch: { ...BLANK, undervalued: true } },
  { key: 'fill', label: '填息快', icon: Gem, patch: { ...BLANK, divFill: 'filled', maxFillDays: 10 } },
  { key: 'signal', label: '糾結轉強', icon: Sparkles, patch: { ...BLANK, signalMa: true } },
  { key: 'foreign', label: '外資連買', icon: Landmark, patch: { ...BLANK, foreignDays: 3, trustDays: 0 } },
  { key: 'bull', label: '多頭排列', icon: TrendingUp, patch: { ...BLANK, bullAligned: true } },
]

// 每個快速套用對應的回測訊號 → 用它的「平均超額報酬」當排序分數（勝率最高的排前面）。
// 沒有對應訊號或無樣本者排到最後（維持原相對順序）。
const PRESET_SIGNAL = {
  rsdual: ['rs_confirmed_60_120'],
  breakout: ['signal_breakout'],
  // 小詩選股＝勾「符合任一小詩形態」，所以戰績要用**母體**（signal_shishi，後端 2026-07-25
  // 新增的回測訊號）。原本列 5 招個別訊號 → presetStat 取「最好的那一招」＝系統性偏高：
  // 母體實測成本後 −0.78pp（樣本 15955），最佳那招（縮口帶量突破）+0.04pp，差距近 0.8pp。
  shishi: ['signal_shishi'],
  value: ['undervalued'],
  signal: ['signal_ma'],
  foreign: ['foreign_buy'],
  fill: ['fill_fast'],
  bull: ['bull_aligned'],
}
// 取該策略「最具代表性訊號」（有樣本者中成本後超額最高）的回測戰績；無樣本回 null。
// ⚠️ 對應多個訊號的策略（小詩選股＝5 招）顯示的是「最好的那一招」，不是「勾了它會篩到的
// 那一整批」的表現——後者需要後端對「任一招成立」另做回測（signal_shishi 目前只有選股用、
// 沒進回測）。差距是真的：小詩 5 招裡最好的是縮口帶量突破，5 招母體的平均會被拉低。
// 這裡回傳時附上 `_isBest`，讓按鈕與表格能明確標示，不能只寫在腳註（腳註會被略過）。
function presetStat(key, weights) {
  const keys = PRESET_SIGNAL[key]
  if (!keys || !weights?.signals) return null
  const cands = keys.map(k => weights.signals[k]).filter(s => s && s.samples > 0 && s.avg_excess != null)
  if (!cands.length) return null
  const netOf = s => s.quality?.net_excess_expectancy ?? s.avg_excess
  const best = cands.reduce((a, b) => (netOf(b) > netOf(a) ? b : a))
  return keys.length > 1 ? { ...best, _isBest: true, _ofN: keys.length } : best
}
// 排序依據＝「成本後超額」（扣手續費證交稅＋扣大盤），不是原始平均超額。
// 原因：原始超額沒扣成本，會把「毛利看起來不錯、扣完成本其實贏不過大盤」的策略排到前面
// （實測縮口帶量突破毛 +0.82pp、扣完只剩 +0.02pp；糾結轉強毛 +0.23pp、扣完 −0.57pp）。
// 舊資料沒有 quality 欄位時退回 avg_excess，不讓排序整個壞掉。
function presetScore(key, weights) {
  const s = presetStat(key, weights)
  if (!s) return -Infinity
  const ne = s.quality?.net_excess_expectancy
  return ne != null ? ne : s.avg_excess
}
// OOS 穩健度徽章的判準已抽到 ../lib/oos（組合戰績排行榜共用同一套，避免兩張表對同一訊號不一致）。

// 橫斷面訊號（相對強弱＋產業輪動）。⚠️ 2026-07-25 起狀態已改變，別照舊註解理解：
//   ① **可以即時篩選**——後端 build_data 用 live_xsect 每天算好全市場百分位寫進 screener.json，
//      三個都在 filters.js 有對應條件（rsStrong60 / rsConfirmed / industryHot）。
//   ② **`rs_confirmed_60_120` 已是 Top5 的入場門檻**（opportunities.GATE_SIGNAL）——先篩它、
//      再用技術訊號排名。但它**不參與加權計分**（21% 的股票符合，當加分項會淹掉窄訊號）。
// 本常數這裡只是「戰績展示表要列哪幾個」的清單，與上面兩件事無關。
const XSECT_SIGNALS = [
  { key: 'rs_strong_60', label: '強勢股（60日）', hint: '近 60 日漲幅排全市場前 20%' },
  { key: 'rs_confirmed_60_120', label: '強勢雙確認', hint: '60 日強、120 日也不弱' },
  { key: 'industry_hot', label: '熱門產業', hint: '所屬產業近期輪動居前' },
]

// 市況分層表要顯示的訊號（有代表性、避免整排 0 樣本的塞版面）
const REGIME_SHOW = ['sn_squeeze_breakout', 'signal_breakout', 'signal_ma', 'bull_aligned',
  'rs_strong_60', 'rs_confirmed_60_120', 'industry_hot', 'sn_immortal_guide', 'sn_volume_support']
const REGIME_COLS = [['green', '綠（強）'], ['yellow', '黃（中）'], ['red', '紅（弱）']]
function regimeCell(cell) {
  if (!cell || !cell.samples) return { txt: '—', cls: '', dim: true }
  const v = cell.avg_excess
  return { txt: `${v >= 0 ? '+' : ''}${v}`, cls: v > 0 ? 'good' : v < 0 ? 'bad' : '', dim: cell.samples < 30, n: cell.samples }
}

export default function ConditionPanel({
  conditions, onChange, total, shown, holderReady, industries = [],
  weights = null, combos = null, exits = null, regime = null, open: openProp, onOpenChange, id,
}) {
  const c = conditions
  // 快速套用依「平均超額報酬」由高到低排（資料驅動；同分或無資料維持原順序）
  const orderedPresets = PRESETS
    .map((p, i) => ({ p, i, s: presetScore(p.key, weights) }))
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map(x => x.p)
  const set = (key, value) => onChange({ ...c, [key]: value })
  const [activePreset, setActivePreset] = useState(null)
  const applyPreset = (key, patch) => { onChange({ ...c, ...patch }); setActivePreset(key) }
  // 手機預設收合，桌機預設展開；若父層有傳 open 則改由父層控制（供手機常駐工具列連動）
  const [openState, setOpenState] = useState(() => !isMobile())
  const open = openProp !== undefined ? openProp : openState
  const setOpen = v => (onOpenChange ? onOpenChange(v) : setOpenState(v))

  return (
    <div id={id} className={`cond-panel ${open ? 'open' : 'collapsed'}`}>
      <button className="cond-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="badge-pill"><SlidersHorizontal size={14} strokeWidth={1.75} />篩選條件</span>
        <span className="cond-toggle-count">符合 <b key={shown}>{shown}</b> ／ {total}</span>
        <ChevronDown className={`chevron ${open ? 'up' : ''}`} size={18} strokeWidth={2} />
      </button>

      <div className="cond-body">
        {/* 一鍵套用（依勝率排序，按鈕上標戰績）＋ 策略戰績表 */}
        <div className="cond-presets">
          <span className="cond-section-label">快速套用</span>
          <div className="preset-row">
            {orderedPresets.map((p, i) => {
              const st = presetStat(p.key, weights)
              // 排序純看歷史平均超額，所以「樣本外沒過」的策略也可能排第一、字最大（例：填息快
              // IS +3.27pp 但 6 個時段只有 1 個合格）。不重排也不隱藏（Andy 要保留全部自行判斷），
              // 但一定要在按鈕上標記，否則「排最前＋數字最大」等於在推薦一個撐不住的策略。
              const tm = TIER_MARK[sigTier(st)]
              // 按鈕上的戰績數字＝成本後超額（與 presetScore 的排序依據同一個數）
              const btnScore = st ? (st.quality?.net_excess_expectancy ?? st.avg_excess) : null
              // st 為 null＝這個策略連回測事件都沒有（例：籌碼類，回測歷史只有 20 天籌碼資料），
              // 此時 oosBadge 也是 null，不可直接內插否則提示會變成「undefined——undefined」。
              const ob = oosBadge(st)
              const mark = !tm ? undefined
                : ob ? `⚠ 這個戰績的樣本外驗證沒過：${ob.text}——${ob.title}`
                  : '這個策略還沒有回測資料，無法判斷可靠度'
              return (
                <button key={p.key} className={`preset-chip ${activePreset === p.key ? 'on' : ''}`} style={{ '--i': i }}
                  onClick={() => applyPreset(p.key, p.patch)}
                  title={mark}>
                  <p.icon size={14} strokeWidth={1.75} />{p.label}
                  {/* 顯示的數字要跟排序依據是同一個（成本後超額）。原本排序用淨值、卻顯示沒扣成本的
                      毛超額，等於重演「畫面數字不是決策依據」那個 bug。 */}
                  {btnScore != null && <span className={`preset-score ${btnScore > 0 ? 'good' : btnScore < 0 ? 'bad' : ''}`}
                    title={st?._isBest
                      ? `成本後超額。⚠️ 這是 ${st._ofN} 個形態裡「最好的那一個」（${st.label}）的成績，不是勾選後篩到的整批的平均`
                      : '成本後超額：扣掉手續費證交稅、再扣掉同日大盤後真正多賺的'}>
                    {btnScore >= 0 ? '+' : ''}{btnScore}<small>pp</small>
                    {st?._isBest && <em className="score-best" title="顯示的是最佳形態的成績">＊</em>}</span>}
                  {tm && <sup className={tm.cls}>{tm.mark}</sup>}
                </button>
              )
            })}
          </div>
          {weights?.signals && (
            <details className="strategy-board">
              <summary>各策略回測戰績（依成本後超額排序）</summary>
              <div className="strategy-scroll">
                <table className="strategy-table">
                  {/* 欄位順序＝重要性順序。「成本後超額」原本排第 4，在 390 手機上會被切掉要橫捲
                      才看得到——標題卻寫著「最重要的一個數字」，自相矛盾。移到策略名旁邊。 */}
                  <thead><tr><th>策略</th>
                    <th title="扣掉手續費證交稅、再扣掉同日大盤後，平均每次真的比大盤多賺多少——最重要的一個數字">成本後超額</th>
                    <th title="樣本外驗證：只用過去資料選、拿沒看過的日子驗，看效力是否還在">樣本外</th>
                    <th title="典型的一筆交易結果（中位數）。訊號報酬極度右偏：平均被少數飆股拉高，中位數才是「大多數時候」的樣子">中位數</th>
                    <th title="扣掉成本後仍贏過同日大盤的比例。低於 50% 代表多數交易是輸給大盤的，靠少數大贏撐整體">贏大盤</th>
                    <th title="沒扣成本、沒扣大盤的原始超額報酬（僅供對照，別拿它當決策依據）">平均超額</th>
                    <th title="平均獲利 ÷ 平均虧損。<1 代表賺小賠大、勝率再高也危險">賺賠比</th>
                    <th>勝率</th><th>樣本</th></tr></thead>
                  <tbody>
                    {orderedPresets.map(p => {
                      const s = presetStat(p.key, weights)
                      const ob = oosBadge(s)
                      const q = s?.quality
                      // ⚠️ 2026-07-25 起看 net_excess_expectancy（成本後超額）而不是 net_expectancy
                      // （成本後絕對報酬）。舊欄位沒扣大盤 → 大盤漲的時候什麼都是正的，破底翻
                      // 明明輸大盤 0.91pp 卻顯示 +0.79pp 並塗成好色。
                      const ne = q?.net_excess_expectancy
                      return (
                        <tr key={p.key}>
                          <td>{p.label}{q?.high_win_trap &&
                            <span className="trap-flag" title="高勝率陷阱：勝率高但扣成本後贏不過大盤，別被勝率騙了">⚠️</span>}
                            {!q?.high_win_trap && q?.loses_to_market &&
                              <span className="trap-flag" title="扣掉交易成本後，這個訊號平均贏不過大盤——不如直接買大盤">⚠️</span>}</td>
                          <td className={ne > 0 ? 'good' : ne < 0 ? 'bad' : ''}>
                            {ne != null ? `${ne >= 0 ? '+' : ''}${ne}pp` : s ? '—' : '尚無回測'}</td>
                          <td>{ob ? <span className={`oos-badge ${ob.cls}`} title={ob.title}>{ob.text}</span> : '—'}</td>
                          <td className={q?.median_net_excess > 0 ? 'good' : q?.median_net_excess < 0 ? 'bad' : ''}>
                            {q?.median_net_excess != null ? `${q.median_net_excess >= 0 ? '+' : ''}${q.median_net_excess}pp` : '—'}</td>
                          <td className={q?.beat_market_rate != null && q.beat_market_rate < 0.5 ? 'combo-weak' : ''}>
                            {q?.beat_market_rate != null ? `${Math.round(q.beat_market_rate * 100)}%` : '—'}</td>
                          <td className={s && s.avg_excess > 0 ? 'good' : s && s.avg_excess < 0 ? 'bad' : ''}>
                            {s ? `${s.avg_excess >= 0 ? '+' : ''}${s.avg_excess}pp` : '—'}</td>
                          <td className={q && q.payoff_ratio != null && q.payoff_ratio < 1 ? 'bad' : ''}>
                            {q && q.payoff_ratio != null ? q.payoff_ratio : '—'}</td>
                          <td>{s && s.excess_win_rate != null ? `${Math.round(s.excess_win_rate * 100)}%` : '—'}</td>
                          <td>{s ? s.samples : '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <p className="strategy-note">
                平均超額＝進場後 20 交易日報酬減去同日全市場平均（衡量比隨便買強多少）；
                <b>樣本外</b>＝只用過去 1 年資料算、再拿之後沒看過的日子驗，「穩健」才是真本事、「過擬合」是背答案；
                <b>成本後超額</b>＝扣掉手續費證交稅、再扣掉大盤後真正多賺的（最重要），<b>賺賠比 &lt;1</b> 代表賺小賠大、
                <b>⚠️</b> 代表扣成本後贏不過大盤。<b>小詩選股顯示的是 5 招母體</b>（勾「符合任一形態」實際會篩到的
                那一整批，成本後 −0.78pp）——不是最好的那一招（縮口帶量突破 +0.04pp）；
                多頭排列／填息快僅供戰績參考、不進機會股名單。
              </p>
              <p className="strategy-note strategy-skew">
                ⚠️ <b>務必看「中位數」和「贏大盤」這兩欄</b>：全樣本實測顯示每個訊號的中位數超額都是負的、
                贏大盤比例都不到 44%。意思是<b>大多數交易其實小輸大盤，整體正報酬靠少數幾檔大贏撐起來</b>。
                這種形狀的策略要能成立，必須分散買足夠多檔、而且不能在賠錢時提早出場——只買一兩檔
                或半路放棄，很可能剛好錯過那幾檔、拿到的是中位數而不是平均數。
              </p>
            </details>
          )}
          <ComboBoard combos={combos} weights={weights} />

          {/* 相對強弱＋產業輪動的樣本外驗證戰績表。注意：這三個訊號現在**可以即時篩選**、
              且 rs_confirmed_60_120 已是 Top5 入場門檻（見 XSECT_SIGNALS 上方註解）；
              這張表只是它們的回測戰績展示。 */}
          {weights?.signals && XSECT_SIGNALS.some(s => (weights.signals[s.key]?.samples || 0) > 0) && (
            <details className="strategy-board">
              <summary>新訊號研究：相對強弱＋產業輪動（樣本外驗證中）</summary>
              <div className="strategy-scroll">
                <table className="strategy-table">
                  <thead><tr><th>新訊號</th><th>平均超額</th><th>樣本外</th><th>勝率</th><th>樣本</th></tr></thead>
                  <tbody>
                    {XSECT_SIGNALS.map(x => {
                      const s = weights.signals[x.key]
                      const ob = oosBadge(s)
                      return (
                        <tr key={x.key}>
                          <td title={x.hint}>{x.label}</td>
                          <td className={s && s.avg_excess > 0 ? 'good' : s && s.avg_excess < 0 ? 'bad' : ''}>
                            {s && s.avg_excess != null ? `${s.avg_excess >= 0 ? '+' : ''}${s.avg_excess}pp` : '尚無回測'}</td>
                          <td>{ob ? <span className={`oos-badge ${ob.cls}`} title={ob.title}>{ob.text}</span> : '—'}</td>
                          <td>{s && s.excess_win_rate != null ? `${Math.round(s.excess_win_rate * 100)}%` : '—'}</td>
                          <td>{s && s.samples ? s.samples : '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <p className="strategy-note">
                「相對強弱」＝拿個股近期漲幅跟全市場排名（不是跟大盤指數比）；「熱門產業」＝所屬產業近期輪動居前。
                這些是<b>橫斷面（跨股票比較）</b>訊號。2026-07-25 起後端每天算好全市場排名，所以<b>都可以直接勾選篩股</b>；
                其中<b>「強勢雙確認」已成為機會股名單的入場門檻</b>（先篩出強勢股，再用技術訊號排名）——
                它<b>不參與加權計分</b>，因為它有 21% 的股票符合，當加分項會淹掉真正有區辨力的窄訊號。
              </p>
            </details>
          )}

          {/* Phase B：出場優化——同一批訊號、比較不同持有期的成本後結果 */}
          {exits?.strategies?.some(s => s.samples > 0) && (
            <details className="strategy-board">
              <summary>出場分析：持有多久最划算（已扣交易成本）</summary>
              <div className="strategy-scroll">
                <table className="strategy-table">
                  <thead><tr><th>出場方式</th><th>淨報酬</th><th>淨超額</th><th>勝率</th><th>賺賠比</th><th>平均持有</th></tr></thead>
                  <tbody>
                    {exits.strategies.filter(s => s.samples > 0).map(s => (
                      <tr key={s.key} className={s.key === exits.control ? 'exit-control' : ''}>
                        <td>{s.label}{s.key === exits.control && <small>（現行）</small>}</td>
                        <td className={s.avg_net_return > 0 ? 'good' : s.avg_net_return < 0 ? 'bad' : ''}>
                          {s.avg_net_return >= 0 ? '+' : ''}{s.avg_net_return}pp</td>
                        <td className={s.avg_net_excess > 0 ? 'good' : s.avg_net_excess < 0 ? 'bad' : ''}>
                          {s.avg_net_excess != null ? `${s.avg_net_excess >= 0 ? '+' : ''}${s.avg_net_excess}pp` : '—'}</td>
                        <td>{Math.round(s.net_win_rate * 100)}%</td>
                        <td>{s.payoff_ratio != null ? s.payoff_ratio : '—'}</td>
                        <td>{s.avg_holding_days}日</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="strategy-note">
                以所有訊號事件為樣本、進場價用訊號次日收盤，比較不同出場方式的<b>成本後</b>結果
                （來回成本約 {exits.cost?.round_trip_pct}%）。淨超額＝扣成本後淨報酬減同期全市場平均。
                <b>這是全樣本比較</b>，要真的改「持有 20 日」的現行設定，還需通過樣本外驗證才算數（先不動）。
                ATR 停損停利因只有還原收盤、暫緩。
              </p>
            </details>
          )}

          {/* 市況分層回測：同一訊號在紅/黃/綠市況各自的超額——看「只在多頭有效」vs「全天候」 */}
          {regime?.signals && (
            <details className="strategy-board">
              <summary>市況分層：訊號在多頭/盤整/空頭各自表現</summary>
              <div className="strategy-scroll">
                <table className="strategy-table regime-table">
                  <thead><tr><th>訊號</th>{REGIME_COLS.map(([k, l]) => <th key={k} title="平均超額(pp)｜下方為樣本數">{l}</th>)}</tr></thead>
                  <tbody>
                    {REGIME_SHOW.map(k => regime.signals[k]).filter(Boolean).map(s => (
                      <tr key={s.label}>
                        <td>{s.label}</td>
                        {REGIME_COLS.map(([col]) => {
                          const c = regimeCell(s[col])
                          return (
                            <td key={col} className={`${c.cls} ${c.dim ? 'regime-dim' : ''}`}>
                              {c.txt}{c.n != null && <small className="regime-n">{c.n}</small>}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="strategy-note">
                每格＝該訊號在「當時市況」的平均超額（pp），下方小字為樣本數。市況用<b>市場廣度</b>判
                （綠＝多數股站上月線、紅＝多數在月線下），且用<b>當下能看到的資料</b>判（不偷看未來）。
                看一個訊號是<b>「全天候」（紅黃綠都正）還是「只有多頭有效」（綠正、紅負）</b>——後者在空頭要小心。
                樣本 &lt;30 淡色僅參考。空頭天數少，紅市況樣本本來就偏少。
              </p>
            </details>
          )}
        </div>

        {/* 範圍：市場 / 產業 */}
        <div className="cond-group">
          <span className="cond-section-label">範圍</span>
          <div className="cond-chips">
            <div className="seg">
              {[['all', '全部'], ['上市', '上市'], ['上櫃', '上櫃']].map(([m, label]) => (
                <button key={m} className={`seg-btn ${c.market === m ? 'on' : ''}`}
                  onClick={() => set('market', m)}>{label}</button>
              ))}
            </div>
            <div className="num-field select-field">
              <label>產業</label>
              <select value={c.industry} onChange={e => set('industry', e.target.value)}>
                <option value="all">全部產業</option>
                {industries.map(ind => <option key={ind} value={ind}>{ind}</option>)}
              </select>
            </div>
          </div>
        </div>

        {/* 風險濾網（Phase C，預設關閉、不影響 Top5，只是使用者自選過濾雜訊） */}
        <div className="cond-group">
          <span className="cond-section-label">風險濾網</span>
          <div className="cond-chips">
            <div className="num-field">
              <label title="20 日平均成交額，太低的股不好進出。台股電子股 1 億以下算偏低">最低成交額（億）</label>
              <input type="number" inputMode="decimal" min="0" step="0.5" value={c.minMoney}
                onChange={e => set('minMoney', Math.max(0, Number(e.target.value) || 0))} />
            </div>
          </div>
          <div className="cond-checks">
            <Toggle label="排除極端暴走股" hint="乖離/短漲/波動過高（追高風險）"
              checked={c.excludeRunaway} onChange={v => set('excludeRunaway', v)} />
          </div>
        </div>

        {/* 技術面 */}
        <div className="cond-group">
          <span className="cond-section-label">技術面</span>
          <div className="cond-checks">
            <Toggle label="糾結後黃金交叉→多頭發散" hint="綜合訊號"
              checked={c.signalMa} onChange={v => set('signalMa', v)} accent />
            <Toggle label="爆量突破起漲" hint="悶久→帶量突破創高" icon={Rocket}
              checked={c.breakout} onChange={v => set('breakout', v)} accent />
            <Toggle label="多頭排列" hint="MA5>10>20>60"
              checked={c.bullAligned} onChange={v => set('bullAligned', v)} />
            <Toggle label="近期黃金交叉" hint="MA5 上穿 MA20"
              checked={c.goldenCross} onChange={v => set('goldenCross', v)} />
            <Toggle label="均線上彎" hint="均線翻揚"
              checked={c.maRising} onChange={v => set('maRising', v)} />
            <Toggle label="強於大盤" hint="近20日報酬贏過加權指數"
              checked={c.strongerThanMarket} onChange={v => set('strongerThanMarket', v)} />
          </div>

          {/* 爆量突破旋鈕：只有勾選時出現 */}
          {c.breakout && (
            <div className="breakout-knobs">
              <Slider label="爆量倍數" value={c.breakoutMult} min={1.5} max={3} step={0.1}
                suffix="倍" onChange={v => set('breakoutMult', v)} />
              <Slider label="突破回看" value={c.breakoutLookback} min={1} max={5} step={1}
                suffix="天內" onChange={v => set('breakoutLookback', v)} />
            </div>
          )}
        </div>

        {/* 橫斷面相對強弱／產業輪動（2026-07-25 從「僅戰績」升級為可篩選）。
            擺在小詩選股前面是刻意的：全樣本去極值檢驗後，強勢雙確認是唯一「去掉最極端 2%
            事件後平均超額仍為正」且樣本外 robust 的訊號，而小詩那 5 招去掉最高 1% 就轉負。 */}
        <div className="cond-group">
          <span className="cond-section-label"><TrendingUp size={14} strokeWidth={1.75} />相對強弱／產業輪動</span>
          <p className="cond-group-note">
            跟全市場比排名（不是跟大盤指數比）。<b>強勢雙確認</b>是目前回測最穩的訊號——去掉最極端
            2% 的事件後平均超額仍為正，樣本外驗證也過關；其他訊號多半去掉最高 1% 就轉負。
          </p>
          <div className="cond-checks">
            <Toggle label="強勢雙確認" hint="60日排前20% 且 120日排前30%"
              checked={c.rsConfirmed} onChange={v => set('rsConfirmed', v)} accent />
            <Toggle label="強勢股（60日）" hint="近60日漲幅排全市場前20%"
              checked={c.rsStrong60} onChange={v => set('rsStrong60', v)} />
            <Toggle label="熱門產業" hint="所屬產業近期輪動居前"
              checked={c.industryHot} onChange={v => set('industryHot', v)} />
          </div>
        </div>

        {/* 小詩選股（布林軌道系列技術形態）*/}
        <div className="cond-group">
          <span className="cond-section-label"><BookOpen size={14} strokeWidth={1.75} />小詩選股</span>
          <div className="cond-checks">
            <Toggle label="符合任一小詩形態" hint="下列 5 招中任一成立"
              checked={c.shishiAny} onChange={v => set('shishiAny', v)} accent />
            <Toggle label="縮口帶量突破" hint="布林壓縮→帶量收上上軌"
              checked={c.snSqueezeBreakout} onChange={v => set('snSqueezeBreakout', v)} />
            <Toggle label="破下軌翻紅" hint="連黑跌破下軌後翻紅"
              checked={c.snLowerReversal} onChange={v => set('snLowerReversal', v)} />
            <Toggle label="破底翻" hint="跌破前低後迅速站回"
              checked={c.snBreakLowRecover} onChange={v => set('snBreakLowRecover', v)} />
            <Toggle label="仙人指路" hint="帶量長上影小K在壓力區"
              checked={c.snImmortalGuide} onChange={v => set('snImmortalGuide', v)} />
            <Toggle label="大量撐" hint="拉回大量紅K低點守住"
              checked={c.snVolumeSupport} onChange={v => set('snVolumeSupport', v)} />
          </div>
        </div>

        {/* 籌碼面 */}
        <div className="cond-group">
          <span className="cond-section-label">籌碼面</span>
          <div className="cond-chips">
            <div className="num-field">
              <label>外資連買 ≥</label>
              <input type="number" inputMode="numeric" min="0" max="30" value={c.foreignDays}
                onChange={e => set('foreignDays', parseInt(e.target.value) || 0)} />
              <span>天</span>
            </div>
            <div className="num-field">
              <label>投信連買 ≥</label>
              <input type="number" inputMode="numeric" min="0" max="30" value={c.trustDays}
                onChange={e => set('trustDays', parseInt(e.target.value) || 0)} />
              <span>天</span>
            </div>
            <div className="seg">
              <button className={`seg-btn ${c.chipLogic === 'and' ? 'on' : ''}`}
                onClick={() => set('chipLogic', 'and')}>外資＋投信都要</button>
              <button className={`seg-btn ${c.chipLogic === 'or' ? 'on' : ''}`}
                onClick={() => set('chipLogic', 'or')}>任一即可</button>
            </div>
            <Toggle label="千張大戶上升" hint={holderReady ? '占比較上週增加' : '資料累積中'}
              checked={c.bigHolderRising} onChange={v => set('bigHolderRising', v)}
              disabled={!holderReady} />
          </div>
        </div>

        {/* 估值 / 同業比 */}
        <div className="cond-group">
          <span className="cond-section-label"><Gem size={14} strokeWidth={1.75} />估值／同業比</span>
          <div className="cond-chips">
            <div className="num-field">
              <label>殖利率 ≥</label>
              <input type="number" inputMode="decimal" min="0" max="20" step="0.5" value={c.minYield}
                onChange={e => set('minYield', parseFloat(e.target.value) || 0)} />
              <span>%</span>
            </div>
            <div className="num-field">
              <label>本益比 ≤</label>
              <input type="number" inputMode="numeric" min="0" max="100" value={c.maxPe}
                onChange={e => set('maxPe', parseFloat(e.target.value) || 0)} />
              <span>倍</span>
            </div>
            <div className="num-field">
              <label>本淨比 ≤</label>
              <input type="number" inputMode="decimal" min="0" max="20" step="0.1" value={c.maxPb}
                onChange={e => set('maxPb', parseFloat(e.target.value) || 0)} />
              <span>倍</span>
            </div>
            <Toggle label="同業被低估" hint="本益比低於同產業中位數" icon={Gem}
              checked={c.undervalued} onChange={v => set('undervalued', v)} accent />
          </div>
        </div>

        {/* 填息（B 段第二段）：配息拿到手不算賺，股價漲回除權息前才是真的填息 */}
        <div className="cond-group">
          <span className="cond-section-label"><Gem size={14} strokeWidth={1.75} />填息</span>
          <div className="cond-chips">
            <div className="seg">
              {[['all', '不限'], ['filled', '已填息'], ['pending', '貼息中']].map(([v, label]) => (
                <button key={v} className={`seg-btn ${c.divFill === v ? 'on' : ''}`}
                  onClick={() => set('divFill', v)}>{label}</button>
              ))}
            </div>
            <div className="num-field">
              <label>填息天數 ≤</label>
              <input type="number" inputMode="numeric" min="0" max="120" value={c.maxFillDays}
                onChange={e => set('maxFillDays', parseInt(e.target.value, 10) || 0)} />
              <span>天</span>
            </div>
          </div>
        </div>

        <div className="cond-footer">
          <div className="search-field">
            <Search size={16} strokeWidth={1.75} />
            <input className="search" type="search" placeholder="搜尋代號／名稱"
              value={c.keyword} onChange={e => set('keyword', e.target.value)} />
          </div>
          <div className="cond-summary">
            符合 <b key={shown}>{shown}</b> 檔 ／ 共 {total} 檔
          </div>
        </div>
      </div>
    </div>
  )
}

function Toggle({ label, hint, checked, onChange, accent, disabled, icon: Icon }) {
  return (
    <label className={`toggle ${checked ? 'checked' : ''} ${accent ? 'accent' : ''} ${disabled ? 'disabled' : ''}`}
      title={hint ? `${label}｜${hint}` : label}>
      <input type="checkbox" checked={checked} disabled={disabled}
        onChange={e => onChange(e.target.checked)} />
      <span className="toggle-label">{Icon && <Icon size={14} strokeWidth={1.75} />}{label}</span>
      {hint && <span className="toggle-hint">{hint}</span>}
    </label>
  )
}

function Slider({ label, value, min, max, step, suffix, onChange }) {
  return (
    <label className="knob">
      <span className="knob-label">{label}</span>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value))} />
      <span className="knob-value">{value}{suffix}</span>
    </label>
  )
}
