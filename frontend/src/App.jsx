import { useCallback, useEffect, useState } from 'react'
import Sidebar from './components/Sidebar.jsx'
import ChatArea from './components/ChatArea.jsx'
import DeleteModal from './components/DeleteModal.jsx'
import {
  deleteSession,
  fetchSessionDetail,
  fetchSessions,
  sendChat,
  testLangGraphApi,
} from './api.js'

/**
 * 顶层状态与布局。
 *
 * 会话 ID 约定（与旧版一致）：
 * - 'default' 是哨兵值：新对话不预先向服务端建线程，首条消息发出时由后端
 *   真实创建 LangGraph 线程，并把返回的 thread_id 回写，之后才能续聊。
 *   好处：反复刷新页面不会在服务端堆积空会话。
 * - 仅存内存：刷新页面回到全新对话（与旧版行为一致）。
 */
export default function App() {
  const [currentSessionId, setCurrentSessionId] = useState('default')
  const [messages, setMessages] = useState([])
  const [isTyping, setIsTyping] = useState(false)
  const [sessions, setSessions] = useState([])
  /** 删除确认弹窗载荷：{ sessionId, previewTitle } */
  const [pendingDelete, setPendingDelete] = useState(null)

  const pushMessage = useCallback((message) => {
    setMessages((prev) => [...prev, message])
  }, [])

  const refreshSessions = useCallback(async () => {
    try {
      const data = await fetchSessions()
      setSessions(data.sessions || [])
    } catch (error) {
      console.error('获取会话列表失败:', error)
      setSessions([])
    }
  }, [])

  useEffect(() => {
    refreshSessions()
  }, [refreshSessions])

  /** 新对话：清空消息区，回到哨兵会话（不向服务端建线程） */
  const handleCreateNew = () => {
    setCurrentSessionId('default')
    setMessages([])
    refreshSessions()
  }

  /** 切换到历史会话并渲染其对话 */
  const handleLoadSession = async (sessionId) => {
    setCurrentSessionId(sessionId)
    try {
      const data = await fetchSessionDetail(sessionId)
      if (!data.session) {
        pushMessage({ role: 'system', content: '会话数据格式错误' })
        return
      }
      setMessages(
        (data.session.conversation_history || []).map((msg) => ({
          role: msg.is_user ? 'user' : 'assistant',
          content: msg.content,
          timestamp: msg.timestamp,
        })),
      )
      refreshSessions()
    } catch (error) {
      console.error('加载会话失败:', error)
      pushMessage({ role: 'system', content: '加载会话失败: ' + error.message })
    }
  }

  /** 发送一轮消息：乐观渲染用户气泡 → 阻塞等待 → 回写真实 thread_id */
  const handleSend = async (message) => {
    if (!message || isTyping || !currentSessionId) return
    pushMessage({ role: 'user', content: message })
    setIsTyping(true)
    try {
      const data = await sendChat(message, currentSessionId)
      // 服务端返回的是真实 LangGraph 线程 ID，必须回写。
      // 不回写会让后续每个请求都带着无效 ID，导致无法续聊。
      if (data.thread_id) {
        setCurrentSessionId(data.thread_id)
      }
      if (data.response) {
        pushMessage({
          role: 'assistant',
          content: data.response,
          agent: data.agent,
          queryType: data.query_type,
        })
      } else {
        pushMessage({ role: 'assistant', content: '抱歉，系统返回了空响应，请稍后重试。' })
      }
      refreshSessions()
    } catch (error) {
      console.error('发送消息失败:', error)
      pushMessage({ role: 'assistant', content: '抱歉，系统出现错误：' + error.message })
    } finally {
      setIsTyping(false)
    }
  }

  /** 侧栏「API测试」：连通性结果以系统消息形式落到对话区 */
  const handleApiTest = async () => {
    try {
      const data = await testLangGraphApi()
      const ok = (code) => typeof code === 'number' && code >= 200 && code < 300
      const parts = [
        (ok(data.health_check) ? '✅' : '❌') + ' 健康检查',
        (ok(data.threads_search) ? '✅' : '❌') + ' 线程搜索',
        (ok(data.assistants_search) ? '✅' : '❌') + ' 助手搜索',
      ]
      pushMessage({ role: 'system', content: '🧪 API 测试完成: ' + parts.join(' | ') })
    } catch (error) {
      pushMessage({ role: 'system', content: '❌ API 测试失败: ' + error.message })
    }
  }

  /** 删除确认后的执行 */
  const handleConfirmDelete = async () => {
    if (!pendingDelete) return
    const sid = pendingDelete.sessionId
    setPendingDelete(null)
    try {
      await deleteSession(sid)
      if (sid === currentSessionId) {
        handleCreateNew()
      } else {
        refreshSessions()
      }
    } catch (error) {
      pushMessage({ role: 'system', content: '删除会话失败: ' + error.message })
    }
  }

  return (
    <div className="container">
      <header className="app-header">
        <div className="app-header-brand">
          <div className="app-header-icon" aria-hidden="true">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor"
              strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
          </div>
          <div className="app-header-text">
            <h1>多智能体客服系统</h1>
            <p>基于 LangGraph API 的智能客服系统</p>
          </div>
        </div>
      </header>

      <div className="main-content">
        <Sidebar
          sessions={sessions}
          currentSessionId={currentSessionId}
          onCreateNew={handleCreateNew}
          onRefresh={refreshSessions}
          onLoadSession={handleLoadSession}
          onRequestDelete={setPendingDelete}
          onApiTest={handleApiTest}
        />
        <ChatArea
          messages={messages}
          isTyping={isTyping}
          canSend={!!currentSessionId && !isTyping}
          onSend={handleSend}
        />
      </div>

      {pendingDelete && (
        <DeleteModal
          previewTitle={pendingDelete.previewTitle}
          onCancel={() => setPendingDelete(null)}
          onConfirm={handleConfirmDelete}
        />
      )}
    </div>
  )
}
