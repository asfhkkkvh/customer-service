#!/usr/bin/env python3
"""
多智能体客服系统 - Web 入口（FastAPI）。

图在应用进程内运行（见 webapp/service.py），不依赖 LangGraph Platform 服务。
本层只做路由与 HTTP 服务。
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import service  # noqa: E402
from config import LOG_CONFIG  # noqa: E402

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent  # 项目根（webapp/ 的上一级）

# React（Vite）构建产物：dist 已随仓库提交，无 Node 环境也可直接启动。
# 前端源码与构建方式见 frontend/ 目录。
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动时构建图与 checkpointer，关闭时释放 SQLite 连接。"""
    await service.startup()
    try:
        yield
    finally:
        await service.shutdown()


app = FastAPI(title="多智能体客服系统", version="2.0.0", lifespan=lifespan)

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
    """主页：React 构建产物（未构建时返回操作指引）"""
    index_html = FRONTEND_DIST / "index.html"
    if not index_html.exists():
        return JSONResponse(
            status_code=503,
            content={
                "error": "前端尚未构建",
                "hint": "在 frontend/ 目录执行 npm install && npm run build 后重启服务",
            },
        )
    return FileResponse(index_html, media_type="text/html")


# Vite 产物静态资源（带 hash 的 js/css）
_assets_dir = FRONTEND_DIST / "assets"
if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")


# --- 聊天 ---


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """
    处理一轮聊天（在图执行完成后返回）。

    响应中的 thread_id 是服务端线程 ID：首次对话由服务端生成，前端**必须**保存并在
    后续请求中回传，否则每轮都会落成新会话、无法续聊。
    """
    result = await service.run_chat(req.message, req.session_id)

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
async def chat_stream(req: ChatRequest):
    """
    SSE 聊天端点。

    注意：当前实现为"运行完成后一次性返回"，不是 token 级流式；
    前端默认走阻塞式 /api/chat，此端点保留给需要 SSE 形状的调用方。
    """
    return StreamingResponse(
        service.stream_chat_events(req.message, req.session_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- 会话管理 ---


@app.delete("/api/conversation/{thread_id}")
async def delete_conversation(thread_id: str):
    """
    删除会话：清掉该线程的 checkpoint。

    会话列表由前端 localStorage 维护，后端只负责删服务端状态。
    """
    ok, err = await service.delete_conversation(thread_id)
    if ok:
        return {"message": "会话删除成功"}
    return JSONResponse(status_code=502, content={"error": err})


# --- 健康与诊断 ---


@app.get("/api/health")
def health_check():
    """健康检查"""
    return {"status": "healthy", "timestamp": time.time(), "ready": service.is_ready()}


@app.get("/api/test")
async def test_runtime():
    """图与持久化自检（节点清单、checkpointer、落盘位置、会话数）"""
    return await service.graph_info()


def main():
    """主函数"""
    logging.basicConfig(level=LOG_CONFIG["level"], format=LOG_CONFIG["format"])
    port = int(os.getenv("WEB_PORT", "5000"))
    print("🚀 多智能体客服系统 Web 应用 (FastAPI，进程内运行 LangGraph)")
    print("=" * 60)
    print(f"🌐 启动 Web 服务: http://localhost:{port}")
    print("💡 按 Ctrl+C 停止服务（或另开终端用 `uvicorn webapp.app:app --port 5000` 直启）")
    print()
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
