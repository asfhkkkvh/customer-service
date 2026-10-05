#!/usr/bin/env python3
"""
客服 Web 业务逻辑层：LangGraph REST 调用、线程/运行、状态解析、会话列表拼装。

与 Web 路由解耦，便于单测与复用。

**会话隔离约定**：本模块不保存任何"当前线程"的模块级状态。
线程 ID 由调用方传入、由本模块返回，全程作为局部变量与返回值传递，
因此多个请求（乃至多个用户）并发时互不干扰。
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# 配置（可被环境变量覆盖）
# -----------------------------------------------------------------------------

LANGGRAPH_API_URL: str = os.getenv("LANGGRAPH_API_URL", "http://127.0.0.1:2024").rstrip("/")
LANGGRAPH_GRAPH_NAME: str = os.getenv("LANGGRAPH_GRAPH_NAME", "customer_service")

#: 单轮对话最长等待时间（秒）
RUN_TIMEOUT_SECONDS = int(os.getenv("RUN_TIMEOUT_SECONDS", "120"))


def _url(path: str) -> str:
    return f"{LANGGRAPH_API_URL}{path}"


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
# 线程 state → 对话列表 / 侧栏预览
# -----------------------------------------------------------------------------


def append_turn_from_state(conversation_history: List[Dict[str, Any]], msg: Dict[str, Any]) -> None:
    """从状态中的单条消息追加到会话历史列表。"""
    content = msg.get("content", "") or ""
    if not content:
        return
    is_user = bool(msg.get("is_user", False))
    entry: Dict[str, Any] = {
        "is_user": is_user,
        "content": content,
        "role": "user" if is_user else "assistant",
    }
    ts = msg.get("timestamp")
    if ts is not None and ts != "":
        entry["timestamp"] = ts
    conversation_history.append(entry)


def conversation_history_from_state_data(state_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 LangGraph 线程 state JSON 解析对话列表。"""
    conversation_history: List[Dict[str, Any]] = []
    if not isinstance(state_data, dict):
        return conversation_history

    if "values" in state_data and isinstance(state_data["values"], dict):
        values = state_data["values"]

        source_turns = None
        filled_from_turn_list = False
        pd_raw = values.get("persisted_dialogue")
        ch_raw = values.get("conversation_history")
        if isinstance(pd_raw, list) and len(pd_raw) > 0:
            source_turns = pd_raw
        elif isinstance(ch_raw, list) and len(ch_raw) > 0:
            source_turns = ch_raw

        if source_turns is not None:
            filled_from_turn_list = True
            for msg in source_turns:
                if isinstance(msg, dict):
                    append_turn_from_state(conversation_history, msg)

        elif "messages" in values:
            for message in values["messages"]:
                role = message.get("role", "user")
                content = message.get("content", "")
                if content:
                    is_user = role == "user"
                    row: Dict[str, Any] = {
                        "is_user": is_user,
                        "content": content,
                        "role": role,
                    }
                    mt = message.get("timestamp")
                    if mt is not None and mt != "":
                        row["timestamp"] = mt
                    conversation_history.append(row)

        # 已有 persisted_dialogue / conversation_history 时不再追加 values.response：
        # 助手正文已在轮次里，重复追加会造成「两条回复」的观感。
        if "response" in values and values["response"]:
            response_content = values["response"]
            if not filled_from_turn_list:
                if not any(
                    msg["content"] == response_content and not msg["is_user"]
                    for msg in conversation_history
                ):
                    conversation_history.append({
                        "is_user": False,
                        "content": response_content,
                        "role": "assistant",
                    })

    elif "messages" in state_data:
        for message in state_data["messages"]:
            role = message.get("role", "user")
            content = message.get("content", "")
            if content:
                is_user = role == "user"
                row = {
                    "is_user": is_user,
                    "content": content,
                    "role": role,
                }
                mt = message.get("timestamp")
                if mt is not None and mt != "":
                    row["timestamp"] = mt
                conversation_history.append(row)

    return conversation_history


