import { useState } from 'react'
import {
  SlidersHorizontal, Search, ChevronDown,
  Rocket, BookOpen, Gem, Sparkles, Landmark, TrendingUp,
} from 'lucide-react'
import ComboBoard from './ComboBoard'

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
}
const PRESETS = [
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
  breakout: ['signal_breakout'],
  shishi: ['sn_squeeze_breakout', 'sn_lower_reversal', 'sn_break_low_recover', 'sn_immortal_guide', 'sn_volume_support'],
  value: ['undervalued'],
  signal: ['signal_ma'],
  foreign: ['foreign_buy'],
  fill: ['fill_fast'],
  bull: ['bull_aligned'],
}
// 取該策略「最具代表性訊號」（有樣本者中平均超額最高）的回測戰績；無樣本回 null。
function presetStat(key, weights) {
  const keys = PRESET_SIGNAL[key]
  if (!keys || !weights?.signals) return null
  const cands = keys.map(k => weights.signals[k]).filter(s => s && s.samples > 0 && s.avg_excess != null)
  if (!cands.length) return null
  return cands.reduce((a, b) => (b.avg_excess > a.avg_excess ? b : a))
}
function presetScore(key, weights) {
  const s = presetStat(key, weights)
  return s ? s.avg_excess : -Infinity
}
// 樣本外(OOS)穩健度徽章：把回測狀態翻成白話。robust＝訓練期看好、沒看過的日子也站得住；
// overfit＝訓練期看好但樣本外變負（等於背答案）；其餘為縮水/挑市況/樣本不足。
const OOS_BADGE = {
  robust: ['穩健', 'oos-robust', '樣本外仍為正、效力保留過半、跨多個市況、樣本足'],
  regime_specific: ['挑市況', 'oos-warn', '樣本外為正，但只有少數市況合格，換市況可能失靈'],
  fragile: ['脆弱', 'oos-warn', '樣本外效力縮水一半以上，不太穩'],
  severe_shrinkage: ['大幅縮水', 'oos-bad', '樣本外只剩不到四分之一，多半是過擬合'],
  overfit: ['過擬合', 'oos-bad', '訓練期看好、樣本外卻變負 → 等於背答案，不是真本事'],
  insufficient_oos: ['資料不足', 'oos-muted', '樣本外事件太少或集中在少數日期，還無法判斷'],
  insufficient_history: ['資料不足', 'oos-muted', '全歷史樣本 <30，無法做樣本外驗證'],
  never_qualified: ['未達標', 'oos-muted', '沒有任何一段訓練期看好過這個策略'],
  no_selected_oos_events: ['資料不足', 'oos-muted', '合格期間內樣本外剛好沒有事件'],
  no_events: ['—', 'oos-muted', '此策略沒有回測事件'],
}
function oosBadge(stat) {
  const b = OOS_BADGE[stat?.oos?.status]
  return b ? { text: b[0], cls: b[1], title: b[2] } : null
}

export default function ConditionPanel({
  conditions, onChange, total, shown, holderReady, industries = [],
  weights = null, combos = null, open: openProp, onOpenChange, id,
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
              return (
                <button key={p.key} className={`preset-chip ${activePreset === p.key ? 'on' : ''}`} style={{ '--i': i }}
                  onClick={() => applyPreset(p.key, p.patch)}>
                  <p.icon size={14} strokeWidth={1.75} />{p.label}
                  {st && <span className={`preset-score ${st.avg_excess > 0 ? 'good' : st.avg_excess < 0 ? 'bad' : ''}`}>
                    {st.avg_excess >= 0 ? '+' : ''}{st.avg_excess}<small>pp</small></span>}
                </button>
              )
            })}
          </div>
          {weights?.signals && (
            <details className="strategy-board">
              <summary>各策略回測戰績（依平均超額排序）</summary>
              <div className="strategy-scroll">
                <table className="strategy-table">
                  <thead><tr><th>策略</th><th>平均超額</th><th title="樣本外驗證：只用過去資料選、拿沒看過的日子驗，看效力是否還在">樣本外</th><th>勝率</th><th>樣本</th></tr></thead>
                  <tbody>
                    {orderedPresets.map(p => {
                      const s = presetStat(p.key, weights)
                      const ob = oosBadge(s)
                      return (
                        <tr key={p.key}>
                          <td>{p.label}</td>
                          <td className={s && s.avg_excess > 0 ? 'good' : s && s.avg_excess < 0 ? 'bad' : ''}>
                            {s ? `${s.avg_excess >= 0 ? '+' : ''}${s.avg_excess}pp` : '尚無回測'}</td>
                          <td>{ob ? <span className={`oos-badge ${ob.cls}`} title={ob.title}>{ob.text}</span> : '—'}</td>
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
                <b>樣本外</b>＝只用過去 1 年資料算、再拿之後沒看過的日子驗，<b>「穩健」才是真本事，「過擬合」是背答案</b>——
                平均超額再高，樣本外過擬合就別太當真。小詩選股取最佳形態；多頭排列／填息快僅供戰績參考、不進 Top5 選股。
                同業低估／外資連買因缺逐日歷史、樣本 0，暫無戰績。
              </p>
            </details>
          )}
          <ComboBoard combos={combos} />
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
