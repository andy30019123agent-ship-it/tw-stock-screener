import { normalizeExitSummary, fmtPct, siteRow } from '../lib/exitSummary'

// 「防守價」照實說明 ＋「各條停損線的代價」對照表（Andy 2026-11-13 決定：規則不換，只改說明並附代價表）。
// 數字全部讀 exit_rules_summary.json（出自 _reports/研究_出場規則_2026-11-13.md），這裡不寫死任何研究數字。
// 讀不到／缺欄位 → 表格整塊不顯示，只留一句中性說明；說明文字本身不含數字，所以照常顯示。
export default function ExitDefense({ exitSummary }) {
  const sum = normalizeExitSummary(exitSummary)
  const site = siteRow(sum)
  return (
    <div className="exd">
      <p>
        <b>防守價是什麼：</b>「現價 −15%」與「20 日均線（月線）」兩個價位<b>取較高的那一個</b>
        （月線要在現價下方才算；在現價上方就退回 −15%）。它只是一條參考線，網站不會替你賣，也不是建議你設在哪裡。
      </p>
      <ul>
        <li>
          <b>實際上多半是月線在當停損。</b>月線通常離現價比 15% 近得多，所以這條線比「−15%」這個字面看起來緊。
          {site && <>歷史上照這條線，約 <b>{fmtPct(site.stop_rate)}</b> 的候選在 {sum.holdDays} 天內會碰到，
            其中本來抱滿會賺的有 <b>{fmtPct(site.miscut_winners)}</b> 被先洗出場。</>}
        </li>
        <li>
          <b>它的作用是壓低極端單筆虧損，不是提高報酬。</b>
          歷史資料分不出哪一條停損線比較好，也看不出「設停損」比「抱滿 {sum?.holdDays ?? 20} 天」多賺；
          停損換到的是最慘的幾筆不那麼慘，代價是賺錢的次數變少。
        </li>
        <li>
          <b>跌了才賣，歷史上平均沒有比續抱好。</b>
          但按「每天一票」算時誤差範圍跨過 0，也就是量不出差別——所以不能說「跌多少就該跑」，反過來也不能說抱著比較對。
        </li>
      </ul>

      {sum ? (
        <>
          <p className="exd-title"><b>各條停損線的代價</b>（買進後 {sum.holdDays} 天內，這不是建議，取捨由你決定）</p>
          <div className="exd-scroll" role="region" aria-label="各條停損線的代價對照表" tabIndex={0}>
            <table className="exd-table">
              <thead>
                <tr>
                  <th>規則</th>
                  <th>{sum.holdDays} 天內觸發率</th>
                  <th>誤砍最後會賺的比例</th>
                  <th>賺錢機率</th>
                  <th>最慘 5%</th>
                  <th>最慘單筆</th>
                </tr>
              </thead>
              <tbody>
                {sum.rows.map(r => (
                  <tr key={r.key || r.label} className={r.key === 'site15ma' ? 'exd-site' : ''}>
                    <td>{r.label}</td>
                    <td>{fmtPct(r.stop_rate)}</td>
                    <td>{fmtPct(r.miscut_winners)}</td>
                    <td>{fmtPct(r.win_rate)}</td>
                    <td>{fmtPct(r.p5)}</td>
                    <td>{fmtPct(r.worst)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="exd-foot">
            量測期間 {sum.first}～{sum.last}，{sum.n.toLocaleString('en-US')} 筆候選，但持有期互相重疊，
            約等於 {sum.batches} 批獨立樣本。成交用保守假設：盤中碰到停損價，隔天開盤才賣（跳空多低就賣多低，所以最慘單筆會比停損線深很多）。
            資料不含下市的股票，也看不到跌停鎖死賣不掉的情況，<b>實際只會更差</b>。
            非投資建議，歷史不代表未來。
          </p>
        </>
      ) : (
        <p className="exd-foot">各條停損線的歷史代價對照表暫時取不到，之後資料更新會自動補上；在那之前這裡不顯示任何停損數字。</p>
      )}
    </div>
  )
}
