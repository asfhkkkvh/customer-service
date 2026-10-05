import { useEffect, useRef, useState } from 'react'
import Message from './Message.jsx'

const SUGGESTED_PROMPTS = [
  '有哪些产品推荐？',
  '产品价格区间和优惠活动说明',
  '如何查询账单与发票？',
  '退款流程需要多久到账？',
  '遇到登录或报错如何进行技术支持？',
  '退换货政策和物流时效是怎样的？',
  '我要投诉服务人员，需要提供哪些信息？',
  '门店营业时间与联系方式',
  '会员积分如何获取与兑换？',
  '电子发票什么时候能开好，在哪儿下载？',
]

/**
 * 聊天主区：消息列表 + 空状态欢迎层 + 输入 Dock。
 */
export default function ChatArea({ messages, isTyping, canSend, onSend }) {
  const [draft, setDraft] = useState('')
  const inputRef = useRef(null)
  const scrollRef = useRef(null)

  const canSubmit = draft.trim().length > 0 && canSend

  // textarea 自适应高度（上限 120px，与旧版一致）
  useEffect(() => {
    const ta = inputRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px'
  }, [draft])

  // 新消息 / typing 时滚动到底部
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, isTyping])

  const submit = () => {
    const message = draft.trim()
    if (!message || !canSend) return
    setDraft('')
    onSend(message)
  }

  const handleKeyDown = (e) => {
    // Enter 发送；Shift+Enter 换行
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  /** 首页「常见问题」药丸：点击填入输入框 */
  const fillPrompt = (prompt) => {
    if (isTyping) return
    setDraft(prompt)
    if (inputRef.current) inputRef.current.focus()
  }

  return (
    <div className="chat-area">
      <div className="chat-workspace">
        <div className="chat-main-column">
          <div className="chat-container" ref={scrollRef}>
            {messages.map((message, index) => (
              <Message key={index} message={message} />
            ))}
          </div>

          {messages.length === 0 && (
            <div className="chat-empty-state" aria-hidden="false">
              <div className="chat-empty-inner">
                <h2 className="chat-empty-title">您好，我是智能客服助手</h2>
                <div className="chat-suggest-list" role="group" aria-label="常见问题推荐">
                  {SUGGESTED_PROMPTS.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      className="chat-suggest-pill"
                      onClick={() => fillPrompt(prompt)}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="chat-floating-dock">
            <div className="floating-composer-stack">
              {isTyping && (
                <div className="typing-indicator" style={{ display: 'block' }}>
                  <span className="typing-dots">智能体正在思考中</span>
                </div>
              )}
              <div className="input-container">
                <div className="input-inner">
                  <div className="input-composer">
                    <textarea
                      ref={inputRef}
                      className="input-composer-field"
                      rows="1"
                      placeholder="请输入您的问题..."
                      maxLength={500}
                      autoComplete="off"
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={handleKeyDown}
                    />
                    <div className="input-composer-toolbar">
                      <div className="input-composer-hint">Enter 发送 · Shift+Enter 换行</div>
                      <button
                        type="button"
                        className={'input-send-circle' + (canSubmit ? ' input-send-ready' : '')}
                        onClick={submit}
                        title="发送"
                        aria-label="发送"
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
                          stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"
                          strokeLinejoin="round" aria-hidden="true">
                          {/* 竖线箭杆 + 向上三角箭首（常见「上传/发送」语义） */}
                          <path d="M12 19.5V10" />
                          <path d="M7.5 14.5L12 10l4.5 4.5" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <p className="chat-ai-disclaimer" role="note">内容由AI生成，可能不准确，请注意核实</p>
          </div>
        </div>
      </div>
    </div>
  )
}
