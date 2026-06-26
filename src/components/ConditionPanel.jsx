import { useState } from 'react'

const isMobile = () =>
  typeof window !== 'undefined' && window.matchMedia('(max-width: 720px)').matches

// 一鍵套用的常用組合（會覆蓋現有勾選，但保留搜尋關鍵字）
const BLANK = {
  signalMa: false, breakout: false, bullAligned: false, goldenCross: false,
  maRising: false, bigHolderRising: false, foreignDays: 0, trustDays: 0,
}
const PRESETS = [
  { key: 'breakout', label: '🚀 爆量突破', patch: { ...BLANK, breakout: true } },
  { key: 'signal', label: '✨ 糾結轉強', patch: { ...BLANK, signalMa: true } },
  { key: 'foreign', label: '🏦 外資連買', patch: { ...BLANK, foreignDays: 3, trustDays: 0 } },
  { key: 'bull', label: '📈 多頭排列', patch: { ...BLANK, bullAligned: true } },
]

export default function ConditionPanel({ conditions, onChange, total, shown, holderReady, industries = [] }) {
  const c = conditions
  const set = (key, value) => onChange({ ...c, [key]: value })
  const applyPreset = patch => onChange({ ...c, ...patch })
  // 手機預設收合，桌機預設展開
  const [open, setOpen] = useState(() => !isMobile())

  return (
    <div className={`cond-panel ${open ? 'open' : 'collapsed'}`}>
      <button className="cond-toggle" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        <span className="cond-toggle-label">篩選條件</span>
        <span className="cond-toggle-count">符合 <b key={shown}>{shown}</b> ／ {total}</span>
        <Chevron open={open} />
      </button>

      <div className="cond-body">
        {/* 一鍵套用 */}
        <div className="cond-presets">
          <span className="cond-section-label">快速套用</span>
          <div className="preset-row">
            {PRESETS.map((p, i) => (
              <button key={p.key} className="preset-chip" style={{ '--i': i }}
                onClick={() => applyPreset(p.patch)}>
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* 範圍：市場 / 產業 */}
        <div className="cond-group">
          <span className="cond-section-label">範圍</span>
          <div className="cond-chips">
            <div className="logic-toggle">
              {[['all', '全部'], ['上市', '上市'], ['上櫃', '上櫃']].map(([m, label]) => (
                <button key={m} className={c.market === m ? 'on' : ''}
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
            <Toggle label="🚀 爆量突破起漲" hint="悶久→帶量突破創高"
              checked={c.breakout} onChange={v => set('breakout', v)} accent />
            <Toggle label="多頭排列" hint="MA5>10>20>60"
              checked={c.bullAligned} onChange={v => set('bullAligned', v)} />
            <Toggle label="近期黃金交叉" hint="MA5 上穿 MA20"
              checked={c.goldenCross} onChange={v => set('goldenCross', v)} />
            <Toggle label="均線上彎" hint="均線翻揚"
              checked={c.maRising} onChange={v => set('maRising', v)} />
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
            <div className="logic-toggle">
              <button className={c.chipLogic === 'and' ? 'on' : ''}
                onClick={() => set('chipLogic', 'and')}>外資＋投信都要</button>
              <button className={c.chipLogic === 'or' ? 'on' : ''}
                onClick={() => set('chipLogic', 'or')}>任一即可</button>
            </div>
            <Toggle label="千張大戶上升" hint={holderReady ? '占比較上週增加' : '資料累積中'}
              checked={c.bigHolderRising} onChange={v => set('bigHolderRising', v)}
              disabled={!holderReady} />
          </div>
        </div>

        <div className="cond-footer">
          <input className="search" type="search" placeholder="🔍 搜尋代號／名稱"
            value={c.keyword} onChange={e => set('keyword', e.target.value)} />
          <div className="cond-summary">
            符合 <b key={shown}>{shown}</b> 檔 ／ 共 {total} 檔
          </div>
        </div>
      </div>
    </div>
  )
}

function Toggle({ label, hint, checked, onChange, accent, disabled }) {
  return (
    <label className={`toggle ${checked ? 'checked' : ''} ${accent ? 'accent' : ''} ${disabled ? 'disabled' : ''}`}>
      <input type="checkbox" checked={checked} disabled={disabled}
        onChange={e => onChange(e.target.checked)} />
      <span className="toggle-label">{label}</span>
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

function Chevron({ open }) {
  return (
    <svg className={`chevron ${open ? 'up' : ''}`} width="16" height="16"
      viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}
