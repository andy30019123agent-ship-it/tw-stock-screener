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
  window: '2025-02 ~ 2026-06（479 個交易日的可評估區間）',
  // 每日 Top5 等權組合，持有 20 交易日，成本後超額（減同日全市場平均）
  batches: [
    { n: 5, mean: 2.47, median: 0.97, winRate: 0.534, sd: 11.8, t: 1.78, maxDD: 27.3 },
    { n: 10, mean: 2.72, median: 1.06, winRate: 0.554, sd: 9.0, t: 2.38, maxDD: 18.8 },
    { n: 20, mean: 2.64, median: 2.12, winRate: 0.640, sd: 6.35, t: 3.00, maxDD: 10.8 },
  ],
  single: { median: -2.14, winRate: 0.464, n: 1695 },   // 單檔推薦的分佈
  topContrib: { stocks: 8, share: 0.836 },              // 8 檔股票貢獻 83.6% 的全部超額
  benchmark0050: { mean: 1.56, median: 1.68, winRate: 0.640 },
  // ⚠️ 這個配對檢定只在 5 檔那組做過（n 記錄檔數）——換檔數就不能直接套用，UI 會據此改文案
  vsBenchmark: { n: 5, diff: 1.43, t: 0.69 },
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
              <span className="os-lab">整批贏過大盤的機率</span>
              <b>{Math.round(cur.winRate * 100)}%</b>
              <small>也就是說約 {Math.round((1 - cur.winRate) * 100)}% 的批次整批輸給大盤</small>
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
              <th>一批買幾檔</th><th>平均</th><th>中位數</th><th>贏大盤機率</th><th>波動</th>
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
                  <td>{b.sd.toFixed(1)}</td>
                  <td>−{b.maxDD.toFixed(1)}pp</td>
                  <td className={b.t >= 2 ? 'good' : ''}>{b.t.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="os-note">
          <b>買越多檔，平均幾乎不變，但「典型結果」明顯變好、折磨程度明顯下降。</b>
          從 5 檔換成 20 檔：平均 {pct(MEASURED.batches[0].mean)} → {pct(MEASURED.batches[2].mean)}（幾乎沒差），
          但中位數 {pct(MEASURED.batches[0].median)} → {pct(MEASURED.batches[2].median)}、
          贏大盤機率 {Math.round(MEASURED.batches[0].winRate * 100)}% → {Math.round(MEASURED.batches[2].winRate * 100)}%、
          最大回撤 −{MEASURED.batches[0].maxDD} → −{MEASURED.batches[2].maxDD}pp。
          這是因為「少數幾檔撐起整體」的形狀下，買太少就是在賭自己剛好抽到那幾檔。
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
          中位 {pct(MEASURED.benchmark0050.median)}、贏大盤 {Math.round(MEASURED.benchmark0050.winRate * 100)}%。
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
