import { Component } from 'react'
import { AlertTriangle } from 'lucide-react'

// 錯誤邊界：React 沒有 error boundary 時，**任何**元件在渲染中丟錯就會卸載整棵樹 →
// 使用者看到的是一片只有底色的空白頁，完全無從得知發生什麼事、也救不回來。
//
// 2026-07-25 就踩到：K 線圖的雙重釋放丟出 `Object is disposed`，整站白畫面，
// 而 Andy 只能看到「有些個股點了會變白」——一個區塊的 bug 毀掉整個站。
//
// 有了邊界之後：壞掉的那一塊顯示可重試的錯誤卡，其餘功能照常。
// ⚠️ 這是**防護網不是修法**——邊界擋住的錯誤仍然是 bug，要照 console 的訊息去修根因。
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { err: null }
  }

  static getDerivedStateFromError(err) {
    return { err }
  }

  componentDidCatch(err, info) {
    // 留在 console 供除錯（線上沒有錯誤收集服務，這是唯一線索來源）
    console.error(`[ErrorBoundary:${this.props.name || '?'}]`, err, info?.componentStack)
  }

  render() {
    if (!this.state.err) return this.props.children
    return (
      <div className="eb-fallback" role="alert">
        <AlertTriangle size={16} strokeWidth={2} />
        <div>
          <b>{this.props.label || '這個區塊'}載入時出錯了</b>
          <p>其他功能仍可正常使用。錯誤訊息：{String(this.state.err?.message || this.state.err)}</p>
          <button onClick={() => this.setState({ err: null })}>重試這個區塊</button>
        </div>
      </div>
    )
  }
}
