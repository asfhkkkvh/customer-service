/**
 * 会话存储：对话列表与消息历史全部保存在浏览器 localStorage。
 *
 * 后端只持久化图状态（checkpoint，用于多轮上下文与续聊），不提供"列出会话"的接口；
 * 因此侧栏列表、标题、历史回显都由此模块负责。
 *
 * 会话结构：
 *   { id, title, messages: [{role, content, agent?, queryType?, timestamp}], createdAt, updatedAt }
 * 时间统一为 Unix 秒，便于复用展示层的时间格式化。
 */

const STORAGE_KEY = 'cs_conversations'

/** 生成会话 ID。非安全上下文（局域网 http）没有 randomUUID，做降级。 */
export function newConversationId() {
  if (typeof window !== 'undefined' && window.crypto && typeof window.crypto.randomUUID === 'function') {
    return window.crypto.randomUUID()
  }
  return 'c-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10)
}

function nowSec() {
  return Math.floor(Date.now() / 1000)
}

/** 用首条用户消息生成侧栏标题 */
export function buildTitle(text) {
  const t = String(text || '').trim().replace(/\s+/g, ' ')
  if (!t) return '新对话'
  return t.length > 20 ? t.slice(0, 20) + '…' : t
}

export function createConversation() {
  const ts = nowSec()
  return { id: newConversationId(), title: '新对话', messages: [], createdAt: ts, updatedAt: ts }
}

function normalize(raw) {
  const ts = nowSec()
  return {
    id: typeof raw.id === 'string' && raw.id ? raw.id : newConversationId(),
    title: typeof raw.title === 'string' && raw.title ? raw.title : '新对话',
    messages: Array.isArray(raw.messages) ? raw.messages : [],
    createdAt: typeof raw.createdAt === 'number' ? raw.createdAt : ts,
    updatedAt: typeof raw.updatedAt === 'number' ? raw.updatedAt : ts,
  }
}

/** 读取全部会话（按最近更新降序）。解析失败返回空数组，不阻断应用启动。 */
export function loadConversations() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '[]')
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((c) => c && typeof c === 'object')
      .map(normalize)
      .sort((a, b) => b.updatedAt - a.updatedAt)
  } catch (e) {
    console.warn('[conversations] 本地会话解析失败，已忽略:', e)
    return []
  }
}

/** 写回全部会话。localStorage 满/被禁用时只告警，不影响当前会话使用。 */
export function saveConversations(conversations) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations))
  } catch (e) {
    console.warn('[conversations] 本地会话写入失败:', e)
  }
}

/** 启动时取初始会话列表：没有历史就开一条新的 */
export function initialConversations() {
  const loaded = loadConversations()
  return loaded.length ? loaded : [createConversation()]
}
