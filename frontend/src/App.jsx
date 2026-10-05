import { useCallback, useEffect, useState } from 'react'
import Sidebar from './components/Sidebar.jsx'
import ChatArea from './components/ChatArea.jsx'
import DeleteModal from './components/DeleteModal.jsx'
import { deleteConversation, sendChat, testRuntime } from './api.js'
import {
  buildTitle,
  createConversation,
  initialConversations,
  saveConversations,
} from './conversations.js'

/**
 * 顶层状态与布局。
 *
 * 架构：图在 FastAPI 进程内运行，服务端只用 checkpoint 保存图状态；
 * 会话列表与消息历史全部由前端 localStorage 维护（见 conversations.js）。
 * 会话 ID 由前端生成并作为 thread_id 传给后端，服务端按线程隔离状态。
 */
export default function App() {
  const [conversations, setConversations] = useState(initialConversations)
  const [currentId, setCurrentId] = useState(null)
  const [isTyping, setIsTyping] = useState(false)
  /** 删除确认弹窗载荷：{ id, title } */
  const [pendingDelete, setPendingDelete] = useState(null)

  // currentId 为空（首次进入 / 删除了当前会话）时回落到最近更新的会话
  const current = conversations.find((c) => c.id === currentId) || conversations[0] || null
  const messages = current ? current.messages : []

  useEffect(() => {
    saveConversations(conversations)
  }, [conversations])

  /** 更新指定会话并按最近更新排序（避免把更新逻辑散落到每个 handler） */
  const mutateConversation = useCallback((id, updater) => {
    setConversations((prev) => {
      const next = prev.map((c) => (c.id === id ? updater(c) : c))
      next.sort((a, b) => b.updatedAt - a.updatedAt)
      return next
    })
  }, [])

  /** 新建对话：已存在空会话时直接切过去，避免反复点击堆出多条"新对话" */
  const handleCreateNew = () => {
    const empty = conversations.find((c) => c.messages.length === 0)
    if (empty) {
      setCurrentId(empty.id)
      return
    }
    const conv = createConversation()
    setConversations((prev) => [conv, ...prev])
    setCurrentId(conv.id)
  }

  const handleSelect = (id) => setCurrentId(id)

  /** 发送一轮消息：本地乐观渲染 → 调用后端 → 落库助手回复 */
  const handleSend = async (text) => {
    if (!text || isTyping) return

    let conv = current
    if (!conv) {
      conv = createConversation()
      setConversations((prev) => [conv, ...prev])
      setCurrentId(conv.id)
    }
    const convId = conv.id

    const tsUser = Math.floor(Date.now() / 1000)
    mutateConversation(convId, (c) => ({
      ...c,
      title: c.messages.length === 0 ? buildTitle(text) : c.title,
      messages: [...c.messages, { role: 'user', content: text, timestamp: tsUser }],
      updatedAt: tsUser,
    }))

    setIsTyping(true)
    try {
      const data = await sendChat(text, convId)
      const realId = data.thread_id || convId
      const reply = data.response || '抱歉，系统返回了空响应，请稍后重试。'
      const tsAi = Math.floor(Date.now() / 1000)

      setConversations((prev) => {
        const next = prev.map((c) => (c.id === convId
          ? {
              ...c,
              // 服务端正常会沿用前端传入的 ID；若它另建了线程则同步过来
              id: realId,
              messages: [
                ...c.messages,
                {
                  role: 'assistant',
                  content: reply,
                  agent: data.agent,
                  queryType: data.query_type,
                  timestamp: tsAi,
                },
              ],
              updatedAt: tsAi,
            }
          : c))
        next.sort((a, b) => b.updatedAt - a.updatedAt)
        return next
      })
      if (realId !== convId) setCurrentId(realId)
    } catch (error) {
      console.error('发送消息失败:', error)
      const tsAi = Math.floor(Date.now() / 1000)
      mutateConversation(convId, (c) => ({
        ...c,
        messages: [
          ...c.messages,
          { role: 'assistant', content: '抱歉，系统出现错误：' + error.message, timestamp: tsAi },
        ],
        updatedAt: tsAi,
      }))
    } finally {
      setIsTyping(false)
    }
  }

  /** 侧栏「运行时自检」：结果以系统消息落到当前会话 */
  const handleSelfCheck = async () => {
    const cid = current ? current.id : null
    const pushSystem = (content) => {
      if (!cid) return
      const ts = Math.floor(Date.now() / 1000)
      mutateConversation(cid, (c) => ({
        ...c,
        messages: [...c.messages, { role: 'system', content, timestamp: ts }],
        updatedAt: ts,
      }))
    }
    try {
      const data = await testRuntime()
      pushSystem(
        `🧪 运行时自检：${data.status === 'ready' ? '✅ 就绪' : '❌ 未就绪'}`
        + ` | checkpointer=${data.checkpointer || '无'}`
        + ` | 图节点 ${data.node_count ?? '?'} 个`
        + ` | 已持久化会话 ${data.persisted_threads ?? 0} 条`,
      )
    } catch (error) {
      pushSystem('❌ 自检失败: ' + error.message)
    }
  }

  /** 删除确认后的执行：先删服务端 checkpoint，再移除本地记录 */
  const handleConfirmDelete = async () => {
    const target = pendingDelete
    setPendingDelete(null)
    if (!target) return

    try {
      await deleteConversation(target.id)
    } catch (error) {
      // 服务端删除失败不阻断本地清理，避免列表残留无法操作的条目
      console.warn('删除服务端会话失败（本地记录仍会移除）:', error)
    }

    setConversations((prev) => {
      const rest = prev.filter((c) => c.id !== target.id)
      return rest.length ? rest : [createConversation()]
    })
    if (currentId === target.id) setCurrentId(null)
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
            <p>基于 LangGraph 的多专家智能客服系统</p>
          </div>
        </div>
      </header>

      <div className="main-content">
        <Sidebar
          conversations={conversations}
          currentId={current ? current.id : null}
          onCreateNew={handleCreateNew}
          onSelect={handleSelect}
          onRequestDelete={setPendingDelete}
          onSelfCheck={handleSelfCheck}
        />
        <ChatArea
          messages={messages}
          isTyping={isTyping}
          canSend={!isTyping}
          onSend={handleSend}
        />
      </div>

      {pendingDelete && (
        <DeleteModal
          previewTitle={pendingDelete.title}
          onCancel={() => setPendingDelete(null)}
          onConfirm={handleConfirmDelete}
        />
      )}
    </div>
  )
}
