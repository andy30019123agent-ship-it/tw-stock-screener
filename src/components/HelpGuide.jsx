import { ArrowLeft, BookOpen, AlertTriangle } from 'lucide-react'
import ExitDefense from './ExitDefense'
import { okNum, signalSummary } from '../lib/signalSummary'
import { edgeSentence, edgeWinRateText, staleText, biasNote } from '../lib/tierVerdict'

// 使用說明書（Andy 2026-07-25 要求，選「做進網站」＋「寫給自己看（術語附白話）」）。
//
// 為什麼放站內而不是獨立文件：站上的數字與邏輯會持續改（今天就改了權重基準、加了入場門檻），
// 獨立文件不會跟著更新 → 幾週後就變成過期的錯誤資訊。放站內至少改站時看得到它。
// 走 hash 路由（#help）而非 react-router：零新依賴、可加書籤、GitHub Pages 不必改設定。
//
// 寫法原則（來自今天一整天跟 Andy 解釋這些概念的經驗）：
// 1. 先講「這個數字在回答什麼問題」，再講怎麼算——他要的是能不能拿來做決定。
// 2. 術語一律「白話（術語）」的順序，例如「贏過大盤多少（超額報酬）」。
// 3. 誠實優先：贏不過大盤、樣本不足、提前放行的地方都要寫進來，不能只寫好的一面。

function Section({ id, title, children }) {
  return (
    <section className="help-section" id={id}>
      <h2>{title}</h2>
      {children}
    </section>
  )
}

// 名詞卡：左邊術語、右邊白話。比表格在手機上好讀（表格會橫捲）。
function Term({ word, children }) {
  return (
    <div className="help-term">
      <div className="help-term-word">{word}</div>
      <div className="help-term-body">{children}</div>
    </div>
  )
}

// 條件層級數字一律讀 tier_stats.json（2026-11-13 起，母體＝歷史候選池重播）。讀不到印「—」。
// 🔴 2026-11-13：這裡原本寫死 47.6%／42.5%／50.0%／48.6%／41.4%／−0.4%——全是 2026-07-26
// 用「所有訊號事件」這個錯的母體算的，跟網站上被分類的候選不是同一群股票。
const wrTxt = s => (okNum(s?.win_rate) ? `${(s.win_rate * 100).toFixed(1)}%` : '—')
const pctTxt = v => (okNum(v) ? `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(1)}%` : '—')

// 2026-11-13 可讀性改版：說明書裡原本寫死的回測數字（26 萬筆、37%～43%、+0.84%→+0.04%、120 組 18 組過關、
// +3.77%、1400 多檔、乖離 −1.59%／+2.36% …）全部改讀資料檔；讀不到就略過那一句或印「—」，絕不印舊數字。
// 研究結論本身（例如「2026-07-25 複驗後乖離方向是反的」）保留成帶日期的歷史敘述，但不再附舊數字。
const pp2 = v => (okNum(v) ? `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(2)}%` : '—')
function comboSummary(combos) {
  const list = Array.isArray(combos?.combos) ? combos.combos : null
  if (!list) return null
  const pass = list.filter(c => c.survives_mc === true)
  const med = arr => { const a = arr.filter(okNum).sort((x, y) => x - y); return a.length ? a[Math.floor((a.length - 1) / 2)] : null }
  const top = pass.filter(c => okNum(c.avg_excess)).sort((a, b) => b.avg_excess - a.avg_excess)[0] || null
  return { total: list.length, pass: pass.length, top, medSamples: med(pass.map(c => c.samples)), medDays: med(pass.map(c => c.n_days)) }
}

