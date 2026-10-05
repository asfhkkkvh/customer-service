"""
会话隔离回归测试（进程内运行，LLM 为可计数假实现，离线零成本）。

这是本项目最容易踩、也最容易被面试官问到的一类问题：
线程 ID 一旦放进模块级全局变量，不同用户就会共用同一条线程 / 同一份 checkpoint。

改造后图在应用进程内运行，隔离由「LangGraph config 的 thread_id + checkpointer」保证，
本文件即守住这条约定。
"""

import asyncio
from contextlib import asynccontextmanager

import pytest

import webapp.service as svc


@asynccontextmanager
async def runtime(monkeypatch, tmp_path, **llm_kwargs):
    """启动一个进程内运行时：临时 SQLite + 假 LLM，退出时自动关闭。"""
    import workflow.graph as graph_mod
    from conftest import CountingLLM

    monkeypatch.setattr(svc, "CHECKPOINT_DB_PATH", tmp_path / "checkpoints.db")
    llm = CountingLLM(**llm_kwargs)
    monkeypatch.setattr(graph_mod, "get_llm", lambda: llm)

    await svc.startup()
    try:
        yield llm
    finally:
        await svc.shutdown()


def test_module_has_no_shared_current_thread_state():
    """静态守住设计约定：不允许出现"当前线程"这类模块级全局变量。"""
    forbidden = [n for n in dir(svc) if "current_thread" in n.lower()]
    assert forbidden == [], f"模块又出现了共享线程状态: {forbidden}"


def test_new_thread_id_is_unique():
    assert svc.new_thread_id() != svc.new_thread_id()


def test_missing_and_default_session_get_distinct_threads(monkeypatch, tmp_path):
    """未传 session_id 与传 'default' 哨兵，都必须各自落到不同的新线程。"""

    async def scenario():
        async with runtime(monkeypatch, tmp_path, classify_label="billing") as _llm:
            a = await svc.run_chat("我要退款", None)
            b = await svc.run_chat("我要退款", "default")
            assert a.thread_id and b.thread_id
            assert a.thread_id != b.thread_id, "两次未指定会话的请求落到了同一条线程"

    asyncio.run(scenario())


def test_second_turn_on_same_thread_sees_the_first(monkeypatch, tmp_path):
    """回传 thread_id 后，第二轮必须能读到第一轮的持久化轮次。"""

    async def scenario():
        async with runtime(monkeypatch, tmp_path, classify_label="product_info") as llm:
            first = await svc.run_chat("手机有什么型号", "t-keep")
            second = await svc.run_chat("那耳机呢", "t-keep")

            assert first.thread_id == second.thread_id
            expert_prompt = "\n".join(str(m.content) for m in llm.calls[-1])
            assert "手机有什么型号" in expert_prompt, "第二轮 prompt 未带上第一轮，续聊上下文丢失"

    asyncio.run(scenario())


def test_two_threads_do_not_leak_context(monkeypatch, tmp_path):
    """回归：A 线程说过的话，绝不能在 B 线程的 prompt 里出现。"""

    async def scenario():
        async with runtime(monkeypatch, tmp_path, classify_label="general_inquiry") as llm:
            await svc.run_chat("这是A线程的秘密问题", "thread-A")
            calls_after_a = len(llm.calls)

            await svc.run_chat("这是B线程的问题", "thread-B")

            later = llm.calls[calls_after_a:]
            joined = "\n".join(str(m.content) for call in later for m in call)
            assert "这是A线程的秘密问题" not in joined, "线程之间发生了上下文串线"

    asyncio.run(scenario())


def test_blank_message_is_rejected(monkeypatch, tmp_path):
    async def scenario():
        async with runtime(monkeypatch, tmp_path) as _llm:
            outcome = await svc.run_chat("   ", "t-blank")
            assert not outcome.ok
            assert outcome.http_status == 400

    asyncio.run(scenario())


def test_delete_conversation_clears_persisted_state(monkeypatch, tmp_path):
    async def scenario():
        async with runtime(monkeypatch, tmp_path, classify_label="billing") as _llm:
            await svc.run_chat("你好", "t-del")
            assert await svc.persisted_thread_count() == 1

            ok, err = await svc.delete_conversation("t-del")

            assert ok and err is None
            assert await svc.persisted_thread_count() == 0, "删除后 checkpoint 未被清理"

    asyncio.run(scenario())


def test_extract_response_meta_reads_agent_and_type():
    meta = svc.extract_response_meta({"current_agent": "投诉处理专家", "query_type": "complaint"})
    assert meta["agent"] == "投诉处理专家"
    assert meta["query_type"] == "complaint"


def test_extract_response_meta_tolerates_empty_state():
    assert svc.extract_response_meta({}) == {"agent": None, "query_type": None}


def test_stream_chat_events_carries_thread_id(monkeypatch, tmp_path):
    async def scenario():
        async with runtime(monkeypatch, tmp_path, classify_label="billing", reply="已受理") as _llm:
            chunks = [chunk async for chunk in svc.stream_chat_events("你好", "t-sse")]
            body = "".join(chunks)

            assert chunks[-1] == "data: [DONE]\n\n"
            assert '"thread_id": "t-sse"' in body
            assert "已受理" in body

    asyncio.run(scenario())