def last_user_question_from_history(conversation_history: List[Dict[str, Any]]) -> str:
    """取最后一条用户消息的纯文本（用于侧栏预览）。"""
    for msg in reversed(conversation_history):
        if not msg.get("is_user"):
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            content = str(content) if content is not None else ""
        s = content.strip()
        if s:
            return s
    return ""


def extract_ai_response(thread_state: Dict[str, Any]) -> str:
    """从线程状态中提取 AI 回复文本。"""
    try:
        if "values" in thread_state and isinstance(thread_state["values"], dict):
            values = thread_state["values"]

            if "response" in values and values["response"]:
                return str(values["response"])

            if "messages" in values:
                for message in values["messages"]:
                    if message.get("role") == "assistant":
                        content = message.get("content", "")
                        if content:
                            return str(content)

        return "抱歉，我无法理解您的问题。"

    except Exception as e:
        logger.error("提取 AI 回复时出错: %s", e)
        return "抱歉，处理您的请求时出现了错误。"


def extract_response_meta(thread_state: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """从线程状态中提取处理专家与查询类型（供前端展示徽章）。"""
    meta: Dict[str, Optional[str]] = {"agent": None, "query_type": None}
    if isinstance(thread_state, dict) and isinstance(thread_state.get("values"), dict):
        values = thread_state["values"]
        meta["agent"] = values.get("current_agent")
        meta["query_type"] = values.get("query_type")
    return meta


# -----------------------------------------------------------------------------
# 助手 / 线程
# -----------------------------------------------------------------------------

#: 助手 ID 是**不可变标识**，缓存它是安全的。
#: 注意与线程 ID 的区别：线程 ID 每个会话都不同，绝不能放进模块级缓存。
_assistant_id: Optional[str] = None


def ensure_assistant_exists() -> Tuple[Optional[str], Optional[str]]:
    """确保 LangGraph 助手存在。成功返回 (assistant_id, None)，失败返回 (None, error)。"""
    global _assistant_id

    if _assistant_id:
        return _assistant_id, None

    try:
        search_response = requests.post(
            _url("/assistants/search"),
            json={"graph_id": LANGGRAPH_GRAPH_NAME, "limit": 1},
            timeout=10,
        )

        if search_response.status_code == 200:
            assistants = search_response.json()
            if assistants:
                _assistant_id = assistants[0]["assistant_id"]
                logger.info("找到现有助手: %s", _assistant_id)
                return _assistant_id, None

        create_response = requests.post(
            _url("/assistants"),
            json={
                "graph_id": LANGGRAPH_GRAPH_NAME,
                "name": "Customer Service Assistant",
                "description": "Multi-agent customer service system",
            },
            timeout=10,
        )

        if create_response.status_code == 200:
            _assistant_id = create_response.json()["assistant_id"]
            logger.info("创建新助手: %s", _assistant_id)
            return _assistant_id, None

        logger.error("创建助手失败: HTTP %s", create_response.status_code)
        return None, f"创建助手失败: HTTP {create_response.status_code}"

    except Exception as e:
        logger.error("确保助手存在时出错: %s", e)
        return None, f"连接 LangGraph 服务失败: {e}"


def create_thread() -> Tuple[Optional[str], Optional[str]]:
    """新建一条 LangGraph 线程。成功返回 (thread_id, None)。"""
    try:
        response = requests.post(_url("/threads"), json={}, timeout=10)
    except requests.RequestException as e:
        logger.error("创建线程请求失败: %s", e)
        return None, f"创建线程失败: {e}"

    if response.status_code != 200:
        logger.error("创建线程失败: HTTP %s", response.status_code)
        return None, f"创建线程失败: HTTP {response.status_code}"

    thread_id = (response.json() or {}).get("thread_id")
    if not thread_id:
        return None, "创建线程失败: 响应缺少 thread_id"

    logger.info("创建新线程: %s", thread_id)
    return thread_id, None


def thread_exists(thread_id: str) -> bool:
    """校验线程是否真实存在。"""
    try:
        return requests.get(_url(f"/threads/{thread_id}"), timeout=5).status_code == 200
    except requests.RequestException as e:
        logger.warning("校验线程 %s 时出错: %s", thread_id, e)
        return False


def resolve_thread(client_session_id: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    解析出本轮请求应使用的线程 ID。

    - 传入真实存在的线程 ID → 复用，实现多轮续聊
    - 传入无效 ID（例如前端本地生成的 `web_<时间戳>`）→ **新建线程**，
      绝不回落到其他请求使用过的线程
    - 未传入 → 新建线程

    成功返回 (thread_id, None)。
    """
    sid = (client_session_id or "").strip()

    if sid and sid != "default":
        if thread_exists(sid):
            return sid, None
        logger.info("会话 ID %s 不是有效的 LangGraph 线程，为其新建线程", sid)

    return create_thread()


def clear_thread_and_create_new(thread_id: str) -> Tuple[Optional[str], Optional[str]]:
    """删除旧线程并新建一条替代线程。成功返回 (new_thread_id, None)。"""
    ok, status = delete_remote_thread(thread_id)
    if not ok:
        return None, f"清空会话失败: HTTP {status}"
    return create_thread()


def delete_remote_thread(thread_id: str) -> Tuple[bool, int]:
    """删除 LangGraph 线程。成功为任意 2xx（DELETE 常为 204 No Content）。"""
    try:
        response = requests.delete(_url(f"/threads/{thread_id}"), timeout=10)
    except requests.RequestException as e:
        logger.error("删除线程失败: %s", e)
        return False, 0
    return 200 <= response.status_code < 300, response.status_code


# -----------------------------------------------------------------------------
# 会话列表 / 详情
# -----------------------------------------------------------------------------


def _normalize_created_at(created_at: Any) -> float:
    if isinstance(created_at, str):
        try:
            return _dt.datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp()
        except Exception:
            return time.time()
    if isinstance(created_at, (int, float)) and created_at > 0:
        return float(created_at)
    return time.time()


def _message_count_from_state_data(state_data: Dict[str, Any]) -> int:
    if "values" in state_data and isinstance(state_data["values"], dict):
        values = state_data["values"]
        if values.get("conversation_history"):
            return len(values["conversation_history"])
        if "messages" in values:
            return len(values["messages"])
        if values.get("response"):
            return 1
    if "messages" in state_data:
        return len(state_data["messages"])
    return 0


def fetch_sessions_list(limit: int = 50) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    拉取线程列表并拼装前端会话项。
    成功返回 (sessions, None)，失败返回 (None, error_message)。
    """
    try:
        response = requests.post(_url("/threads/search"), json={"limit": limit}, timeout=10)

        if response.status_code != 200:
            logger.error("获取线程列表失败: HTTP %s", response.status_code)
            return None, f"获取会话列表失败: HTTP {response.status_code}"

        sessions: List[Dict[str, Any]] = []
        for thread in response.json():
            thread_id = thread.get("thread_id", "")
            message_count = 0
            last_user_question = ""
            try:
                state_response = requests.get(_url(f"/threads/{thread_id}/state"), timeout=5)
                if state_response.status_code == 200:
                    state_data = state_response.json()
                    parsed = conversation_history_from_state_data(state_data)
                    last_user_question = last_user_question_from_history(parsed)
                    message_count = _message_count_from_state_data(state_data)
            except requests.RequestException as e:
                logger.warning("读取线程 %s 状态失败: %s", thread_id, e)

            sessions.append({
                "session_id": thread_id,
                "created_at": _normalize_created_at(thread.get("created_at", time.time())),
                "message_count": message_count,
                "last_user_question": last_user_question,
            })

        return sessions, None

    except Exception as e:
        logger.exception("获取会话列表时出错")
        return None, f"服务器错误: {e}"


def fetch_session_detail(session_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """获取单个线程详情 + 对话历史。成功返回 (payload, None)。"""
    try:
        response = requests.get(_url(f"/threads/{session_id}"), timeout=10)
        if response.status_code != 200:
            logger.error("获取线程详情失败: HTTP %s", response.status_code)
            return None, f"获取会话详情失败: HTTP {response.status_code}"

        thread_data = response.json()
        conversation_history: List[Dict[str, Any]] = []

        try:
            state_response = requests.get(_url(f"/threads/{session_id}/state"), timeout=5)
            if state_response.status_code == 200:
                conversation_history = conversation_history_from_state_data(state_response.json())
            else:
                logger.warning("获取线程状态失败: HTTP %s", state_response.status_code)
        except requests.RequestException as e:
            logger.warning("获取线程状态时出错: %s", e)

        session_data = {
            "session_id": session_id,
            "created_at": thread_data.get("created_at", time.time()),
            "conversation_history": conversation_history,
        }
        return session_data, None

    except Exception as e:
        logger.exception("获取会话详情时出错")
        return None, f"服务器错误: {e}"


# -----------------------------------------------------------------------------
# 一次聊天运行
# -----------------------------------------------------------------------------


def _poll_interval(attempt: int) -> float:
    """轮询退避：前几轮快、之后放慢，兼顾响应延迟与请求量。"""
    return min(0.4 * (1.5 ** attempt), 2.0)


def _wait_for_run(thread_id: str, run_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """轮询运行状态直到结束。成功返回 (thread_state, None)。"""
    started = time.time()
    attempt = 0

    while True:
        if time.time() - started > RUN_TIMEOUT_SECONDS:
            logger.warning("运行超时，已等待 %s 秒", RUN_TIMEOUT_SECONDS)
            return None, "运行超时，请稍后重试"

        time.sleep(_poll_interval(attempt))
        attempt += 1

        try:
            status_response = requests.get(
                _url(f"/threads/{thread_id}/runs/{run_id}"), timeout=10
            )
        except requests.RequestException as e:
            logger.error("获取运行状态失败: %s", e)
            return None, f"获取运行状态失败: {e}"

        if status_response.status_code != 200:
            logger.error("获取运行状态失败: HTTP %s", status_response.status_code)
            return None, f"获取运行状态失败: HTTP {status_response.status_code}"

        run_status = (status_response.json() or {}).get("status", "unknown")

        if run_status in ("completed", "success"):
            state_response = requests.get(_url(f"/threads/{thread_id}/state"), timeout=10)
            if state_response.status_code != 200:
                return None, "无法获取线程状态"
            return state_response.json(), None

        if run_status in ("failed", "cancelled", "error", "timeout"):
            logger.error("运行失败: %s", run_status)
            return None, f"运行失败: {run_status}"


def _submit_run(thread_id: str, assistant_id: str, user_message: str) -> Tuple[Optional[str], Optional[str]]:
    """向线程提交一轮用户消息，返回 (run_id, error)。"""
    payload = {
        "assistant_id": assistant_id,
        "input": {
            "messages": [{"role": "user", "content": user_message}],
            "customer_query": user_message,
            "session_id": thread_id,
        },
    }
    try:
        run_resp = requests.post(_url(f"/threads/{thread_id}/runs"), json=payload, timeout=30)
    except requests.RequestException as e:
        logger.error("提交运行失败: %s", e)
        return None, f"调用失败: {e}"

    if run_resp.status_code != 200:
        logger.error("创建运行失败: HTTP %s", run_resp.status_code)
        return None, f"调用失败: HTTP {run_resp.status_code}"

    run_id = (run_resp.json() or {}).get("run_id")
    if not run_id:
        return None, "调用失败: 响应缺少 run_id"
    return run_id, None


def run_chat_sync(user_message: str, client_session_id: Optional[str] = None) -> ChatOutcome:
    """
    在当前线程上提交一轮用户消息并等待完成。

    返回的 ChatOutcome 一定带回 `thread_id`；调用方应把它持久化并在后续请求中回传，
    这样才能实现多轮续聊。
    """
    message = (user_message or "").strip()
    if not message:
        return ChatOutcome(error="消息不能为空", http_status=400)

    assistant_id, err = ensure_assistant_exists()
    if err:
        return ChatOutcome(error=err, http_status=500)

    thread_id, err = resolve_thread(client_session_id)
    if err:
        return ChatOutcome(error=err, http_status=500)

    try:
        run_id, err = _submit_run(thread_id, assistant_id, message)
        if err:
            return ChatOutcome(error=err, http_status=500, thread_id=thread_id)

        thread_state, err = _wait_for_run(thread_id, run_id)
        if err:
            return ChatOutcome(error=err, http_status=500, thread_id=thread_id)

        meta = extract_response_meta(thread_state)
        return ChatOutcome(
            text=extract_ai_response(thread_state),
            thread_id=thread_id,
            agent=meta["agent"],
            query_type=meta["query_type"],
        )

    except Exception as e:
        logger.exception("聊天处理错误")
        return ChatOutcome(error=f"内部错误: {e}", http_status=500, thread_id=thread_id)


def stream_chat_events(user_message: str, client_session_id: Optional[str] = None) -> Iterable[str]:
    """
    生成 SSE data 行（含末尾 [DONE]）。

    ⚠️ 这不是 token 级流式：当前实现是「提交运行 → 轮询到完成 → 一次性写出整段回复」，
    只是把等待过程包装成 SSE 形状。若要真正的逐 token 输出，应改用 LangGraph 的
    `POST /threads/{tid}/runs/stream` 并以 stream=True 透传事件。
    """
    def sse(payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    message = (user_message or "").strip()
    if not message:
        yield sse({"error": "消息不能为空"})
        yield "data: [DONE]\n\n"
        return

    assistant_id, err = ensure_assistant_exists()
    if err:
        yield sse({"error": err})
        yield "data: [DONE]\n\n"
        return

    thread_id, err = resolve_thread(client_session_id)
    if err:
        yield sse({"error": err})
        yield "data: [DONE]\n\n"
        return

    try:
        run_id, err = _submit_run(thread_id, assistant_id, message)
        if err:
            yield sse({"error": err})
            yield "data: [DONE]\n\n"
            return

        thread_state, err = _wait_for_run(thread_id, run_id)
        if err:
            yield sse({"error": err})
        else:
            meta = extract_response_meta(thread_state)
            yield sse({
                "content": extract_ai_response(thread_state),
                "session_id": thread_id,
                "thread_id": thread_id,
                "agent": meta["agent"],
                "query_type": meta["query_type"],
            })
    except Exception as e:
        logger.exception("流式处理错误")
        yield sse({"error": f"流式处理错误: {e}"})

    yield "data: [DONE]\n\n"


def langgraph_connectivity_test() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """探测 LangGraph 服务与搜索接口。成功返回 (result, None)。"""
    try:
        health_check_status = 0
        try:
            health_check_status = requests.get(_url("/ok"), timeout=5).status_code
        except requests.RequestException as e:
            logger.warning("LangGraph GET /ok 失败: %s", e)

        threads_response = requests.post(_url("/threads/search"), json={}, timeout=10)
        assistants_response = requests.post(_url("/assistants/search"), json={}, timeout=10)

        if not (200 <= health_check_status < 300) and (200 <= threads_response.status_code < 300):
            logger.warning("GET /ok 未成功，但 threads/search 正常，健康检查标记为通过")
            health_check_status = 200

        return ({
            "status": "test_completed",
            "health_check": health_check_status,
            "threads_search": threads_response.status_code,
            "assistants_search": assistants_response.status_code,
            "details": {
                "ok_response": "OK" if 200 <= health_check_status < 300 else (health_check_status or "unreachable"),
                "threads_response": threads_response.text if threads_response.status_code != 200 else "OK",
                "assistants_response": assistants_response.text if assistants_response.status_code != 200 else "OK",
            },
        }, None)

    except Exception as e:
        logger.exception("测试 LangGraph API 时出错")
        return None, f"测试失败: {e}"
