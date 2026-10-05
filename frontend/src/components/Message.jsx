import { useRef, useState } from 'react'
import {
  copyPlainText,
  formatMessageWallClock,
  messageTimeDatetimeAttr,
  renderAssistantHtml,
} from '../utils.js'

/**
 * 单条消息气泡。
 * role: 'user' | 'assistant' | 'system'（system 复用助手形态，meta 标签为「系统消息」）
 * 实时回复可带 agent / queryType 徽章（历史消息无此信息，与旧版一致）。
 */
export default function Message({ message }) {
  const bodyRef = useRef(null)
  const [copyState, setCopyState] = useState('') // '' | 'ok' | 'fail'

  const isUser = message.role === 'user'
  const metaLabel = isUser ? '您' : message.role === 'system' ? '系统消息' : '智能客服'
  const timeLabel = formatMessageWallClock(message.timestamp)
  const datetimeAttr = messageTimeDatetimeAttr(message.timestamp)
  const copyTitle = copyState === 'ok' ? '已复制' : copyState === 'fail' ? '复制失败' : '复制'

  const handleCopy = (e) => {
    e.stopPropagation()
    // 取渲染后的纯文本（与旧版 innerText 行为一致）
    const text = bodyRef.current ? (bodyRef.current.innerText || '').trim() : ''
    if (!text) return
    copyPlainText(text)
      .then(() => setCopyState('ok'))
      .catch(() => setCopyState('fail'))
    setTimeout(() => setCopyState(''), 1600)
  }

  const meta = (
    <div className="message-meta">
      <span className="message-meta-role">{metaLabel}</span>
      {timeLabel && (
        <>
          <span className="message-meta-sep" aria-hidden="true">·</span>
          <time className="message-meta-time" dateTime={datetimeAttr || undefined}>{timeLabel}</time>
        </>
      )}
    </div>
  )

  const actions = (
    <div className="message-actions" role="toolbar" aria-label="复制消息">
      <button type="button" className="msg-action-btn" title={copyTitle} aria-label="复制全文" onClick={handleCopy}>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      </button>
    </div>
  )

  if (isUser) {
    // 用户消息：纯文本渲染（React 自动转义，杜绝旧版 innerHTML 注入隐患）
    return (
      <div className="message user">
        <div className="message-user-wrap">
          <div className="message-content">
            <div ref={bodyRef} className="message-body">{message.content ?? ''}</div>
          </div>
          {actions}
          {meta}
        </div>
      </div>
    )
  }

  const html = renderAssistantHtml(message.content)
  return (
    <div className="message assistant">
      <div className="message-content">
        {(message.agent || message.queryType) && (
          <div className="agent-info">
            🤖 {message.agent || '智能客服'} | 📋 {message.queryType || '已处理'}
          </div>
        )}
        {html !== null ? (
          <div
            ref={bodyRef}
            className="message-body md-body"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        ) : (
          <div ref={bodyRef} className="message-body">{String(message.content ?? '')}</div>
        )}
        {actions}
        {meta}
      </div>
    </div>
  )
}
