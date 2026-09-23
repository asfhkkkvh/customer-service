"""Web API 契约测试：锁住前端依赖的响应字段与状态码语义。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import chat_web_service as svc
import web_app

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client():
    return TestClient(web_app.app)


def test_chat_response_carries_thread_id_and_agent_meta(monkeypatch, client):
    """
    前端依赖 thread_id 回写才能续聊；依赖 agent/query_type 渲染专家徽章。
    这两个字段一旦缺一个，前端对应功能就是死代码。
    """
    monkeypatch.setattr(
        web_app,
        "run_chat_sync",
        lambda message, session_id: svc.ChatOutcome(
            text="退款已受理", thread_id="thread-9", agent="账单专家", query_type="billing"
        ),
    )

    resp = client.post("/api/chat", json={"message": "我要退款", "session_id": "web_1"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["thread_id"] == "thread-9"
    assert body["session_id"] == "thread-9"
    assert body["response"] == "退款已受理"
    assert body["agent"] == "账单专家"
    assert body["query_type"] == "billing"


def test_blank_message_returns_400(monkeypatch, client):
    monkeypatch.setattr(
        web_app, "run_chat_sync", lambda m, s: svc.ChatOutcome(error="消息不能为空", http_status=400)
    )
    resp = client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 400


def test_upstream_failure_is_reported_as_502(monkeypatch, client):
    monkeypatch.setattr(
        web_app, "run_chat_sync", lambda m, s: svc.ChatOutcome(error="运行超时，请稍后重试", http_status=500)
    )
    resp = client.post("/api/chat", json={"message": "你好"})
    assert resp.status_code == 502
    assert "运行超时" in resp.json()["error"]


def test_new_session_returns_a_real_server_side_thread_id(monkeypatch, client):
    monkeypatch.setattr(web_app, "create_thread", lambda: ("thread-77", None))
    resp = client.post("/api/new_session")
    assert resp.status_code == 200
    assert resp.json()["thread_id"] == "thread-77"


def test_new_session_reports_failure_when_langgraph_unreachable(monkeypatch, client):
    monkeypatch.setattr(web_app, "create_thread", lambda: (None, "创建线程失败"))
    resp = client.post("/api/new_session")
    assert resp.status_code == 502


def test_sessions_list_and_detail(monkeypatch, client):
    monkeypatch.setattr(web_app, "fetch_sessions_list", lambda: ([{"session_id": "thread-1"}], None))
    monkeypatch.setattr(
        web_app,
        "fetch_session_detail",
        lambda sid: ({"session_id": sid, "created_at": 0.0, "conversation_history": []}, None),
    )

    assert client.get("/api/sessions").json()["sessions"][0]["session_id"] == "thread-1"
    assert client.get("/api/sessions/thread-1").json()["session"]["session_id"] == "thread-1"


def test_export_session_returns_downloadable_json(monkeypatch, client):
    monkeypatch.setattr(
        web_app,
        "fetch_session_detail",
        lambda sid: (
            {
                "session_id": sid,
                "created_at": 0.0,
                "conversation_history": [
                    {"is_user": True, "content": "我要退款", "role": "user"},
                    {"is_user": False, "content": "已受理", "role": "assistant"},
                ],
            },
            None,
        ),
    )

    resp = client.get("/api/sessions/thread-1/export")

    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    body = resp.json()
    assert body["session_id"] == "thread-1"
    assert body["message_count"] == 2
    assert len(body["conversation_history"]) == 2


def test_health_and_index_page(client):
    assert client.get("/api/health").json()["status"] == "healthy"
    assert client.get("/").status_code == 200


def test_frontend_writes_back_thread_id():
    """
    回归：前端曾用本地伪 ID（'web_<时间戳>'）且从不回写服务端 thread_id，
    导致后端无法识别会话。这里静态守住修复结果。
    """
    html = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert "currentSessionId = data.thread_id" in html, "前端没有回写服务端 thread_id"
    assert "'web_' + Date.now()" not in html, "前端又用回了本地伪会话 ID"
