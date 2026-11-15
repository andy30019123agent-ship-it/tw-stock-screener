import { TrendingUp, AlertTriangle, Info, ListChecks, CircleCheck, CircleMinus } from 'lucide-react'
import { usablePair, winDiffText, evDiffText, edgeSentence, staleText, biasNote, evVerdictOf, normalizeTier } from '../lib/tierVerdict'
import { fmtRange } from '../lib/fmtRange'
import { signed, commonReasons, reasonView, sortRuleText, MIN_VOL_LOTS, GATE_LABELS } from '../lib/cardFacts'

// 「依據」分頁（2026-11-16 三分頁改版，Andy 核准方向 A＋C、卡片改方向 B）。由上而下：
//   1. 這份清單怎麼來的（口語版；關卡叫法與卡片上的過關清單一一對應，共用 cardFacts.GATE_LABELS）
//   2. 真實績效紀錄（成績單：實際發出的候選，不是回測）
//   3. 回測結論與證據（原「這些數字怎麼來的」的結論／證據兩層，內容原樣搬來）
//   4. 限制與但書（原「限制」層，內容原樣搬來）
// 原本在主頁、預設收合；現在整頁就是依據，所以直接展開。
// 「條件層級的歷史分佈」照核准規格搬到「工具」分頁。

const isNum = v => typeof v === 'number' && Number.isFinite(v)

const pct1 = v => (isNum(v) ? `${(v * 100).toFixed(1)}%` : '—')
const sPct = (v, d = 1) => (isNum(v) ? `${signed(v, d)}%` : '—')

function usableTier(v) {
  return v && v.win_rate != null && v.avg_win_pct != null && v.avg_loss_pct != null && Array.isArray(v.ci90)
}

function selfVerdict(s) {
  const ev = Number.isFinite(s.ev_pct) ? s.ev_pct : s.win_rate * s.avg_win_pct + (1 - s.win_rate) * s.avg_loss_pct
  const okEvCi = Array.isArray(s.ci90_ev) && isNum(s.ci90_ev[0]) && isNum(s.ci90_ev[1])
  const r = okEvCi ? `（誤差範圍 ${fmtRange(s.ci90_ev, { digits: 1 })}）` : ''
  // 幅度宣稱規則（tierVerdict 檔頭）：下限 ≥0.5 才講優勢、0~0.5 用保守說法，一律附誤差範圍
  let tail
  if (ev <= 0) tail = `扣完成本平均沒有賺${r}`
  else {
    const v = okEvCi ? evVerdictOf(s.ci90_ev) : null
    if (v === 'better') tail = `平均每筆是正的${r}，優勢在賺賠幅度，不是在賺錢機率`
    else if (v === 'marginal') tail = `平均每筆略正${r}，但接近量不出`
    else tail = `平均看起來略正，但誤差範圍跨過 0${r}，還不能說這群自己會賺`
  }
  return { ev, tail }
}

