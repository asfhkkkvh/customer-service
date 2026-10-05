/**
 * 后端 API 封装。所有函数在非 2xx 时抛 Error（message 优先取后端 error 字段），
 * 调用方只需 try/catch 一处。
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

/** 会话列表。返回 { sessions: [...] } */
export function fetchSessions() {
  return requestJson('/api/sessions')
}

/** 单个会话详情（含对话历史）。返回 { session: {...} } */
export function fetchSessionDetail(sessionId) {
  return requestJson(`/api/sessions/${encodeURIComponent(sessionId)}`)
}

/** 删除会话 */
export function deleteSession(sessionId) {
  return requestJson(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
}

/** LangGraph 连通性测试。返回 { status, health_check, threads_search, assistants_search } */
export function testLangGraphApi() {
  return requestJson('/api/test')
}
