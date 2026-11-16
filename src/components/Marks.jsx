import { AlertTriangle, Check, X } from 'lucide-react'

// 狀態記號（2026-11-16 專業看盤小修）：⚠ ✓ ✗ 這類文字符號在 iOS 可能被畫成彩色 emoji，
// 顏色不受 token 控制。改畫 lucide 圖示（顏色走 currentColor＝CSS token），
// 原本的符號放進 sr-only，螢幕報讀念到的跟改之前一模一樣，畫面上不多任何字。
function Mark({ Icon, text, className = '' }) {
  return (
    <span className={`mark-ico ${className}`.trim()}>
      <Icon size={14} strokeWidth={2.25} aria-hidden="true" focusable="false" />
      <span className="sr-only">{text}</span>
    </span>
  )
}

export const WarnMark = props => <Mark Icon={AlertTriangle} text="⚠" {...props} />
export const CheckMark = props => <Mark Icon={Check} text="✓" {...props} />
export const CrossMark = props => <Mark Icon={X} text="✗" {...props} />

// TIER_MARK（lib/oos.js）的上標：⚠ 畫成圖示，? 是一般 ASCII 問號、不會變 emoji，照舊輸出文字。
export function TierMark({ tm }) {
  if (!tm) return null
  return <sup className={tm.cls}>{tm.mark === '⚠' ? <WarnMark /> : tm.mark}</sup>
}
