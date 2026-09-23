"""专家 Agent：模板方法、召回边界、异常兜底、消息结构。"""

import pytest

from conftest import CountingLLM
from multi_agents import (
    BillingAgent,
    ComplaintAgent,
    GeneralAgent,
    ProductAgent,
    TechAgent,
)

ALL_AGENTS = [ProductAgent, TechAgent, BillingAgent, ComplaintAgent, GeneralAgent]


@pytest.mark.parametrize("agent_cls", ALL_AGENTS)
def test_every_agent_loads_its_knowledge_base(agent_cls):
    agent = agent_cls()
    assert agent.knowledge is not None, f"{agent_cls.__name__} 未挂载知识库"
    assert agent.knowledge.categories, f"{agent_cls.__name__} 的知识库为空"
    assert agent.name and agent.role and agent.expertise


@pytest.mark.parametrize("agent_cls", ALL_AGENTS)
def test_agents_build_context_prompt_and_knowledge_messages(agent_cls, fake_llm):
    """有历史时消息结构应为：历史上下文 + 系统提示 + 当前查询（含知识片段）。"""
    agent = agent_cls()
    agent.set_llm(fake_llm)

    state = {
        "customer_query": "我要退款",
        "persisted_dialogue": [
            {"content": "你好", "is_user": True, "timestamp": "2026-01-01 00:00:00"},
            {"content": "您好，请问有什么可以帮您", "is_user": False, "timestamp": "2026-01-01 00:00:01"},
        ],
        "tools_used": [],
    }

    out = agent.process(state)

    assert out["response"] == fake_llm.reply
    assert out["current_agent"] == agent.name
    assert len(fake_llm.calls) == 1, "单个 Agent 每轮只应调用一次 LLM"
    assert len(fake_llm.calls[0]) == 3, "消息应为：上下文 + 系统提示 + 查询"
    assert any("你好" in str(m.content) for m in fake_llm.calls[0]), "历史未拼进 prompt"


def test_recall_does_not_fall_back_to_whole_knowledge_base():
    """
    回归：兜底分支曾写错成"只要查询里出现泛词，就把整个知识库塞进上下文"，
    等于召回层失效。现在无命中就应返回空列表。
    """
    agent = ProductAgent()
    total = len(agent.knowledge.categories)

    assert agent.recall("你能推荐一款适合我的产品吗") == []
    assert agent.recall("随便聊聊") == []
    assert len(agent.recall("我想买个手机")) < total


def test_recall_is_precise_and_ordered():
    agent = ProductAgent()
    hits = agent.recall("我想买个手机")
    assert [h.category.name for h in hits] == ["手机"]

    tech = TechAgent()
    hits = tech.recall("屏幕坏了，而且充电口也有问题")
    assert [h.category.name for h in hits] == ["硬件问题"]


def test_recall_respects_top_n():
    agent = TechAgent()
    hits = agent.recall("开机就卡顿崩溃，系统越来越耗电，屏幕还发烫")
    assert 1 <= len(hits) <= agent.recall_top_n


def test_recall_is_deterministic():
    """同样输入多次调用结果一致（关键词打分的意义就在这里）。"""
    agent = ComplaintAgent()
    first = [h.category.name for h in agent.recall("快递一直没到，物流延迟")]
    for _ in range(3):
        assert [h.category.name for h in agent.recall("快递一直没到，物流延迟")] == first


def test_llm_exception_returns_fallback_reply_not_raise():
    class Boom:
        def invoke(self, *args, **kwargs):
            raise RuntimeError("上游 500")

    agent = ProductAgent()
    agent.set_llm(Boom())

    out = agent.process({"customer_query": "手机的型号", "tools_used": []})

    assert out["response"] == agent.llm_failure_reply
    assert out["current_agent"] == agent.name


def test_agent_without_llm_does_not_crash():
    """未注入 LLM 时（例如密钥缺失）也必须返回兜底话术，不能抛异常打断整张图。"""
    agent = GeneralAgent()
    out = agent.process({"customer_query": "营业时间", "tools_used": []})
    assert out["response"] == agent.llm_failure_reply


def test_real_client_llm_returns_its_content(build_graph):
    """Sanity check：拿到真实返回对象时取 .content。"""
    llm = CountingLLM(reply="欢迎光临")
    agent = ProductAgent()
    agent.set_llm(llm)
    out = agent.process({"customer_query": "你好", "tools_used": []})
    assert out["response"] == "欢迎光临"


def test_tools_used_records_recall_size():
    agent = TechAgent()
    agent.set_llm(CountingLLM())
    state = {"customer_query": "屏幕发烫", "tools_used": []}
    agent.process(state)
    assert any(entry.startswith(f"{agent.name}_recall:") for entry in state["tools_used"])
