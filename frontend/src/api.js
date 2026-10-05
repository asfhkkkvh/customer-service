/**
 * 后端 API 封装。所有函数在非 2xx 时抛 Error（message 优先取后端 error 字段），
 * 调用方只需 try/catch 一处。
 *
 * 注意：图在服务端进程内运行，会话列表与历史存在前端 localStorage（见 conversations.js），
 * 因此这里没有"列出会话"的接口，只有发送与删除。
 */

async function requestJson(url, options) {
  const response = await fetch(url, options)
  let data = {}
  try {
    data = await response.json()
  } catch {
    // 非 JSON 响应体（如网关错误页）不阻断错误提示
  }
  if (!response.ok) {
    const detail = typeof data.error === 'string' && data.error
      ? data.error
      : `HTTP ${response.status}: ${response.statusText}`
    throw new Error(detail)
  }
  return data
}

/** 发送一轮对话。返回 { response, thread_id, agent, query_type } */
export function sendChat(message, sessionId) {
  return requestJson('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  })
}

/** 删除会话（清掉服务端 checkpoint） */
export function deleteConversation(threadId) {
  return requestJson(`/api/conversation/${encodeURIComponent(threadId)}`, { method: 'DELETE' })
}

/** 运行时自检：图节点、checkpointer、落盘位置、已持久化会话数 */
export function testRuntime() {
  return requestJson('/api/test')
}
