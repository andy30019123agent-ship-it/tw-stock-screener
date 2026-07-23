import { useState } from 'react'
import {
  SlidersHorizontal, Search, ChevronDown,
  Rocket, BookOpen, Gem, Sparkles, Landmark, TrendingUp,
} from 'lucide-react'

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

export default function ConditionPanel({
  conditions, onChange, total, shown, holderReady, industries = [],
  open: openProp, onOpenChange, id,
}) {
  const c = conditions
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
        {/* 一鍵套用 */}
        <div className="cond-presets">
          <span className="cond-section-label">快速套用</span>
          <div className="preset-row">
            {PRESETS.map((p, i) => (
              <button key={p.key} className={`preset-chip ${activePreset === p.key ? 'on' : ''}`} style={{ '--i': i }}
                onClick={() => applyPreset(p.key, p.patch)}>
                <p.icon size={14} strokeWidth={1.75} />{p.label}
              </button>
            ))}
          </div>
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
    <label className={`toggle ${checked ? 'checked' : ''} ${accent ? 'accent' : ''} ${disabled ? 'disabled' : ''}`}>
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
