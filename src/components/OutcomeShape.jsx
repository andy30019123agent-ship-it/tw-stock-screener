import { useState } from 'react'
import { ChevronDown, ChevronRight, Dices } from 'lucide-react'

// 「這批推薦大概會怎樣」——報酬分佈卡（Andy 2026-07-25 要求 2️⃣）。
//
// 為什麼需要：站上每個數字都是**平均值**，但這套系統的報酬極度右偏（少數大賺撐起整體）。
// 只看平均會讓人在正常的虧損期誤判成「系統壞了」而放棄——而放棄恰好是這種形狀最大的虧損來源。
// 所以要把「典型會發生什麼」「最壞大概多壞」直接寫出來。
//
// ⚠️ 這些數字來自一次性的程序回測（`verify_top5_procedure.py`，2026-07-25 跑），**不是每日更新**。
// 因此寫死在這裡並標註量測日期與樣本；資料重跑後要回來更新（下面 MEASURED.asOf 就是提醒）。
// 不從 JSON 讀是刻意的：假裝它會自動更新，比寫死更危險。
const MEASURED = {
  asOf: '2026-07-25',
  window: '2025-02-05 ~ 2026-06-25（339 個交易日）',
  // ⚠️ 對應線上真正在跑的設定（Top8 ＋ rs_pct_60 排序）。改設定要回來重算這裡（見
  // pipeline/opportunities.py 的 TOP_N 註解）——寫死的量測值一旦設定改了就是錯的。
  // 每日等權組合，持有 20 交易日。winRate＝贏過同日全市場平均；winMoney＝**實際賺到錢**
  // （絕對報酬扣成本後 > 0）。這兩個是不同的事：空頭時可以贏大盤但帳戶還是虧的。
  batches: [
    { n: 5, mean: 3.56, median: 2.82, winRate: 0.581, winMoney: 0.661, absMean: 5.75, sd: 11.77, t: 2.17, maxDD: 19.4 },
    { n: 8, mean: 4.00, median: 2.62, winRate: 0.625, winMoney: 0.667, absMean: 6.19, sd: 10.58, t: 2.73, maxDD: 15.8 },
    { n: 10, mean: 3.69, median: 1.93, winRate: 0.628, winMoney: 0.658, absMean: 5.88, sd: 9.49, t: 2.80, maxDD: 14.3 },
    { n: 20, mean: 3.38, median: 2.46, winRate: 0.634, winMoney: 0.720, absMean: 5.57, sd: 6.79, t: 3.52, maxDD: 9.7 },
  ],
  // 勝率的誤差：持有 20 天彼此重疊 → 有效獨立批次只有 339/20 ≈ 17 批，勝率標準誤約 ±12pp。
  // 這是這張表最重要的註腳：檔數之間的勝率差距**幾乎都在誤差內**，不要拿來當精確排名。
  winMoneySE: 12,
  effBatches: 17,
  nDays: 339,
  single: { median: -1.13, winRate: 0.478, n: 3390 },
  topContrib: { stocks: 8, share: 0.488 },
  benchmark0050: { mean: 1.85, median: 1.68, winRate: 0.640, winMoney: 0.742 },
  vsBenchmark: { n: 10, diff: 2.03, t: 1.16 },
}

const pct = v => `${v >= 0 ? '+' : ''}${v.toFixed(2)}pp`

