#!/usr/bin/env python3
"""
客服业务逻辑层（进程内运行时）。

不使用 LangGraph Platform 的 REST API：本模块在应用进程内持有**一个已编译的
LangGraph 图**，通过 `graph.ainvoke` 直接执行，无需 langgraph_sdk、/threads、
/runs、/state 等服务端端点，也没有 run 轮询。

持久化由 `AsyncSqliteSaver` 负责，checkpoint 落盘到 `data/checkpoints.db`：
多轮对话状态（含 `persisted_dialogue`）按 thread_id 隔离并跨进程可续聊。

**会话隔离约定**：thread_id 由调用方传入，作为 LangGraph config 的
`configurable.thread_id`；本模块只持有「图 / checkpointer」这类应用级基础设施，
不保存任何"当前线程"的请求级状态，因此多用户并发互不干扰。
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional, Tuple

import aiosqlite
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

#: checkpoint 落盘位置（可用 CHECKPOINT_DB_PATH 覆盖）
CHECKPOINT_DB_PATH: Path = Path(
    os.getenv("CHECKPOINT_DB_PATH") or (BASE_DIR / "data" / "checkpoints.db")
)


@dataclass
class ChatOutcome:
    """一次对话运行的结果。用结构体替代多返回值元组，避免调用方错位取值。"""

    text: Optional[str] = None
    error: Optional[str] = None
    http_status: int = 200
    thread_id: Optional[str] = None
    agent: Optional[str] = None
    query_type: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


# -----------------------------------------------------------------------------
# 应用级运行时（图 + checkpointer 单例，非请求级状态）
# -----------------------------------------------------------------------------

_conn: Optional[aiosqlite.Connection] = None
_saver: Optional[AsyncSqliteSaver] = None
_graph: Any = None


async def startup() -> None:
    """应用启动：打开 SQLite、建表、构建带 checkpointer 的图。"""
    global _conn, _saver, _graph

    # 延迟导入：避免 webapp 导入期就拉起 LangChain/LangGraph 依赖
    from workflow.graph import make_graph

    CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _conn = await aiosqlite.connect(str(CHECKPOINT_DB_PATH))
    _saver = AsyncSqliteSaver(_conn)
    await _saver.setup()
    _graph = make_graph(_saver)
    logger.info("运行时就绪：checkpoint → %s", CHECKPOINT_DB_PATH)


async def shutdown() -> None:
    """应用关闭：释放 SQLite 连接。"""
    global _conn, _saver, _graph
    if _conn is not None:
        await _conn.close()
    _conn = _saver = _graph = None


def is_ready() -> bool:
    return _graph is not None


def new_thread_id() -> str:
    """生成一个新的会话（线程）ID。"""
    return str(uuid.uuid4())


def _require_graph() -> Any:
    if _graph is None:
        raise RuntimeError("图尚未初始化：应用 startup 未完成")
    return _graph


# -----------------------------------------------------------------------------
# 状态解析
# -----------------------------------------------------------------------------


def extract_ai_response(state: Dict[str, Any]) -> str:
    """从图返回的最终状态中提取 AI 回复文本。"""
    if isinstance(state, dict) and state.get("response"):
        return str(state["response"])
    return "抱歉，我无法理解您的问题。"


def extract_response_meta(state: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """提取处理专家与查询类型（供前端展示徽章）。"""
    values = state if isinstance(state, dict) else {}
    return {"agent": values.get("current_agent"), "query_type": values.get("query_type")}


# -----------------------------------------------------------------------------
# 对话运行
# -----------------------------------------------------------------------------


async def run_chat(user_message: str, thread_id: Optional[str] = None) -> ChatOutcome:
    """
    执行一轮对话。

    thread_id 为空时自动生成一个；调用方应把它持久化并在后续请求中回传，
    这样才能在同一线程上续聊（否则每轮都是全新会话）。
    """
    message = (user_message or "").strip()
    if not message:
        return ChatOutcome(error="消息不能为空", http_status=400)

    tid = (thread_id or "").strip()
    # 'default' 是前端"尚未建立会话"的哨兵值，不能当作真实线程 ID，
    # 否则所有未携带 session_id 的请求会共用同一条线程。
    if not tid or tid == "default":
        tid = new_thread_id()

    try:
        graph = _require_graph()
        state = await graph.ainvoke(
            {"customer_query": message, "session_id": tid},
            config={"configurable": {"thread_id": tid}},
        )
    except Exception as e:
        logger.exception("对话执行失败")
        return ChatOutcome(error=f"内部错误: {e}", http_status=500, thread_id=tid)

    return ChatOutcome(
        text=extract_ai_response(state),
        thread_id=tid,
        agent=state.get("current_agent") if isinstance(state, dict) else None,
        query_type=state.get("query_type") if isinstance(state, dict) else None,
    )


async def stream_chat_events(
    user_message: str, thread_id: Optional[str] = None
) -> AsyncIterator[str]:
    """
    生成 SSE data 行（含末尾 [DONE]）。

    ⚠️ 当前为「运行完成后一次性写出」，不是 token / 节点级流式。
    如需逐节点推送，把 run_chat 换成 `graph.astream(input, config, stream_mode="updates")`
    并在循环里 yield 每个节点事件即可。
    """
    outcome = await run_chat(user_message, thread_id)
    if outcome.ok:
        yield _sse({
            "content": outcome.text,
            "session_id": outcome.thread_id,
            "thread_id": outcome.thread_id,
            "agent": outcome.agent,
            "query_type": outcome.query_type,
        })
    else:
        yield _sse({"error": outcome.error})
    yield "data: [DONE]\n\n"


def _sse(payload: Dict[str, Any]) -> str:
    import json

    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# -----------------------------------------------------------------------------
# 会话管理
# -----------------------------------------------------------------------------


async def delete_conversation(thread_id: str) -> Tuple[bool, Optional[str]]:
    """删除一个会话的全部 checkpoint（图状态）。成功返回 (True, None)。"""
    tid = (thread_id or "").strip()
    if not tid:
        return False, "会话 ID 不能为空"
    if _saver is None:
        return False, "服务未就绪"

    try:
        await _saver.adelete_thread(tid)
    except Exception as e:
        logger.exception("删除会话失败")
        return False, f"删除会话失败: {e}"
    return True, None


async def persisted_thread_count() -> int:
    """已持久化的会话数（诊断用）。"""
    if _conn is None:
        return 0
    try:
        async with _conn.execute("SELECT COUNT(DISTINCT thread_id) FROM checkpoints") as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.warning("统计会话数失败: %s", e)
        return 0


async def graph_info() -> Dict[str, Any]:
    """图与持久化的自检信息（供 /api/test 展示）。"""
    if _graph is None:
        return {"status": "not_ready", "checkpointer": None, "checkpoint_db": str(CHECKPOINT_DB_PATH)}

    inner = _graph.get_graph()
    nodes = inner.nodes
    node_ids = sorted(nodes.keys()) if isinstance(nodes, dict) else sorted(
        n if isinstance(n, str) else getattr(n, "id", str(n)) for n in nodes
    )

    return {
        "status": "ready",
        "checkpointer": type(_saver).__name__,
        "checkpoint_db": str(CHECKPOINT_DB_PATH),
        "nodes": node_ids,
        "node_count": len(node_ids),
        "persisted_threads": await persisted_thread_count(),
    }
