import { useEffect, useRef, useState } from 'react'
import { formatSessionCreatedAt } from '../utils.js'

/**
 * 会话侧栏：操作按钮 + 最近对话列表。
 */
export default function Sidebar({
  sessions,
  currentSessionId,
  onCreateNew,
  onRefresh,
  onLoadSession,
  onRequestDelete,
  onApiTest,
}) {
  return (
    <div className="sidebar">
      <div className="session-controls">
        <button type="button" className="session-btn session-btn-accent-new" title="新建对话" onClick={onCreateNew}>
          <svg className="btn-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 8v8M8 12h8" />
          </svg>
          <span>新建对话</span>
        </button>
        <button type="button" className="session-btn session-btn-accent-sync" title="刷新列表" onClick={onRefresh}>
          <svg className="btn-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8M3 3v5h5M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16m0 5v-5h-5" />
          </svg>
          <span>刷新列表</span>
        </button>
        <button type="button" className="session-btn session-btn-accent-api" title="API测试" onClick={onApiTest}>
          <svg className="btn-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M16 18l6-6-6-6M8 6l-6 6 6 6M14 4l-4 16" />
          </svg>
          <span>API测试</span>
        </button>
      </div>
      <div className="sidebar-title">最近对话</div>
      <div className="session-list">
        {sessions.length === 0 ? (
          <div className="session-list-empty">暂无会话数据</div>
        ) : (
          sessions.map((session) => (
            <SessionItem
              key={session.session_id}
              session={session}
              active={session.session_id === currentSessionId}
              onLoad={onLoadSession}
              onRequestDelete={onRequestDelete}
            />
          ))
        )}
      </div>
    </div>
  )
}

function SessionItem({ session, active, onLoad, onRequestDelete }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const rootRef = useRef(null)

  // 菜单打开时：点击组件外部或按 Escape 关闭
  useEffect(() => {
    if (!menuOpen) return
    const onDocClick = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setMenuOpen(false)
    }
    const onKey = (e) => {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('click', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('click', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  const previewRaw = typeof session.last_user_question === 'string'
    ? session.last_user_question.trim()
    : ''
  const titleText = previewRaw || '新对话'

  return (
    <div
      ref={rootRef}
      className={
        'session-item'
        + (active ? ' active' : '')
        + (menuOpen ? ' session-item--menu-open' : '')
      }
    >
      <div className="session-item-main" onClick={() => onLoad(session.session_id)}>
        <div className="session-item-preview" title={previewRaw || undefined}>{titleText}</div>
        <div className="session-item-meta">
          消息: {session.message_count || 0} | 创建: {formatSessionCreatedAt(session.created_at)}
        </div>
      </div>
      <div className="session-item-actions">
        <button
          type="button"
          className="session-item-more-btn"
          aria-label="更多操作"
          aria-expanded={menuOpen}
          aria-haspopup="true"
          title="更多"
          onClick={(e) => {
            e.stopPropagation()
            setMenuOpen((v) => !v)
          }}
        >
          ...
        </button>
        {menuOpen && (
          <div className="session-item-menu session-item-menu--open">
            <ul className="session-item-menu-list" role="menu">
              <li role="none">
                <button
                  type="button"
                  className="session-item-menu-delete"
                  role="menuitem"
                  aria-label="删除此对话"
                  onClick={(e) => {
                    e.stopPropagation()
                    setMenuOpen(false)
                    onRequestDelete({ sessionId: session.session_id, previewTitle: titleText })
                  }}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    <line x1="10" y1="11" x2="10" y2="17" />
                    <line x1="14" y1="11" x2="14" y2="17" />
                  </svg>
                  <span>删除此对话</span>
                </button>
              </li>
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