export default function HelpGuide({ onBack, tierStats, exitSummary, weights, combos, exits, regime, marketCount }) {
  const sig = signalSummary(weights)
  const cmb = comboSummary(combos)
  const rs60 = weights?.signals?.rs_strong_60
  const brk = weights?.signals?.signal_breakout
  // 「樣本外穩健、可是扣完成本是負的」的例子：從資料裡找，找不到就不舉例
  const robustNeg = Object.values(weights?.signals || {}).find(x => x?.oos?.status === 'robust' && okNum(x.net_excess) && x.net_excess < 0) || null
  const regimeDays = regime?.regime_days ? Object.values(regime.regime_days).filter(okNum).reduce((a, b) => a + b, 0) : null
  const pa = weights?.phase_a
  const oosDays = okNum(pa?.total_folds) && okNum(pa?.config?.test_days) ? pa.total_folds * pa.config.test_days : null
  const strat = k => (Array.isArray(exits?.strategies) ? exits.strategies.find(x => x.key === k) : null)
  const h20 = strat('h20')?.avg_net_excess, h40 = strat('h40')?.avg_net_excess
  const bias = tierStats?.stale ? null : tierStats?.features?.bias20_pct
  const biasMedians = bias ? ['high', 'mid', 'low'].map(k => bias[k]?.median_pct).filter(okNum) : []
  const turn = tierStats?.features?.turnover || {}
  const tsDate = tierStats?.date || '—'
  // 2026-11-13 分類簡化：主訊息＝「相對優勢 vs 當天其餘候選」的同日配對差（tierVerdict.edgeSentence，
  // 與網站候選區、TG 快報同一句）；缺資料／stale 走中性句。
  const head = edgeSentence(tierStats)
  const wr = edgeWinRateText(tierStats)
  const stale = staleText(tierStats)
  const helpPairs = head
    ? <>{head}{wr ? `。${wr}` : ''}（{tsDate} 用歷史候選池重算）。這是看完資料才選的比較方式，還需要新資料再驗證。</>
    : <>相對優勢跟其他候選的同日比較數字暫時取不到{stale ? `（${stale}）` : ''}，有分類也可能虧錢。</>
  const medians = ['high', 'mid', 'low'].map(k => turn[k]?.median_pct).filter(okNum)
  return (
    <div className="help">
      <header className="help-head">
        <button className="help-back" onClick={onBack}>
          <ArrowLeft size={16} strokeWidth={2} />回選股頁
        </button>
        <span className="badge-pill"><BookOpen size={14} strokeWidth={1.75} />使用說明書</span>
        <h1>這個網站怎麼用</h1>
        <p className="subtitle">最後更新 2026-11-13 · 站上哪些數字扣過成本、哪些沒扣，第 4 章有對照表</p>
      </header>

      <nav className="help-toc" aria-label="目錄">
        {[['s1', '你每天實際的動作'], ['s2', '候選清單是怎麼選出來的'],
          ['s3', '看數字前必須知道的一件事'], ['s4', '名詞白話對照'],
          ['s5', '自己篩股：條件怎麼選'], ['s6', '組合排行榜怎麼看'],
          ['s7', '這個系統的已知限制']].map(([id, label]) => (
            <a key={id} href={`#help/${id}`} onClick={e => {
              e.preventDefault()
              document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
            }}>{label}</a>
          ))}
      </nav>

      <Section id="s1" title="你每天實際的動作">
        <p>
          這個網站不會幫你配好「今天買這幾檔」——<b>買哪幾檔、買不買，一律由你決定</b>。
          它每天做的事，是把候選股整理好、把歷史上這類股票的賺賠分佈老實攤出來。實際上你該做的四步：
        </p>
        <ol className="help-steps">
          <li>
            <b>晚上收到 TG 快報 → 先看市況那一行。</b>紅色代表多數股票都在跌，這時候不管清單列什麼都該減碼；
            平常沒特別標警示，就是「沒有特別要提醒你的事」。
          </li>
          <li>
            <b>看「相對優勢」那一區。</b>只有一個分類：成交金額在「當天候選池」裡排前 1/3 的，
            標成「<b>相對優勢</b>」；其他候選不給稱號。
            <span className="help-why">
              「相對」的意思是<b>跟同一天的其他候選比</b>，不是說它單檔大概率會賺。歷史上每一天照同一套流程重選候選、
              再分類，結果是：{helpPairs}
              卡片上的「<b>乖離排前段</b>」（當天候選池乖離前 1/3）只是描述，可能掛在任何候選上——{biasNote(tierStats).replace('「乖離排前段」只是描述（當天候選裡乖離前 1/3），', '')}
              （2026-11-13 起分類簡化成這樣：其他分類稱號量不出差別，留在畫面上等於替它背書，所以拿掉了。）
            </span>
          </li>
          <li>
            <b>要買就隔天開盤買。</b>這是網站上所有回測數字用的口徑——訊號當天收盤後才發榜，最快隔天開盤才買得到。
            <span className="help-why">盤中追高、或拖到第三天才買，等於換了一把不同的尺，網站上的勝率／賺賠幅度數字就跟你的實際結果無關了。</span>
          </li>
          <li>
            <b>放 20 個交易日再檢視。</b>這是回測結算的口徑，不是叫你一定要抱滿或一定要出場。
            <span className="help-why">中途帳面先虧很常見，所以才建議放滿 20 日再看，別被前幾天的帳面帶著走。</span>
          </li>
        </ol>

        <div className="help-callout">
          <p><b>三個要先記住的判斷（都有數字支撐，不是感覺）：</b></p>
          <ul>
            <li>
              <b>挑對條件層級，拉不開太大差距。</b>候選池裡成交金額最高的三分之一，歷史賺錢機率 {wrTxt(turn.high)}、
              最低的三分之一 {wrTxt(turn.low)}（{tsDate} 重算，讀網站同一份資料）。
              賺時平均 {pctTxt(turn.high?.avg_win_pct)}、賠時平均 {pctTxt(turn.high?.avg_loss_pct)}——
              每一筆的結果主要由幅度決定，不是挑得準不準。
            </li>
            <li>
              <b>只買一兩檔不是「買到精華」，是把同一批賭注押得更集中。</b>
              這套系統的正報酬是少數幾檔大賺撐起來的（見第 3 章），檔數挑得越少，
              越可能剛好錯過那幾檔、只留下小輸的那些。
            </li>
            <li>
              <b>停損沒有「驗證過的最佳線」。</b>「近 20 日前高（觀察位）」不是出場價，只是技術上的參考點。
              歷史資料分不出哪一條停損線比較好，所以網站不給停損建議，只在下面「防守價與停損的代價」把各條線的代價列給你自己挑。
            </li>
          </ul>
        </div>

        <h3 className="help-sub" id="exit-cost">防守價與停損的代價</h3>
        <ExitDefense exitSummary={exitSummary} />

        <p className="help-note">
          其他區塊（篩選條件、各種戰績表）是給你想深入研究時用的，日常看盤不用每次都打開。
        </p>
      </Section>

      <Section id="s2" title="候選清單是怎麼選出來的">
        <p>三層漏斗，每一層都有回測數字支撐：</p>
        <ol className="help-steps">
          <li>
            <b>全市場</b>（有成交量的上市＋上櫃，已排除 ETF；檔數每天略有變動）
          </li>
          <li>
            <b>→ 先篩「強勢雙確認」</b>：近 60 天漲幅排全市場前 20%，而且近 120 天也排前 30%。
            <span className="help-why">為什麼用這個當第一關：它是所有訊號裡唯一「去掉最極端的樣本後還是賺」而且「拿沒訓練過的時期驗證也站得住」的。</span>
          </li>
          <li>
            {/* 2026-07-26 修正：①「今日 N 檔」是舊 UI 標籤，畫面上現在叫「今日候選」；
                ②寫死的 140~170 檔範圍會過期——2026-07-26 實測只剩 132 檔，已經低於這個範圍，
                改成不寫死具體數字的講法，避免文案跟實際數字對不上。 */}
            <b>→ 再剔除成交量太小、營收年減的，剩下能通過門檻的檔數</b>（畫面上「今日候選」顯示的就是這個數，每天隨市況變動，不是固定範圍）
          </li>
          <li>
            <b>→ 全部列出來，依「近 60 天漲幅在全市場的排名」由高到低排</b>：漲得越強的排越前面（第一關門檻取消的日子，會先看訊號分數、再看這個排名）。
            <span className="help-why">為什麼不是用技術訊號（糾結轉強、縮口帶量突破等）排序：它們扣掉交易成本後，歷史上平均都沒有穩定贏過大盤，所以目前沒有拿它們加分，實際上就是按相對強弱排。哪些訊號有沒有加分，以「各訊號回測勝率」那張表為準，每週會重算。<b>注意這是「排前面」不是「硬篩掉」</b>——候選不會被砍成固定檔數，通過門檻的都照樣列出；卡片的理由若寫「僅符合門檻，按相對強弱排序」，就是這個意思；而如果那天過門檻的不到 20 檔，系統會取消第一關、改看所有有技術訊號的股票，這時理由會直接寫「今天沒套用強勢雙確認門檻…未經強勢篩選」（前面帶一個警示圖示）——看到這句就知道這檔連第一關都沒過。</span>
          </li>
          <li>
            <b>→ 通過的全部列出來，不再砍成固定幾檔</b>，並依「成交金額」與「20 日乖離」在當天候選池裡的
            百分位，成交金額排前 1/3 的標成<b>相對優勢</b>；20 日乖離排前 1/3 的另外掛一個「乖離排前段」描述標籤
            （不代表比較好。跟風險提醒「乖離大」不一樣：「乖離排前段」是跟當天其他候選比的相對排名，「乖離大」是離月線超過 15% 的絕對標準）。
            <span className="help-why">
              2026-07-26 改的：以前這裡會排序後取前 8 檔給你，那等於幫你配好一個組合。
              現在系統只負責告訴你「有哪些候選、各自落在什麼條件層級」，<b>買哪幾檔由你決定</b>。
              <b><AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" />清單的順序不是好壞排名</b>——2026-07-25 實測過「前 3 名 vs 第 4~8 名」的差別
              測不出來，而且第 2 名反而是全場最差的位置。有證據的是「有沒有進這個層級」，
              不是「在層級裡排第幾」。
            </span>
          </li>
        </ol>
        <p className="help-note">
          若某天過門檻的不到 20 檔，系統會取消第一關並在畫面上標「門檻未套用」（帶警示圖示）——看到這行就知道當天的名單品質比平常鬆。
        </p>
      </Section>

      <Section id="s3" title="看數字前必須知道的一件事">
        <div className="help-callout">
          <p>
            <b>這套系統的賺錢方式是「大部分交易小輸給大盤，靠少數幾檔大賺把整體拉成正的」。</b>
          </p>
          <p>
            {sig ? (<>
              用「隔天開盤進場」的口徑回測{okNum(exits?.n_events) ? ` ${exits.n_events.toLocaleString('en-US')} 筆訊號事件` : ''}
              （{weights?.date || '—'} 重算）：
              <b>{sig.n} 個有樣本的訊號，「贏過大盤比例」落在 {Math.round(sig.min * 100)}%～{Math.round(sig.max * 100)}% 之間{sig.anyHalf ? '' : '，沒有一個過半'}</b>。
            </>) : <>各訊號「贏過大盤比例」的回測數字暫時取不到。</>}
            而候選池條件層級的<b>典型結果（中位數）</b>：成交金額最高的那一層中位數 {pctTxt(turn.high?.median_pct)}
            {medians.length ? `（三層裡最差 ${pctTxt(Math.min(...medians))}）` : ''}，{tsDate} 重算。
            平均數字之所以比中位數好看，靠的是少數漲很多的股票。
          </p>
          <p>這不是壞事，很多真實的動能策略都是這個形狀。但它決定了你該怎麼用：</p>
          <ul>
            <li><b>要分散買足夠多檔</b>——只買一兩檔，很可能剛好都是那些「小輸」的。</li>
            <li><b>不要在賠錢時提早放棄</b>——大賺的那幾檔往往中間也會回檔。</li>
            <li><b>不要看到「平均超額 +3%」就以為每筆都賺 3%</b>——那是平均，不是典型。</li>
          </ul>
        </div>
        <p className="help-note">
          所以戰績表裡我特別放了<b>「中位數」</b>和<b>「贏大盤」</b>兩欄，就是要讓這件事一直看得見。
        </p>
      </Section>

      <Section id="s4" title="名詞白話對照">
        <Term word="超額報酬">
          贏過大盤多少。買進後 20 個交易日的報酬，<b>減掉</b>同一天買進全市場所有股票的平均報酬。
          單看「賺了 5%」沒意義——如果那天大盤漲 8%，你其實是輸的。
        </Term>
        <Term word="成本後超額">
          <b>最重要的數字。</b>在上面那個「超額報酬」再扣掉一趟買賣的成本（手續費、證交稅、滑價，來回約 0.785%）。
          這才是你實際能拿到的。
          {okNum(rs60?.avg_excess) && okNum(rs60?.net_excess) && (
            <>例如「{rs60.label}」毛的看起來 {pp2(rs60.avg_excess)}、扣完只剩 {pp2(rs60.net_excess)}，差距就是被成本吃掉的。</>
          )}
        </Term>

        <div className="help-callout">
          <p><b><AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" />站上有些地方還是「沒扣成本」的毛數字，這張表要記住：</b></p>
          <ul>
            <li><b>已扣成本</b>（可以直接信）：快速套用按鈕上的數字、「各策略回測戰績」表的「成本後超額」欄、組合戰績排行榜。</li>
            <li>
              <b>還沒扣成本</b>（要自己心裡扣掉約 0.8%）：
              <b>「本週市況建議」卡</b>、「市況分層」表、「勝率榜／多時間窗」表。
            </li>
          </ul>
          <p className="help-why">
            {okNum(brk?.avg_excess) && okNum(brk?.net_excess) && (
              <>具體差多少：「{brk.label}」不扣成本的平均超額是 {pp2(brk.avg_excess)}，扣掉成本後是 <b>{pp2(brk.net_excess)}</b>
              {brk.net_excess < 0 ? '（輸給大盤）' : ''}（{weights?.date || '—'} 重算）。</>
            )}
            所以那張卡目前只適合用來看「這個市況下哪幾個訊號<b>相對</b>強」，不要當成「會賺多少」。
            我已經把「把這幾處也改成成本後」列進待辦，改好後這段就會拿掉。
          </p>
        </div>
        <Term word="中位數">
          把所有交易的結果從小排到大，正中間那一筆。<b>它代表「典型」，平均值代表「總和分攤」。</b>
          當中位數是負的、平均是正的，就表示少數大賺在撐場面。
        </Term>
        <Term word="樣本外驗證">
          防作弊機制。只用過去一段時間的資料決定「哪個訊號好」，然後拿<b>之後那段沒看過的日子</b>去驗，看效力還剩多少。
          標「穩健」＝真本事；標「過擬合」＝只是背了考古題；標「資料不足」＝樣本太少還不能下結論。
          <span className="help-why">這機制今天證明了自己：「填息快」在場內統計是全場最強，但樣本外一直標「資料不足」——後來補齊資料後發現它根本是負的。</span>
        </Term>
        <Term word="禁得起挑選">
          組合排行榜同時比較{cmb ? ` ${cmb.total} ` : '很多'}組，光靠運氣就會有幾組看起來很強。打勾的代表它的優勢通過了統計檢定
          （Bonferroni 多重比較校正），不太可能只是被挑出來的巧合。
          {cmb && <b>目前 {cmb.total} 組裡{cmb.pass ? `只有 ${cmb.pass} 組過關` : '沒有任何一組過關'}（{combos?.date || '—'} 重算）。</b>}
        </Term>
        <Term word="RS（卡片與表格上那個）">
          <b>這個是「個股近 20 天報酬 － 加權指數近 20 天報酬」。</b>
          看到「RS +21.5%」＝這 20 天贏大盤 21.5 個百分點。正值綠、負值紅。
          <span className="help-why"><AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" />別跟下面那個「全市場排名」搞混——站上有兩種相對強弱，算法不同。候選卡上寫成「近 20 天報酬比大盤 ±X 個百分點」。</span>
        </Term>
        <Term word="全市場排名（強勢雙確認用的）">
          這檔股票的漲幅在全市場排第幾（百分位）。0.9 代表贏過 90% 的股票。
          「強勢雙確認」＝近 60 天排前 20%（≥0.80）且近 120 天排前 30%（≥0.70）。
          <b>這個是跟全市場{okNum(marketCount) ? `約 ${marketCount} 檔有量的` : '其他'}股票比排名，不是跟指數比</b>——因為加權指數存下來的歷史不夠長，
          算不了 60/120 天的比較，所以改用排名繞開。候選卡上的「強弱」寫成「近 60 天漲幅贏過全市場 X% 的股票」，就是這個數字。
        </Term>
        <Term word="乖離">
          現價離 20 日均線多遠。
          <span className="help-why">
            <AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" /><b>這裡有一個常見說法被資料推翻了，值得記住。</b>
            一般都說「乖離太大＝漲一大段了，追進去風險高」，我原本也照這個假設在快報裡對高乖離扣分。
            2026-07-25 複驗後發現<b>方向是反的</b>（高乖離那組反而比低乖離好），所以那個扣分已經移除。
            {bias?.high && bias?.low && okNum(bias.high.ev_pct) && okNum(bias.low.ev_pct) && (
              <>用現在的候選池重算（{tierStats?.date || '—'}）：乖離排前 1/3 的平均每筆 {pctTxt(bias.high.ev_pct)}、賺錢機率 {wrTxt(bias.high)}；
              排後 1/3 的平均每筆 {pctTxt(bias.low.ev_pct)}、賺錢機率 {wrTxt(bias.low)}。</>
            )}
            <b>但也不因此改成加分</b>——
            {biasMedians.length === 3 && biasMedians.every(v => v < 0)
              ? '因為每一組的中位數都還是負的（高乖離只是「比較不負」），'
              : '因為差距量不出來，'}
            結論是：<b>乖離大不是買進理由，但也不該當成扣分理由。</b>
          </span>
        </Term>
        <Term word="市況（紅／黃／綠）">
          用「多少比例的股票站上月線」＋「全市場 20 日報酬中位數」判斷。
          綠＝多頭、黃＝盤整、紅＝空頭。有些訊號只在多頭有效，市況分層表可以看出來。
        </Term>
      </Section>

      <Section id="s5" title="自己篩股：條件怎麼選">
        <p>
          點<b>「篩選條件」</b>展開後，快速套用按鈕上的數字就是該策略的<b>成本後超額</b>——
          正數才代表扣完成本還贏過大盤。旁邊的記號要看：
        </p>
        <ul className="help-marks">
          <li><AlertTriangle size={14} strokeWidth={2} className="inline-warn-icon" />＝<b>樣本外驗證判定「過擬合」或效力大幅縮水</b>（在沒訓練過的日子撐不住）。</li>
          <li><b>?</b>＝樣本外<b>無法判斷</b>：可能是樣本太少，也可能是「從來沒有任何一段訓練期看好過它」（例：糾結轉強）。</li>
          <li><b>沒有記號</b>＝通過樣本外驗證。</li>
        </ul>
        <p className="help-note">
          <AlertTriangle size={16} strokeWidth={2} className="inline-warn-icon" /><b>這兩個記號只看「樣本外驗證」，不看成本。</b>所以會出現「沒有記號、但數字是負的」的情況
          {robustNeg
            ? <>——例如「{robustNeg.label}」樣本外判定是「穩健」（沒記號），可是成本後超額 {pp2(robustNeg.net_excess)}，扣完成本還是輸大盤。</>
            : '。'}
          <b>要判斷賺不賺，看數字本身的正負；記號只告訴你這個數字可不可信。</b>
        </p>
        <p>
          目前只有少數幾個訊號扣完成本後還是正的，多數訊號扣完成本是負的（輸給大盤）。
          具體是哪幾個、各是多少，看上面表格的最新數字（每週重算，這裡不寫死）——
          負的條件仍然保留讓你自己研究，但畫面上會誠實標出來。
        </p>
        <p className="help-note">
          「相對強弱／產業輪動」那組條件是 2026-07-25 才能用的（以前只能看戰績、不能篩），
          因為後端現在每天會算好每檔股票在全市場的排名。
        </p>
      </Section>

      <Section id="s6" title="組合排行榜怎麼看">
        <p>
          「A＋B 同時成立」的歷史戰績。<b>不要只看最上面那幾名</b>——排行榜按平均超額排序，
          而樣本少的組合天生容易衝到前面（丟 6 次硬幣有 5 次正面不代表硬幣有問題）。
        </p>
        <p>正確的看法是三欄一起看：</p>
        <ul className="help-marks">
          <li><b>樣本</b>與<b>天數</b>——樣本 20 筆、集中在 20 天內的，參考價值低。
            {cmb?.pass > 0 && okNum(cmb.medSamples) && okNum(cmb.medDays) && <>過關的組合樣本中位數是 {cmb.medSamples} 筆、跨 {cmb.medDays} 個交易日。</>}</li>
          <li><b>穩健下界</b>——保守估計值。平均高但下界低甚至負的，多半是小樣本巧合。</li>
          <li><b>禁得起挑選</b>——打勾的才是通過統計檢定的。可以用上方的「只看禁得起挑選的」開關過濾。</li>
        </ul>
        {cmb && (
          <p>
            {cmb.top
              ? <>目前通過檢定的第一名是<b>「{(cmb.top.labels || []).join('＋')}」，成本後 {pp2(cmb.top.avg_excess)}</b>，
                樣本 {cmb.top.samples} 筆、跨 {cmb.top.n_days} 個交易日（{combos?.date || '—'} 重算）。</>
              : <>目前（{combos?.date || '—'} 重算）<b>沒有任何組合通過檢定</b>——排行榜上看起來強的，都還不能排除是運氣。</>}
          </p>
        )}
      </Section>

      <Section id="s7" title="這個系統的已知限制">
        <p>不寫這段的說明書不能信，所以照實列：</p>
        <ul className="help-limits">
          <li>
            <b>回測歷史不長</b>{okNum(regimeDays) && regimeDays > 0 ? `（約 ${regimeDays} 個交易日）` : ''}。沒經歷過完整的大牛市或金融危機，
            所以「空頭也有效」這種結論的信心有限。
          </li>
          <li>
            {okNum(oosDays) && oosDays >= 180
              ? <><b>樣本外驗證已累積 {oosDays} 個決策日</b>，達到專案自己訂的 180 天標準；「強勢雙確認」當入場門檻原本是<b>提前放行</b>的，現在才算補足這一條。</>
              : <><b>樣本外驗證的時間長度還不夠</b>。{okNum(oosDays) ? `目前累積 ${oosDays} 個決策日，` : ''}專案自己訂的標準是 180 天以上。
                也就是說「強勢雙確認」當入場門檻這件事，嚴格說是<b>提前放行</b>的（證據是它在所有指標上都最強，
                但還沒滿足最嚴格的門檻）。</>}
          </li>
          <li>
            <b>籌碼面訊號沒有戰績</b>（外資連買、投信連買、千張大戶）。因為只存了 20 天的籌碼歷史，
            回測期間沒有資料 → 樣本 0。它們可以拿來篩股，但<b>沒有回測數字支撐</b>。
          </li>
          <li>
            <b>進場價用「訊號隔天開盤」計算</b>，跟你實際最快能買到的時間一致；但盤中追高、或隔幾天才買，結果就會跟回測不同。
          </li>
          <li>
            <b>戰績不含停損停利</b>。所有戰績都是「買進後固定持有 20 個交易日」；
            各條停損線的歷史代價另外列在第 1 章的「防守價與停損的代價」，兩者不要混著讀。
            {okNum(h20) && okNum(h40) && (h40 > h20
              ? <>出場分析顯示持有 40 天成本後平均超額 {pp2(h40)}，比 20 天的 {pp2(h20)} 好{h40 < 0 ? '（但兩者都還是負的）' : ''}，而且那還沒經過樣本外驗證。</>
              : <>出場分析目前看不出持有更久比較好（20 天 {pp2(h20)}、40 天 {pp2(h40)}）。</>)}
          </li>
          <li>
            <b>這是研究工具，不是投資建議。</b>所有數字都是歷史統計，未來不保證重現。
          </li>
        </ul>
      </Section>

      <footer className="help-foot">
        <button className="help-back" onClick={onBack}>
          <ArrowLeft size={16} strokeWidth={2} />回選股頁
        </button>
        <p>資料來源：TWSE／TPEX 官方公開資料 · 僅供研究參考，非投資建議</p>
      </footer>
    </div>
  )
}