export default function OutcomeShape({ pickCount = 5 }) {
  const [open, setOpen] = useState(false)
  // 🔴 2026-07-25（Codex 指出）：原本 `|| MEASURED.batches[0]`——候選不足時可能回 7 檔，
  // 找不到量測列就**靜默套用 5 檔的統計**，等於用錯的數字騙人。現在明確標示「沒有量測」。
  const cur = MEASURED.batches.find(b => b.n === pickCount) || null

  return (
    <div className="os">
      <button className="os-toggle" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        {open ? <ChevronDown size={16} strokeWidth={2} /> : <ChevronRight size={16} strokeWidth={2} />}
        <Dices size={15} strokeWidth={1.75} />這批大概會怎樣？（實測分佈，不是預測）
      </button>

      {open && (<>
        {cur ? (
          <div className="os-key">
            <div className="os-stat">
              <span className="os-lab">典型結果（中位數）</span>
              <b className={cur.median > 0 ? 'good' : 'bad'}>{pct(cur.median)}</b>
              <small>一半的批次比這個好、一半比這個差</small>
            </div>
            <div className="os-stat">
              <span className="os-lab">實際賺到錢的機率</span>
              <b>{Math.round(cur.winMoney * 100)}%</b>
              <small>誤差約 ±{MEASURED.winMoneySE}pp（見下方說明）；平均賺 {cur.absMean}%</small>
            </div>
            <div className="os-stat">
              <span className="os-lab">整批贏過大盤的機率</span>
              <b>{Math.round(cur.winRate * 100)}%</b>
              <small>跟上面那個不同：空頭時可能贏大盤但帳戶仍虧</small>
            </div>
            <div className="os-stat">
              <span className="os-lab">波動（標準差）</span>
              <b>{cur.sd.toFixed(1)}pp</b>
              <small>批次之間的落差有這麼大</small>
            </div>
          </div>
        ) : (
          /* 檔數不在量測過的組合裡（例如候選不足只給了 7 檔）→ 明說沒有對應數字，
             不可拿最接近的那組來套（那等於顯示錯的統計）。下面的對照表照樣有參考價值。 */
          <p className="os-warn">
            <b>今天是 {pickCount} 檔，這個檔數沒有單獨量測過</b>——下表只量過 5／10／20 檔。
            不硬套最接近的那組數字（那會顯示錯的統計），請把下表當範圍參考。
          </p>
        )}

        <p className="os-warn">
          <b>⚠️ 單獨看一檔的話，典型結果是輸大盤 {Math.abs(MEASURED.single.median).toFixed(2)}pp、
          只有 {Math.round(MEASURED.single.winRate * 100)}% 會贏過大盤</b>
          （{MEASURED.single.n.toLocaleString()} 次推薦的實測）。
          整體之所以是正的，是因為 <b>{MEASURED.topContrib.stocks} 檔股票貢獻了{' '}
          {Math.round(MEASURED.topContrib.share * 100)}% 的全部超額</b>。
          <br />
          這代表兩件事：<b>①不能只買一兩檔</b>——很可能剛好都是那些「小輸」的；
          <b>②不能在賠錢時提早放棄</b>——大賺的那幾檔中途也會回檔。
        </p>

        <div className="os-scroll">
          <table className="os-table">
            <thead><tr>
              <th>一批買幾檔</th><th>平均</th><th>中位數</th><th>贏大盤機率</th>
              <th title="絕對報酬扣掉成本後 > 0 的比率。這跟「贏大盤」是兩件事——空頭時可以贏大盤但帳戶還是虧的">實際賺錢機率</th>
              <th>波動</th>
              <th title="複利計算下最大的累積回撤，數字越小越不折磨人">最大回撤</th>
              <th title="統計顯著性（t 值，已做同日群聚與序列相關校正）。約 &gt;2 才算有訊號">t 值</th>
            </tr></thead>
            <tbody>
              {MEASURED.batches.map(b => (
                <tr key={b.n} className={b.n === pickCount ? 'os-cur' : ''}>
                  <td>{b.n} 檔{b.n === pickCount && <small>目前</small>}</td>
                  <td>{pct(b.mean)}</td>
                  <td className={b.median > 0 ? 'good' : 'bad'}>{pct(b.median)}</td>
                  <td>{Math.round(b.winRate * 100)}%</td>
                  <td>{Math.round(b.winMoney * 100)}%</td>
                  <td>{b.sd.toFixed(1)}</td>
                  <td>−{b.maxDD.toFixed(1)}pp</td>
                  <td className={b.t >= 2 ? 'good' : ''}>{b.t.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="os-note">
          <b>⚠️ 先看誤差，再看排名。</b>
          持有 20 交易日彼此重疊，所以 {MEASURED.nDays} 天其實只等於約
          <b> {MEASURED.effBatches} 批</b>獨立的進場，
          勝率的誤差約 <b>±{MEASURED.winMoneySE} 個百分點</b>。
          也就是說上表裡<b>檔數之間的勝率差距幾乎都在誤差內</b>——不要把它當精確排名，
          「8 檔 66.7% 比 10 檔 65.8% 好」這種話是量不出來的。
          <br />
          真正單調、看得出方向的只有一件事：<b>檔數越多，結論越可信</b>
          （t 值 {MEASURED.batches[0].t} → {MEASURED.batches[3].t}），
          而且波動與回撤明顯變小（sd {MEASURED.batches[0].sd} → {MEASURED.batches[3].sd}、
          回撤 −{MEASURED.batches[0].maxDD} → −{MEASURED.batches[3].maxDD}pp）。
          <br />
          {/* 為什麼是 8：不是因為量得出最好，是因為在測不出差別的範圍內取「精簡」那端。
              往下砍到 4~5 檔會開始掉 t 值、單檔運氣成分變大（一次進場最慘 −44%）。 */}
          <b>所以檔數選 8 的理由不是「它最好」</b>，是在這段測不出差別的範圍裡取比較精簡的那一端；
          再往下砍到 4~5 檔就會開始付代價（可信度下降、單一檔的運氣成分變大）。
        </p>

        <p className="os-note os-honest">
          <b>必須誠實講的兩件事。</b>
          ①{cur ? <>目前 {pickCount} 檔的 t 值是 {cur.t}——</> : <>{pickCount} 檔沒有量測過 t 值——</>}
          {cur && cur.t >= 2
            ? <>剛好過了一般認定的 2 門檻，<b>但這是「勉強站得住」不是「證明有效」</b>。</>
            : cur
              ? <><b>統計上還無法排除「這只是運氣」</b>（一般要 &gt;2）。</>
              : <>量測過的 5／10／20 檔分別是 1.78／2.38／3.00，可作範圍參考。</>}
          ②跟最簡單的做法（買 0050）比：0050 在同一把尺是平均 {pct(MEASURED.benchmark0050.mean)}、
          中位 {pct(MEASURED.benchmark0050.median)}、贏大盤 {Math.round(MEASURED.benchmark0050.winRate * 100)}%，
          而<b>「實際賺到錢」的機率是 {Math.round(MEASURED.benchmark0050.winMoney * 100)}%——比本系統任何檔數都高</b>
          （最高的 20 檔是 {Math.round(MEASURED.batches[3].winMoney * 100)}%）。
          差別在幅度：0050 平均賺 4.22%、本系統 8 檔 {MEASURED.batches[1].absMean}%。
          <b>0050 賺得更常、本系統賺得更多</b>，這是取捨不是優劣。
          {MEASURED.vsBenchmark.n === pickCount
            ? <>本系統減掉 0050 是 {pct(MEASURED.vsBenchmark.diff)}，但 t 只有 {MEASURED.vsBenchmark.t}
              → <b>測不出「比直接買 0050 更好」</b>。</>
            : <><b>「本系統 − 0050」的配對檢定只量過 {MEASURED.vsBenchmark.n} 檔那組</b>
              （+{MEASURED.vsBenchmark.diff}pp、t={MEASURED.vsBenchmark.t}＝測不出差異），
              <b>{pickCount} 檔這組還沒單獨量過</b>，所以不能直接套用。</>}
          <br />
          量測時間 {MEASURED.asOf}｜區間 {MEASURED.window}｜這些是歷史統計，不是未來保證。
        </p>
      </>)}
    </div>
  )
}
