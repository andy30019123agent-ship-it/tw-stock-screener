export default function ConditionPanel({ conditions, onChange, total, shown }) {
  const c = conditions
  const set = (key, value) => onChange({ ...c, [key]: value })

  return (
    <div className="cond-panel">
      <div className="cond-row cond-checks">
        <Toggle label="✨ 糾結後黃金交叉→多頭發散" hint="綜合訊號"
          checked={c.signalMa} onChange={v => set('signalMa', v)} accent />
        <Toggle label="多頭排列" hint="MA5>10>20>60"
          checked={c.bullAligned} onChange={v => set('bullAligned', v)} />
        <Toggle label="近期黃金交叉" hint="MA5 上穿 MA20"
          checked={c.goldenCross} onChange={v => set('goldenCross', v)} />
        <Toggle label="均線上彎" hint="均線翻揚"
          checked={c.maRising} onChange={v => set('maRising', v)} />
      </div>

      <div className="cond-row cond-chips">
        <div className="num-field">
          <label>外資連買 ≥</label>
          <input type="number" min="0" max="30" value={c.foreignDays}
            onChange={e => set('foreignDays', parseInt(e.target.value) || 0)} />
          <span>天</span>
        </div>
        <div className="num-field">
          <label>投信連買 ≥</label>
          <input type="number" min="0" max="30" value={c.trustDays}
            onChange={e => set('trustDays', parseInt(e.target.value) || 0)} />
          <span>天</span>
        </div>
        <div className="logic-toggle">
          <button className={c.chipLogic === 'and' ? 'on' : ''}
            onClick={() => set('chipLogic', 'and')}>外資＋投信都要</button>
          <button className={c.chipLogic === 'or' ? 'on' : ''}
            onClick={() => set('chipLogic', 'or')}>任一即可</button>
        </div>
        <input className="search" type="search" placeholder="搜尋代號／名稱"
          value={c.keyword} onChange={e => set('keyword', e.target.value)} />
      </div>

      <div className="cond-summary">
        符合 <b>{shown}</b> 檔 ／ 共 {total} 檔
      </div>
    </div>
  )
}

function Toggle({ label, hint, checked, onChange, accent }) {
  return (
    <label className={`toggle ${checked ? 'checked' : ''} ${accent ? 'accent' : ''}`}>
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      <span className="toggle-label">{label}</span>
      {hint && <span className="toggle-hint">{hint}</span>}
    </label>
  )
}
