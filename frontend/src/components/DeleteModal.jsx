import { useEffect, useRef } from 'react'

/**
 * 会话删除二次确认弹窗。确认动作交给上层执行。
 */
export default function DeleteModal({ onCancel, onConfirm }) {
  const cancelRef = useRef(null)

  useEffect(() => {
    if (cancelRef.current) cancelRef.current.focus()
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onCancel()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onCancel])

  return (
    <div className="session-delete-modal" role="dialog" aria-modal="true" aria-labelledby="sessionDeleteModalTitle">
      <div className="session-delete-modal__backdrop" onClick={onCancel} />
      <div className="session-delete-modal__panel">
        <h2 id="sessionDeleteModalTitle" className="session-delete-modal__title">删除会话</h2>
        <p className="session-delete-modal__body">删除后，这条对话记录将无法找回。确定删除此对话？</p>
        <div className="session-delete-modal__actions">
          <button ref={cancelRef} type="button" className="session-delete-modal__btn" onClick={onCancel}>
            取消
          </button>
          <button
            type="button"
            className="session-delete-modal__btn session-delete-modal__btn--danger"
            onClick={onConfirm}
          >
            删除
          </button>
        </div>
      </div>
    </div>
  )
}