function BasisLayers({ tierStats, gate }) {
  const t = tierStats?.features?.turnover
  const edge = usableTier(tierStats?.categories?.edge) ? tierStats.categories.edge : t?.high
  const rest = tierStats?.categories?.rest
  const ready = usableTier(t?.high) && usableTier(t?.mid) && usableTier(t?.low) && usableTier(edge)
  const stale = staleText(tierStats)
  const head = edgeSentence(tierStats)
  const meta = tierStats?.meta || {}
  const fb = tierStats?.by_gate?.fallback
  const fbE = fb?.categories?.edge?.win_rate, fbR = fb?.categories?.rest?.win_rate
  const notReplayed = Array.isArray(meta.not_replayed) ? meta.not_replayed.map(x => x?.item).filter(Boolean) : []

  let conclusion, evidence
  if (!ready || tierStats?.stale) {
    conclusion = (
      <p>
        條件層級的歷史分佈{stale ? `${stale}，先不引用數字` : '暫時取不到'}，候選清單本身仍正常。
      </p>
    )
  } else {
    const { high: hi, mid, low: lo } = t
    const hp = usablePair(tierStats, 'turnover_high_vs_low')
    const hpWin = winDiffText(hp), hpEv = evDiffText(hp)
    const allBelowHalf = [hi, mid, lo].every(x => x.win_rate < 0.5)
    const sv = selfVerdict(edge)
    conclusion = (<>
      {head && (
        <p><b>跟同一天其他候選比</b>：{head}。
          <span className="opp-basis-aside">（這是每個交易日各算一次差距再平均；下面「證據」是全部筆數合起來算，兩者本來就不同。）</span>
        </p>
      )}
      <p>
        <b>單看這群自己</b>：單檔賺錢機率 <b className="mono">{pct1(edge.win_rate)}</b>{edge.win_rate < 0.5 ? '，不到一半' : '，過半也不代表穩賺'}；
        平均每筆 <b className="mono">{sPct(sv.ev, 2)}</b>，{sv.tail}。兩句講的是不同的比較，不矛盾。
      </p>
      <p className="opp-basis-def">
        <Info size={16} strokeWidth={1.75} aria-hidden="true" />
        <span><b>誤差範圍</b>＝把運氣算進去後，真正的數字大概落在這一段。整段都在 0 以上，才算量得出差別。</span>
      </p>
    </>)
    // 手機 390 寬放得下：誤差範圍放在主數字下一行（一位小數），不另開一列（審計 B1：小數位統一）
    const rng = (c, sign) => fmtRange(c, { digits: 1, sign })
    const rows = [
      ['單檔賺錢機率', s => pct1(s.win_rate), s => rng(s.ci90, false)],
      ['平均每筆', s => sPct(s.ev_pct, 2), s => rng(s.ci90_ev, true)],
      ['賺的時候平均', s => sPct(s.avg_win_pct)],
      ['賠的時候平均', s => sPct(s.avg_loss_pct)],
      ['中位數（典型）', s => sPct(s.median_pct, 2)],
    ]
    const cell = (f, r, s) => (
      <td className={r ? 'big' : ''}>{f(s)}{r && <small>{r(s)}</small>}</td>
    )
    evidence = (<>
      <div className="opp-basis-scroll">
        <table className="opp-basis-table" aria-label="相對優勢與其他候選的歷史對照">
          <caption>歷史上持有 20 個交易日、已扣成本；小字＝誤差範圍</caption>
          <thead><tr><th scope="col"><span className="sr-only">項目</span></th><th scope="col">相對優勢</th>{rest && <th scope="col">其他候選</th>}</tr></thead>
          <tbody>
            {rows.map(([label, f, r]) => (
              <tr key={label}>
                <th scope="row">{label}</th>
                {cell(f, r, edge)}
                {rest && cell(f, r, rest)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        再細看成交金額：候選池裡最高的三分之一，單檔歷史賺錢機率 <b className="mono">{pct1(hi.win_rate)}</b>；最低的三分之一 <b className="mono">{pct1(lo.win_rate)}</b>
        {allBelowHalf ? <>——<b>三層都不到一半</b></> : <>（中段 {pct1(mid.win_rate)}）</>}。
        {hpWin && <>同一天比，高層比低層{hpWin}{hpEv ? `、${hpEv}` : ''}。</>}
      </p>
      <p className="opp-basis-note">
        樣本：歷史上每天重播同一套選股流程後的候選池{meta.date_from && meta.date_to ? `（${meta.date_from}～${meta.date_to}）` : ''}，
        相對優勢共 <b className="mono">{isNum(edge.samples) ? edge.samples.toLocaleString('en-US') : '—'}</b> 筆；
        持有 {tierStats.forward_days ?? 20} 個交易日互相重疊，約等於 <b className="mono">{edge.blocks ?? '—'}</b> 批獨立進場，所以誤差範圍很寬。
        {isNum(tierStats.cost_pct) && <>已扣來回交易成本 {tierStats.cost_pct}%。</>}
        這是整群的統計，<b>不是任何一檔自己的賺錢機率</b>。（{tierStats.date || '—'} 重算）
      </p>
    </>)
  }

  return (<>
    <section className="bt-sec" data-region="回測結論與證據">
      <h2 className="bt-h">回測結論與證據</h2>
      <div className="opp-layer">
        <span className="opp-layer-k">結論</span>
        {conclusion}
      </div>
      <div className="opp-layer">
        <span className="opp-layer-k">證據</span>
        {evidence || <p>歷史對照表暫時取不到。</p>}
        {stale && (
          <p className="opp-basis-warn"><AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" />{stale}，數字可能過時</p>
        )}
        <p className="opp-basis-note">每一層的賺錢機率與誤差範圍，在「工具」分頁的「條件層級的歷史分佈」。</p>
      </div>
    </section>

    <section className="bt-sec" data-region="限制與但書">
      <h2 className="bt-h">限制與但書</h2>
      <div className="opp-layer">
        <span className="opp-layer-k">限制</span>
        <ul className="opp-limits">
          {!tierStats?.stale && isNum(fbE) && isNum(fbR) && (
            <li>
              <b>門檻放寬的弱勢日</b>：過「強勢雙確認」的候選不足 {gate?.min_pool ?? 20} 檔、系統放寬門檻的日子
              {isNum(fb?.meta?.days_total) ? `（歷史 ${fb.meta.days_total} 天）` : ''}，相對優勢 {pct1(fbE)}、其他候選 {pct1(fbR)}
              {fbE < fbR ? '，方向反而相反' : '，差距跟平常不一樣'}。今天門檻{gate?.applied === false ? '沒有' : '有'}套用。
            </li>
          )}
          {notReplayed.length > 0 && (
            <li><b>歷史重播不了的條件</b>：{notReplayed.join('、')}——回測裡都沒套用。</li>
          )}
          <li><b>「離前高」方向不穩定</b>：重算後跟舊研究方向相反，卡片上只當位置看，不代表離前高越遠或越近越好。K 線視窗裡的「近 20 日前高」也只是技術觀察位，不是目標價或預期報酬。</li>
          <li><b>大盤狀態</b>是市場廣度代理（站上月線的比例），不是大盤指數，不會改變選股結果。</li>
          <li><b>這不是幫你配好的購買組合</b>，清單只是整理候選。</li>
          <li><b>這些都是歷史回測</b>，未必代表未來；僅供研究參考，非投資建議。</li>
        </ul>
      </div>
    </section>
  </>)
}

// 這份清單怎麼來的：每一關的叫法跟卡片上的過關清單一樣（GATE_LABELS），順序也一樣。
// 今天的檔數與門檻是否套用讀 opportunities.json；原本主頁清單下方的三句說明（門檻、理由都一樣、乖離排前段）併到這裡。
function HowMade({ opp, tierStats }) {
  const picks = opp?.picks || []
  const poolN = opp?.pool_n ?? picks.length
  const gate = opp?.gate
  const common = commonReasons(picks)
  const anyBias = picks.some(p => normalizeTier(p).biasHigh)
  const sortRule = sortRuleText(picks)
  const gateOn = gate?.applied !== false
  const steps = [
    { k: GATE_LABELS.strong, ok: gateOn, t: gateOn
      ? <>近 60 天、近 120 天的漲幅都排在全市場前段（全市場漲幅前段、回測最穩的門檻）。卡片上寫這檔贏過全市場幾 %。</>
      : <>今天「{gate?.label || GATE_LABELS.strong}」門檻沒套用（過關的不足 {gate?.min_pool ?? 20} 檔或強弱資料算不出來），改看當日有訊號的全部股票。</> },
    { k: GATE_LABELS.signal, ok: true, t: <>當天至少亮一個技術或籌碼訊號，一個都沒亮的刷掉。卡片上列出亮了哪幾個（資料有寫才列）。</> },
    { k: GATE_LABELS.volume, ok: true, t: <>近 20 日平均成交量至少 {MIN_VOL_LOTS} 張。</> },
    { k: GATE_LABELS.revenue, ok: true, t: <>最近一個月營收沒有年減；查不到營收的不剔除，卡片標「營收資料缺」。</> },
  ]
  return (
    <section className="bt-sec bt-how" data-region="這份清單怎麼來的">
      <h2 className="bt-h">這份清單怎麼來的</h2>
      <p className="bt-lead">
        <span>{opp ? <>今天共 <b className="mono">{poolN}</b> 檔候選，每一檔都過了下面這幾關（卡片上的勾就是這幾關）：</> : <>每一檔候選都要過下面這幾關（卡片上的勾就是這幾關）：</>}</span>
      </p>
      <ol className="bt-steps">
        {steps.map(s => (
          <li key={s.k} className={s.ok ? '' : 'is-neutral'}>
            {s.ok ? <CircleCheck size={20} strokeWidth={1.75} aria-hidden="true" /> : <CircleMinus size={20} strokeWidth={1.75} aria-hidden="true" />}
            <span><b>{s.k}</b>：{s.t}</span>
          </li>
        ))}
      </ol>
      <p className="bt-lead"><ListChecks size={16} strokeWidth={1.75} aria-hidden="true" /><span><b>排順序</b>：{sortRule}；排前面沒有證據比較會賺。</span></p>
      <p className="bt-lead"><TrendingUp size={16} strokeWidth={1.75} aria-hidden="true" /><span><b>相對優勢（卡片上的「強在哪」）</b>：成交金額排今天候選前 1/3 的另外分一組，跟漲得強不強無關；其他的叫「其他候選」，沒有分類稱號。</span></p>
      <p className="bt-lead"><AlertTriangle size={16} strokeWidth={1.75} aria-hidden="true" /><span><b>要小心</b>：卡片上這一行只列既有標記（乖離大、乖離排前段、法說會將近、營收資料缺）和近 20 天輸大盤幾個百分點，不另外判斷好壞；清單上的橘點就是這一行有內容。</span></p>
      {common && (
        <p className="bt-lead"><Info size={16} strokeWidth={1.75} aria-hidden="true" />
          <span>今天 {poolN} 檔候選的理由都一樣：「{common.map(r => reasonView(r).text).join('、')}」，所以卡片上不重複列。</span></p>
      )}
      {anyBias && (
        <p className="bt-lead"><Info size={16} strokeWidth={1.75} aria-hidden="true" /><span>{biasNote(tierStats)}</span></p>
      )}
    </section>
  )
}

function Scoreboard({ board }) {
  if (!board) return null
  return (
    <section className="bt-sec" data-region="真實績效紀錄">
      <h2 className="bt-h">真實績效紀錄</h2>
      <p className="bt-lead"><span>這是網站實際發出過的候選、入選後真的走完的結果，不是回測。</span></p>
        <div className="opp-board">
          <span className="opp-board-title"><TrendingUp size={16} strokeWidth={1.75} />候選情報成績單</span>
          {board.samples > 0 ? (
            <div className="opp-board-stats">
              <span>賺錢機率 <b>{Math.round(board.win_rate * 100)}%</b></span>
              <span>平均報酬 <b className={board.avg_ret >= 0 ? 'good' : 'bad'}>{board.avg_ret >= 0 ? '+' : ''}{board.avg_ret}%</b></span>
              <span>樣本 <b>{board.samples}</b></span>
              <span className="opp-muted">（入選後 {board.forward_days} 交易日）</span>
              {board.samples < 20 && <span className="opp-muted">樣本尚少，參考即可</span>}
            </div>
          ) : (
            <span className="opp-muted">樣本累積中——每天留檔，滿 {board.forward_days || 20} 交易日的舊 picks 才計入實績。</span>
          )}
        </div>
    </section>
  )
}

export default function BasisTab({ opp, tierStats, board }) {
  return (
    <div className="bt">
      <HowMade opp={opp} tierStats={tierStats} />
      <Scoreboard board={board} />
      <BasisLayers tierStats={tierStats} gate={opp?.gate} />
    </div>
  )
}
