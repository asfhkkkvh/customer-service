/**
 * 展示层工具：时间格式化 + 助手回复的 Markdown 安全渲染。
 * 全部从旧版 templates/index.html 平移，行为保持一致。
 */

import { marked } from 'marked'
import DOMPurify from 'dompurify'

function pad2(n) {
  return String(n).padStart(2, '0')
}

function formatWallClockDate(d) {
  return (
    d.getFullYear()
    + '-'
    + pad2(d.getMonth() + 1)
    + '-'
    + pad2(d.getDate())
    + ' '
    + pad2(d.getHours())
    + ':'
    + pad2(d.getMinutes())
    + ':'
    + pad2(d.getSeconds())
  )
}

/** 侧边栏会话「创建」时间：本地日历，YYYY-MM-DD HH:mm:ss（24 小时） */
export function formatSessionCreatedAt(tsUnix) {
  let sec = (tsUnix !== undefined && tsUnix !== null && tsUnix !== '')
    ? Number(tsUnix)
    : (Date.now() / 1000)
  if (isNaN(sec) || sec <= 0) {
    sec = Date.now() / 1000
  }
  return formatWallClockDate(new Date(sec * 1000))
}

/** 仅当后端/状态里存有非空 timestamp 时才展示时间 */
function hasMessageTimestamp(tsRaw) {
  if (tsRaw === undefined || tsRaw === null) return false
  if (typeof tsRaw === 'string') return tsRaw.trim() !== ''
  if (typeof tsRaw === 'number') return !isNaN(tsRaw)
  return false
}

/** 将后端时间渲染为可读串；无有效值时返回空（不调用当前时间兜底） */
export function formatMessageWallClock(tsRaw) {
  if (!hasMessageTimestamp(tsRaw)) return ''
  if (typeof tsRaw === 'string') {
    const ss = tsRaw.trim()
    if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$/.test(ss)) return ss.replace('T', ' ')
    const ds = new Date(ss.includes('T') ? ss : ss.replace(' ', 'T'))
    if (!isNaN(ds.getTime())) return formatWallClockDate(ds)
    return ''
  }
  const ms = tsRaw < 1e12 ? tsRaw * 1000 : tsRaw
  const da = new Date(ms)
  if (isNaN(da.getTime())) return ''
  return formatWallClockDate(da)
}

/** <time> 的机器可读属性；无效返回空串（调用方不设置 dateTime） */
export function messageTimeDatetimeAttr(tsRaw) {
  if (!hasMessageTimestamp(tsRaw)) return ''
  if (typeof tsRaw === 'string' && /\d{4}-\d{2}-\d{2}[ T]\d{2}:/.test(tsRaw)) {
    const s = tsRaw.trim().replace(' ', 'T')
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(s)) return s + ':00'
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(s)) return s
    return ''
  }
  if (typeof tsRaw === 'number') {
    const ms2 = tsRaw < 1e12 ? tsRaw * 1000 : tsRaw
    const dn = new Date(ms2)
    if (!isNaN(dn.getTime())) return dn.toISOString()
    return ''
  }
  return ''
}

/**
 * 助手回复渲染为安全 HTML（GFM + DOMPurify 消毒）。
 * 解析异常时返回 null，调用方回退为纯文本展示（React 自动转义，无注入风险）。
 */
export function renderAssistantHtml(text) {
  const src = text === undefined || text === null ? '' : String(text)
  try {
    const dirty = marked.parse(src, { breaks: false, gfm: true })
    return DOMPurify.sanitize(dirty)
  } catch (e) {
    console.warn('[markdown] 解析失败，回退为原始展示:', e)
    return null
  }
}

/** 复制纯文本；非安全上下文（http 局域网）回退 execCommand */
export function copyPlainText(text) {
  const t = text == null ? '' : String(text)
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(t)
  }
  return new Promise((resolve, reject) => {
    try {
      const ta = document.createElement('textarea')
      ta.value = t
      ta.setAttribute('readonly', '')
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      resolve()
    } catch (err) {
      reject(err)
    }
  })
}
