#!/usr/bin/env python3
"""
多智能体客服系统 - Web 入口（FastAPI）。

只做路由与 HTTP 服务，业务逻辑见 chat_web_service.py。
本层不依赖 LangChain / LangGraph，只通过 REST 与 LangGraph 服务通信。
"""

import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import (  # noqa: E402
    FileResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from pydantic import BaseModel  # noqa: E402

from chat_web_service import (  # noqa: E402
    clear_thread_and_create_new,
    create_thread,
    delete_remote_thread,
    fetch_session_detail,
    fetch_sessions_list,
    langgraph_connectivity_test,
    run_chat_sync,
    stream_chat_events,
)
from config import LOG_CONFIG  # noqa: E402

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="多智能体客服系统", version="1.0.0")

# CORS：同源渲染本不需要，放开以兼容 file:// 直接打开或后续跨端口部署。
# 可通过 WEB_CORS_ORIGINS 收紧（逗号分隔）。
_cors_origins = [o.strip() for o in os.getenv("WEB_CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 请求模型 ---


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


# --- 页面 ---


@app.get("/")
def index():
    """主页（纯静态单页，无模板变量注入）"""
    return FileResponse(BASE_DIR / "templates" / "index.html", media_type="text/html")


# --- 聊天 ---


@app.post("/api/chat")
def chat(req: ChatRequest):
    """
    处理聊天请求（阻塞等待 LangGraph 运行完成）。

    响应中的 thread_id 是服务端真实线程 ID，前端**必须**保存并在后续请求中回传，
    否则每轮都会新建线程、无法续聊。
    """
    result = run_chat_sync(req.message, req.session_id)

    if not result.ok:
        # 空消息属客户端错误，原样透传其状态码
        status = result.http_status if 400 <= result.http_status < 500 else 502
        return JSONResponse(status_code=status, content={"error": result.error})

    return {
        "response": result.text,
        "session_id": result.thread_id,
        "thread_id": result.thread_id,
        "agent": result.agent,
        "query_type": result.query_type,
    }


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    """
    SSE 聊天端点。

    注意：当前实现为"轮询完成后一次性返回"，不是 token 级流式；
    前端默认走阻塞式 /api/chat，此端点保留给需要 SSE 形状的调用方。
    """
    return StreamingResponse(
        stream_chat_events(req.message, req.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- 会话管理 ---


@app.get("/api/sessions")
def get_sessions():
    """获取会话列表"""
    sessions, err = fetch_sessions_list()
    if err:
        return JSONResponse(status_code=502, content={"error": err})
    return {"sessions": sessions or []}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    """获取特定会话详情"""
    session_data, err = fetch_session_detail(session_id)
    if err:
        return JSONResponse(status_code=502, content={"error": err})
    return {"session": session_data}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    """删除会话"""
    ok, status = delete_remote_thread(session_id)
    if ok:
        return {"message": "会话删除成功"}
    return JSONResponse(status_code=502, content={"error": f"删除会话失败: HTTP {status}"})


@app.post("/api/sessions/{session_id}/clear")
def clear_session(session_id: str):
    """清空会话（删除旧线程并新建一条）"""
    new_thread_id, err = clear_thread_and_create_new(session_id)
    if err:
        return JSONResponse(status_code=502, content={"error": err})
    return {"message": "会话清空成功", "new_thread_id": new_thread_id}


@app.get("/api/sessions/{session_id}/export")
def export_session(session_id: str):
    """
    导出单个会话的完整对话记录（JSON 下载），用于离线分析。

    以附件形式返回，浏览器会直接下载成 session-<id>.json。
    """
    session_data, err = fetch_session_detail(session_id)
    if err:
        return JSONResponse(status_code=502, content={"error": err})

    history = session_data.get("conversation_history") or []
    payload = {
        "session_id": session_id,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "message_count": len(history),
        "conversation_history": history,
    }
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="session-{session_id}.json"'},
    )


@app.post("/api/new_session")
def create_new_session():
    """
    创建新会话：由服务端真实创建 LangGraph 线程并返回其 ID。

    不再返回本地伪 ID —— 伪 ID 会在后端校验失败后触发"回落"行为，
    导致不同用户共用线程。
    """
    thread_id, err = create_thread()
    if err:
        return JSONResponse(status_code=502, content={"error": err})
    return {"session_id": thread_id, "thread_id": thread_id, "message": "新会话创建成功"}


# --- 健康与诊断 ---


@app.get("/api/health")
def health_check():
    """健康检查"""
    return {"status": "healthy", "timestamp": time.time()}


@app.get("/api/test")
def test_langgraph():
    """测试 LangGraph API 调用"""
    result, err = langgraph_connectivity_test()
    if err:
        return JSONResponse(status_code=502, content={"error": err})
    return result


def main():
    """主函数"""
    logging.basicConfig(level=LOG_CONFIG["level"], format=LOG_CONFIG["format"])
    port = int(os.getenv("WEB_PORT", "5000"))
    print("🚀 多智能体客服系统 Web 应用 (FastAPI)")
    print("=" * 60)
    print(f"🌐 启动 Web 服务: http://localhost:{port}")
    print("💡 按 Ctrl+C 停止服务（或另开终端用 `uvicorn web_app:app --port 5000` 直启）")
    print()
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
