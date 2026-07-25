import { useState } from 'react'
import { ChevronDown, ChevronRight, ListOrdered } from 'lucide-react'

// 「我只想買幾檔？」——把「買少」的代價攤開（Andy 2026-07-25 要求：不想每天下一堆單）。
//
// ⚠️ 這張卡原本的設計是「把前 3 名標成最高信心」，**實測後推翻了**：
//   名次跟品質沒有關係。第 2 名是全場最差（賺錢率 45.1%、中位超額 −4.35pp），
//   第 8 名反而不錯（54.9%）；「前 3 名」與「第 4~8 名」的配對差是 −0.26%、t=−0.22。
//   也就是說「只買前幾名」**不是挑到更好的股票，只是把注押得更集中**。
//   給一個沒有證據的「最高信心」標籤，等於用介面說謊——所以改成攤開代價讓使用者自己決定。
//
// 數字來源：verify_top5_procedure.py 的重播快取，2025-02-05~2026-06-25 共 339 次進場，
// 持有 20 交易日、扣完來回成本 0.78%。「買 N 檔」＝照名單順序買前 N 檔（使用者實際會做的事）。
// 改 TOP_N 或改排序都要回來重算（見 pipeline/opportunities.py 的 TOP_N 註解）。
const COST_OF_FEWER = {
  asOf: '2026-07-25',
  entries: 339,
  rows: [
    { n: 1, winMoney: 0.560, mean: 8.85, worst: -44.2, sd: 29.2 },
    { n: 2, winMoney: 0.552, mean: 5.93, worst: -40.1, sd: 21.1 },
    { n: 3, winMoney: 0.596, mean: 6.03, worst: -33.1, sd: 17.1 },
    { n: 5, winMoney: 0.661, mean: 5.75, worst: -28.3, sd: 14.6 },
    { n: 8, winMoney: 0.667, mean: 6.19, worst: -31.7, sd: 13.9, full: true },
  ],
  // 名次無區辨力的證據（上面註解的來源），寫出來讓人能質疑
  rankEvidence: { top3: 0.596, rest5: 0.625, pairedDiff: -0.26, t: -0.22 },
  worstRank: { rank: 2, winMoney: 0.451, medianExcess: -4.35 },
}

const pctOf = v => `${Math.round(v * 100)}%`

export default function HowManyToBuy({ pickCount }) {
  const [open, setOpen] = useState(false)
  const full = COST_OF_FEWER.rows.find(r => r.full)

  return (
    <div className="hm">
      <button className="hm-toggle" onClick={() => setOpen(o => !o)} aria-expanded={open}>
        {open ? <ChevronDown size={16} strokeWidth={2} /> : <ChevronRight size={16} strokeWidth={2} />}
        <ListOrdered size={15} strokeWidth={1.75} />我只想買幾檔？先看代價
      </button>

      {open && (<>
        <p className="hm-lead">
          <b>名次不代表品質——這點很反直覺，但實測是這樣。</b>
          「前 3 名」與「第 4~8 名」的賺錢機率是 {pctOf(COST_OF_FEWER.rankEvidence.top3)} vs{' '}
          {pctOf(COST_OF_FEWER.rankEvidence.rest5)}，配對差 {COST_OF_FEWER.rankEvidence.pairedDiff}%、
          t 值 {COST_OF_FEWER.rankEvidence.t}（<b>測不出差異</b>）。
          單看名次更誇張：<b>第 {COST_OF_FEWER.worstRank.rank} 名是全場最差的位置</b>
          （賺錢機率只有 {pctOf(COST_OF_FEWER.worstRank.winMoney)}、中位超額 {COST_OF_FEWER.worstRank.medianExcess}pp）。
          <br />
          所以<b>「只買前幾名」不是挑到更好的股票，是把同樣的賭注押得更集中</b>。
          下表是這個集中的代價：
        </p>

        <div className="hm-scroll">
          <table className="hm-table">
            <thead><tr>
              <th>照順序買</th>
              <th title="絕對報酬扣掉成本後 > 0 的比率——也就是「這批真的賺到錢」的機率">賺錢機率</th>
              <th>平均賺</th>
              <th title="339 次進場中最慘的那一次">最慘一次</th>
              <th title="批次之間的落差，越大代表結果越靠運氣">波動</th>
            </tr></thead>
            <tbody>
              {COST_OF_FEWER.rows.map(r => (
                <tr key={r.n} className={r.n === pickCount ? 'hm-cur' : ''}>
                  <td>{r.n} 檔{r.full && <small>完整名單</small>}</td>
                  <td className={r.winMoney >= 0.65 ? 'good' : ''}>{pctOf(r.winMoney)}</td>
                  <td>+{r.mean.toFixed(2)}%</td>
                  <td className="bad">{r.worst.toFixed(1)}%</td>
                  <td>{r.sd.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="hm-note">
          <b>怎麼讀這張表</b>：平均賺的幅度幾乎不隨檔數變化（買 1 檔的 +8.85% 是被少數飆股拉高的），
          但<b>賺錢機率從 {pctOf(full.winMoney)} 掉到 {pctOf(COST_OF_FEWER.rows[0].winMoney)}</b>、
          最慘一次從 {full.worst}% 惡化到 {COST_OF_FEWER.rows[0].worst}%、
          波動從 {full.sd} 暴增到 {COST_OF_FEWER.rows[0].sd}。
          <br />
          <b>買越少不是賺越少，是「越靠運氣」</b>。如果你只想下 3 筆單，
          建議接受它是一個運氣成分明顯較大的選擇——而不是以為自己買到了「最精華的 3 檔」。
          <br />
          <small>
            量測 {COST_OF_FEWER.asOf}｜{COST_OF_FEWER.entries} 次進場｜持有 20 交易日、已扣來回成本 0.78%
            ｜⚠️ 持有期重疊，有效獨立批次約 17 批，機率的誤差約 ±12pp，別把差幾個百分點當精確排名
          </small>
        </p>
      </>)}
    </div>
  )
}
