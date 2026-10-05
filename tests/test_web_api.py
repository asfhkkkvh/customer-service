"""Web API 契约测试：锁住前端依赖的响应字段与状态码语义。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import webapp.app as web_app
import webapp.service as svc

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(monkeypatch, tmp_path):
    """
    带 lifespan 的测试客户端。

    TestClient 只有作为上下文管理器使用时才会触发 lifespan（即构建图与
    checkpointer），因此这里必须用 `with`；同时把落盘位置改到 tmp_path，
    避免测试在仓库里生成 data/checkpoints.db。
    """
    monkeypatch.setattr(svc, "CHECKPOINT_DB_PATH", tmp_path / "checkpoints.db")
    with TestClient(web_app.app) as test_client:
        yield test_client


def test_chat_response_carries_thread_id_and_agent_meta(monkeypatch, client):
    """
    前端依赖 thread_id 才能续聊；依赖 agent/query_type 渲染专家徽章。
    这两个字段一旦缺一个，前端对应功能就是死代码。
    """

    async def fake_run_chat(message, session_id=None):
        return svc.ChatOutcome(
            text="退款已受理", thread_id="thread-9", agent="账单专家", query_type="billing"
        )

    monkeypatch.setattr(svc, "run_chat", fake_run_chat)

    resp = client.post("/api/chat", json={"message": "我要退款", "session_id": "web_1"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["thread_id"] == "thread-9"
    assert body["session_id"] == "thread-9"
    assert body["response"] == "退款已受理"
    assert body["agent"] == "账单专家"
    assert body["query_type"] == "billing"


def test_blank_message_returns_400(monkeypatch, client):
    async def fake_run_chat(message, session_id=None):
        return svc.ChatOutcome(error="消息不能为空", http_status=400)

    monkeypatch.setattr(svc, "run_chat", fake_run_chat)
    assert client.post("/api/chat", json={"message": ""}).status_code == 400


def test_runtime_failure_is_reported_as_502(monkeypatch, client):
    async def fake_run_chat(message, session_id=None):
        return svc.ChatOutcome(error="内部错误: 图尚未初始化", http_status=500)

    monkeypatch.setattr(svc, "run_chat", fake_run_chat)

    resp = client.post("/api/chat", json={"message": "你好"})

    assert resp.status_code == 502
    assert "内部错误" in resp.json()["error"]


def test_delete_conversation_endpoint(monkeypatch, client):
    async def ok(thread_id):
        return True, None

    monkeypatch.setattr(svc, "delete_conversation", ok)

    resp = client.delete("/api/conversation/thread-1")

    assert resp.status_code == 200
    assert resp.json()["message"] == "会话删除成功"


def test_delete_conversation_failure_returns_502(monkeypatch, client):
    async def bad(thread_id):
        return False, "服务未就绪"

    monkeypatch.setattr(svc, "delete_conversation", bad)
    assert client.delete("/api/conversation/thread-1").status_code == 502


def test_self_check_endpoint_reports_graph_info(monkeypatch, client):
    async def info():
        return {
            "status": "ready",
            "checkpointer": "AsyncSqliteSaver",
            "node_count": 6,
            "persisted_threads": 2,
        }

    monkeypatch.setattr(svc, "graph_info", info)

    body = client.get("/api/test").json()

    assert body["status"] == "ready"
    assert body["checkpointer"] == "AsyncSqliteSaver"


def test_health_and_index_page(client):
    assert client.get("/api/health").json()["status"] == "healthy"
    assert client.get("/").status_code == 200


def test_rest_session_endpoints_are_removed(client):
    """
    架构回归：会话列表/详情已改为前端 localStorage，后端只保留删除接口。
    若这些 REST 端点又被加回来，说明有调用方仍在依赖服务端会话列表。
    """
    assert client.get("/api/sessions").status_code == 404
    assert client.get("/api/sessions/thread-1").status_code == 404
    assert client.post("/api/new_session").status_code == 404


def test_frontend_keeps_thread_id_and_stores_conversations_locally():
    """
    前端约定（静态检查）：
    - 会话 ID 由前端生成并作为 thread_id 传给后端
    - 会话列表与历史落在 localStorage，不再调用已下线的 REST 会话接口
    """
    app_src = (PROJECT_ROOT / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    conv_src = (PROJECT_ROOT / "frontend" / "src" / "conversations.js").read_text(encoding="utf-8")
    api_src = (PROJECT_ROOT / "frontend" / "src" / "api.js").read_text(encoding="utf-8")

    assert "sendChat(text, convId)" in app_src, "前端没有把会话 ID 作为 thread_id 传给后端"
    assert "cs_conversations" in conv_src, "会话列表没有落到 localStorage"
    assert "'web_' + Date.now()" not in app_src, "前端又用回了本地伪会话 ID"
    assert "/api/sessions" not in api_src, "api.js 仍在调用已下线的 REST 会话接口"
