"""
会话隔离回归测试（离线，requests 已打桩）。

这是本项目最容易踩、也最容易被面试官问到的一类问题：
线程 ID 一旦放进模块级全局变量，不同用户就会共用同一条线程。
"""

from conftest import FakeResponse

import chat_web_service as svc


class _FakeLangGraph:
    """最小的 LangGraph REST 替身：只维护线程集合与固定的运行结果。"""

    def __init__(self, assistant_id="asst-1", response_text="已为您处理。", thread_state=None):
        self.assistant_id = assistant_id
        self.response_text = response_text
        self.thread_state = thread_state or {
            "values": {"response": response_text, "current_agent": "账单专家", "query_type": "billing"}
        }
        self.threads = []
        self.run_calls = []
        self._seq = 0

    # --- requests.get ---
    def get(self, url, **kwargs):
        if "/runs/" in url:
            return FakeResponse(200, {"status": "completed"})
        if url.endswith("/state"):
            return FakeResponse(200, self.thread_state)
        tid = url.rsplit("/", 1)[-1]
        return FakeResponse(200 if tid in self.threads else 404, {"thread_id": tid})

    # --- requests.post ---
    def post(self, url, **kwargs):
        if url.endswith("/assistants/search"):
            return FakeResponse(200, [{"assistant_id": self.assistant_id}])
        if url.endswith("/assistants"):
            return FakeResponse(200, {"assistant_id": self.assistant_id})
        if url.endswith("/threads"):
            self._seq += 1
            tid = f"thread-{self._seq}"
            self.threads.append(tid)
            return FakeResponse(200, {"thread_id": tid})
        if url.endswith("/runs"):
            self.run_calls.append(kwargs.get("json", {}))
            return FakeResponse(200, {"run_id": f"run-{len(self.run_calls)}"})
        return FakeResponse(404)

    # --- requests.delete ---
    def delete(self, url, **kwargs):
        tid = url.rsplit("/", 1)[-1]
        if tid in self.threads:
            self.threads.remove(tid)
            return FakeResponse(204)
        return FakeResponse(404)


def _install(monkeypatch, backend):
    monkeypatch.setattr(svc.requests, "get", backend.get)
    monkeypatch.setattr(svc.requests, "post", backend.post)
    monkeypatch.setattr(svc.requests, "delete", backend.delete)
    monkeypatch.setattr(svc.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(svc, "_assistant_id", None)
    return backend


def test_two_clients_never_share_a_thread(monkeypatch):
    """回归：两个浏览器各自带着无效的本地 ID，必须各拿到一条独立线程。"""
    backend = _install(monkeypatch, _FakeLangGraph())

    tid_a, err_a = svc.resolve_thread("web_1000")
    tid_b, err_b = svc.resolve_thread("web_2000")

    assert err_a is None and err_b is None
    assert tid_a != tid_b, "两个客户端拿到同一条线程，会话串线"
    assert {tid_a, tid_b} == set(backend.threads)


def test_module_has_no_shared_current_thread_state():
    """静态守住设计约定：不允许再出现"当前线程"这类模块级全局变量。"""
    forbidden = [n for n in dir(svc) if "current_thread" in n.lower()]
    assert forbidden == [], f"模块又出现了共享线程状态: {forbidden}"


def test_valid_thread_id_is_reused(monkeypatch):
    backend = _install(monkeypatch, _FakeLangGraph())
    tid, _ = svc.create_thread()

    reused, err = svc.resolve_thread(tid)

    assert err is None
    assert reused == tid
    assert len(backend.threads) == 1, "复用已有线程时不应再新建"


def test_missing_session_id_creates_a_new_thread(monkeypatch):
    backend = _install(monkeypatch, _FakeLangGraph())

    tid_none, _ = svc.resolve_thread(None)
    tid_default, _ = svc.resolve_thread("default")

    assert tid_none and tid_default
    assert tid_none != tid_default
    assert len(backend.threads) == 2


def test_run_chat_sync_returns_the_thread_of_this_request(monkeypatch):
    backend = _install(monkeypatch, _FakeLangGraph(response_text="退款已受理"))

    outcome_a = svc.run_chat_sync("我要退款", "web_1000")
    outcome_b = svc.run_chat_sync("我要退款", "web_2000")

    assert outcome_a.ok and outcome_b.ok
    assert outcome_a.text == "退款已受理"
    assert outcome_a.thread_id != outcome_b.thread_id
    # 提交给运行时带的 session_id 必须与各自线程一致，不能串
    assert backend.run_calls[0]["input"]["session_id"] == outcome_a.thread_id
    assert backend.run_calls[1]["input"]["session_id"] == outcome_b.thread_id


def test_run_chat_sync_continues_existing_thread(monkeypatch):
    backend = _install(monkeypatch, _FakeLangGraph())

    first = svc.run_chat_sync("第一轮", "web_1")
    second = svc.run_chat_sync("第二轮", first.thread_id)

    assert second.thread_id == first.thread_id, "回传 thread_id 后应继续同一会话"
    assert len(backend.threads) == 1


def test_run_chat_sync_rejects_blank_message(monkeypatch):
    _install(monkeypatch, _FakeLangGraph())

    outcome = svc.run_chat_sync("   ", "web_1")

    assert not outcome.ok
    assert outcome.http_status == 400


def test_run_chat_sync_surfaces_backend_failure(monkeypatch):
    backend = _FakeLangGraph()

    def broken_post(url, **kwargs):
        if url.endswith("/runs"):
            return FakeResponse(500, {})
        return backend.post(url, **kwargs)

    _install(monkeypatch, backend)
    monkeypatch.setattr(svc.requests, "post", broken_post)

    outcome = svc.run_chat_sync("你好", "web_1")

    assert not outcome.ok
    assert outcome.http_status == 500


def test_extract_response_meta_reads_agent_and_type():
    state = {"values": {"current_agent": "投诉处理专家", "query_type": "complaint"}}
    meta = svc.extract_response_meta(state)
    assert meta["agent"] == "投诉处理专家"
    assert meta["query_type"] == "complaint"


def test_extract_response_meta_tolerates_empty_state():
    assert svc.extract_response_meta({}) == {"agent": None, "query_type": None}


def test_stream_chat_events_returns_thread_id(monkeypatch):
    _install(monkeypatch, _FakeLangGraph())

    chunks = list(svc.stream_chat_events("你好", "web_1"))
    body = "".join(chunks)

    assert chunks[-1] == "data: [DONE]\n\n"
    assert '"thread_id": "thread-1"' in body


def test_clear_thread_creates_a_replacement(monkeypatch):
    backend = _install(monkeypatch, _FakeLangGraph())
    old, _ = svc.create_thread()

    new, err = svc.clear_thread_and_create_new(old)

    assert err is None
    assert new != old
    assert old not in backend.threads
