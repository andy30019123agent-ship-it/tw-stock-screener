import { useState } from 'react'
import { ChevronDown, ChevronRight, Dices } from 'lucide-react'

// 條件層級分佈卡（2026-07-26 全面重寫）。
//
// 舊版是「一次買 N 檔的組合分佈」，數字寫死在 MEASURED 常量裡（2026-07-25 一次性回測）。
// 新需求（Andy：不用幫我配好購買組合）拿掉了「買幾檔」這個單位，改成「條件層級」——
// 每天候選池會按 turnover／bias20_pct／high20_gap／rs_pct_60 四個特徵各自切成高/中/低三層，
// 這裡顯示的是「這個層級的股票，歷史上進場後 20 個交易日大概長怎樣」，不是某一批候選的預測。
//
// 資料來源：public/data/tier_stats.json（pipeline/tier_stats.py 算，逐日更新）。
// 一律讀 JSON，不寫死——2026-07-26 重算後 52%／44%／66% 這些舊數字全部作廢，
// 如果又出現這種寫死的數字，就是重蹈舊版的覆轍。
//
// 🔴 兩條硬性限制（實作計畫 Task 8）：
// 1. high20_gap 不可標「偏優」——重算後方向與舊研究相反（high 42.5% vs low 45.8%），是不穩定特徵。
//    只顯示數值當事實。
// 2. 不可用兩層的信賴區間是否重疊來宣稱「差異顯著」——CI 只說明「這一層自己有多不確定」，
//    要證明層級之間有差，需要同日配對比較（第二段 walk-forward 的工作，這裡還沒有）。

const FEATURES = [
  {
    key: 'turnover', label: '成交金額', usedFor: '候選清單「勝率偏優」分類依據',
    hint: '20 日均量 × 收盤價，當日候選池內切三分位',
  },
  {
    key: 'bias20_pct', label: '20 日乖離', usedFor: '候選清單「報酬偏優」分類依據',
    hint: '現價偏離 20 日均線的百分比，當日候選池內切三分位',
  },
  {
    key: 'high20_gap', label: '距 20 日前高', usedFor: null, caution: true,
    hint: '離近 20 日最高價還有多遠，正值＝還沒到前高',
  },
  {
    key: 'rs_pct_60', label: '60 日相對強弱百分位', usedFor: null,
    hint: '近 60 日報酬在全市場的百分位排名',
  },
]
const LEVELS = [['high', '高（前 1/3）'], ['mid', '中（中間 1/3）'], ['low', '低（後 1/3）']]

const pct1 = v => `${v.toFixed(1)}%`
const signedPct = v => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`

function FeatureBlock({ meta, data }) {
  if (!data) return null
  return (
    <div className="os-feat">
      <div className="os-feat-head">
        <span className="os-feat-label">{meta.label}</span>
        {meta.usedFor
          ? <span className="os-feat-used">{meta.usedFor}</span>
          : <span className="os-feat-unused">目前不用於分類，僅供參考</span>}
      </div>
      {meta.caution && (
        <p className="os-warn os-feat-caution">
          <b>⚠️ 這項方向不穩定</b>：2026-07-26 重算後與舊研究方向相反，只當事實數值看，
          <b>不代表「離前高越遠越好」或「越近越好」</b>，本站不會把它標成偏優。
        </p>
      )}
      <div className="os-scroll">
        <table className="os-table os-feat-table">
          <thead>
            <tr>
              <th>層級</th>
              <th title="成本後絕對報酬 > 0 的比例">賺錢機率</th>
              <th title="19 個約當獨立批次、400 次 moving-block bootstrap 算出的 90% 信賴區間——只說明這一層自己有多不確定，不能拿來跟別層比顯著性">獨立樣本／90% CI</th>
              <th>賺時平均</th>
              <th>賠時平均</th>
              <th>中位數</th>
            </tr>
          </thead>
          <tbody>
            {LEVELS.map(([lvKey, lvLabel]) => {
              const d = data[lvKey]
              if (!d) return <tr key={lvKey}><td>{lvLabel}</td><td colSpan={5}>—</td></tr>
              return (
                <tr key={lvKey}>
                  <td>{lvLabel}</td>
                  <td><b>{Math.round(d.win_rate * 100)}%</b></td>
                  <td className="os-ci">{d.blocks} 批 · [{d.ci90[0]}, {d.ci90[1]}]</td>
                  <td className="good">{signedPct(d.avg_win_pct)}</td>
                  <td className="bad">{signedPct(d.avg_loss_pct)}</td>
                  <td className={d.median_pct > 0 ? 'good' : 'bad'}>{signedPct(d.median_pct)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function OutcomeShape({ tierStats }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="os">
      <button className="os-toggle" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        {open ? <ChevronDown size={16} strokeWidth={2} /> : <ChevronRight size={16} strokeWidth={2} />}
        <Dices size={15} strokeWidth={1.75} />條件層級的歷史分佈（不是這批候選，是這整層歷史上長怎樣）
      </button>

      {open && (<>
        {!tierStats ? (
          <p className="os-warn">
            <b>條件層級歷史分佈暫時取不到</b>——這通常是資料管線問題，不影響上面的候選清單本身；
            隔天自動更新後會恢復。
          </p>
        ) : (<>
          <p className="os-note">
            資料日期 <b>{tierStats.date || '—'}</b>｜持有 <b>{tierStats.forward_days ?? 20}</b> 個交易日再檢視｜
            數字已扣來回交易成本 <b>{tierStats.cost_pct}%</b>（手續費＋證交稅＋滑價）。
            <br />
            <b>不是個股勝率。</b>這裡只顯示「這個條件層級」歷史上的分佈，不顯示任何一檔股票自己的精確勝率——
            樣本是同一層裡成千上萬筆歷史事件的統計，不是這檔股票單獨的成績。
          </p>

          {FEATURES.map(meta => (
            <FeatureBlock key={meta.key} meta={meta} data={tierStats.features?.[meta.key]} />
          ))}

          <p className="os-note">
            <b>⚠️ 先看信賴區間，再看數字大小。</b>
            持有 20 交易日彼此重疊，{tierStats.date ? '長歷史' : '樣本'}換算下來每個層級只有約
            <b> {tierStats.features?.turnover?.high?.blocks ?? 19} 批</b>獨立進場，所以每一格都附了信賴區間。
            <b>兩層的信賴區間有重疊，不代表兩層一樣，也不代表哪層一定比較好</b>——那需要同一天配對比較才量得出來，
            這裡還沒做，看到重疊時只能說「目前量不出誰比較好」。
          </p>
        </>)}
      </>)}
    </div>
  )
}
