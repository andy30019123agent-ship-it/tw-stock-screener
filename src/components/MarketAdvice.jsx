import { TrendingUp, TrendingDown, Minus, Check } from 'lucide-react'

// 本週市況建議：看現在大盤（市場廣度）是紅/黃/綠，從「市況分層」回測挑出「這個市況下歷史最強」的訊號。
// 全天候（三種市況都正）會標記，並給「套用」鈕一鍵套上條件。
//
// 2026-07-25：相對強弱／產業輪動原本只能看戰績（需要全市場排名，前端算不出來），現在後端
// build_data 會用與回測同一支 live_xsect 算好百分位並寫進 screener.json，所以這三個也能套用了。
// 這件事的價值：全樣本去極值驗證顯示「強勢雙確認」是唯一去掉最極端 2% 事件後仍為正的訊號，
// 而它先前正好是唯一不能拿來選股的——最穩的訊號不能用，是最不該留著的錯配。
const STATUS = {
  green: { label: '偏強（多頭）', tone: 'up', icon: TrendingUp },
  yellow: { label: '中性（盤整）', tone: 'flat', icon: Minus },
  red: { label: '偏弱（空頭）', tone: 'down', icon: TrendingDown },
  severe_red: { label: '明顯走弱（空頭）', tone: 'down', icon: TrendingDown },
}
const BUCKET = { green: 'green', yellow: 'yellow', red: 'red', severe_red: 'red' }
const BUCKETS = ['green', 'yellow', 'red']
// 訊號 → 可即時套用的篩選條件。key 必須與 filters.js 的 DEFAULT_CONDITIONS 對得上。
const APPLY = {
  signal_ma: { signalMa: true }, signal_breakout: { breakout: true },
  sn_squeeze_breakout: { snSqueezeBreakout: true }, sn_immortal_guide: { snImmortalGuide: true },
  sn_volume_support: { snVolumeSupport: true }, sn_break_low_recover: { snBreakLowRecover: true },
  sn_lower_reversal: { snLowerReversal: true }, bull_aligned: { bullAligned: true },
  // 橫斷面（2026-07-25 起後端已提供旗標，可即時篩）
  rs_confirmed_60_120: { rsConfirmed: true }, rs_strong_60: { rsStrong60: true },
  industry_hot: { industryHot: true },
}

export default function MarketAdvice({ breadth, regime, onApply }) {
  if (!breadth || !regime?.signals) return null
  const st = STATUS[breadth.status]
  const bucket = BUCKET[breadth.status]
  if (!st || !bucket) return null

  const ranked = Object.entries(regime.signals).map(([k, s]) => {
    const allWeather = BUCKETS.every(b => s[b]?.samples >= 30 && s[b]?.avg_excess > 0)
    return { k, label: s.label, cur: s[bucket], allWeather }
  }).filter(x => x.cur && x.cur.samples >= 30 && x.cur.avg_excess > 0)
    .sort((a, b) => b.cur.avg_excess - a.cur.avg_excess)
    .slice(0, 5)

  if (!ranked.length) return null
  const Icon = st.icon

  return (
    <div className={`market-advice tone-${st.tone}`}>
      <div className="ma-head">
        <Icon size={18} strokeWidth={2} />
        <span>本週市況：<b>{st.label}</b></span>
        <small>全市場 {Math.round(breadth.breadth20 * 100)}% 站上月線</small>
      </div>
      <div className="ma-sub">這個市況下，歷史表現最強的訊號：</div>
      <ol className="ma-list">
        {ranked.map(x => (
          <li key={x.k}>
            {/* 訊號名要用 span 包住才能單獨 nowrap——原本是裸文字節點，375 寬被套用鈕擠壓時
                會斷成「縮口帶量突／破」（中文可在任何字元間斷行，2026-07-25 實測發現）。 */}
            <span className="ma-name"><span className="ma-label">{x.label}</span>
              {x.allWeather && <span className="ma-tag" title="紅黃綠三種市況都有正超額，空頭也站得住">全天候</span>}</span>
            <span className="ma-exc good">+{x.cur.avg_excess}pp</span>
            {APPLY[x.k]
              ? <button className="ma-apply" onClick={() => onApply(APPLY[x.k])}><Check size={13} strokeWidth={2.5} />套用</button>
              : <span className="ma-info" title="相對強弱/產業訊號需全市場即時排名，網站只提供歷史戰績、無法即時篩選">僅戰績</span>}
          </li>
        ))}
      </ol>
      <p className="ma-note">依「市況分層」歷史回測——挑目前市況下超額最高、樣本足（≥30）的訊號；全天候＝空頭也有效。僅供參考、非投資建議。</p>
    </div>
  )
}
