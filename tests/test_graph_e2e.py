"""
图端到端行为（注入假 LLM，离线运行，零成本）。

这里锁住三条在简历/README 里被量化的声明：
1. 单轮 **恰好 2 次** LLM 调用（分类 1 + 专家 1）
2. out_of_scope 护栏 **短路**，不进入任何业务 Agent
3. 每轮对话结构化为 **2 条** 持久化轮次（用户 + 助手）
"""

from conftest import CountingLLM


def test_single_turn_uses_exactly_two_llm_calls(build_graph):
    llm = CountingLLM(classify_label="billing", reply="已为您受理退款申请。")
    main, graph = build_graph(llm)

    out = graph.invoke({"customer_query": "我要退款", "session_id": "t1"})

    assert llm.call_count == 2, "单轮应固定为 2 次 LLM 调用（分类 + 专家）"
    assert out["query_type"] == "billing"
    assert out["current_agent"] == "账单专家"
    assert out["response"] == "已为您受理退款申请。"
    assert len(out["persisted_dialogue"]) == 2
    assert out["persisted_dialogue"][0]["is_user"] is True
    assert out["persisted_dialogue"][1]["is_user"] is False


def test_guardrail_short_circuits_before_any_business_agent(build_graph):
    llm = CountingLLM(classify_label="out_of_scope")
    main, graph = build_graph(llm)

    out = graph.invoke({"customer_query": "给我讲个故事", "session_id": "t2"})

    assert out["response"] == main.OUT_OF_SCOPE_REPLY
    assert "out_of_scope_refusal" in out["tools_used"]
    assert "账单专家_processing" not in out["tools_used"]
    assert llm.call_count == 1, "护栏分支只调用分类模型，不应再触发专家"


def test_empty_query_never_reaches_the_model(build_graph):
    llm = CountingLLM()
    main, graph = build_graph(llm)

    out = graph.invoke({"customer_query": "   ", "session_id": "t3"})

    assert llm.call_count == 0
    assert out["query_type"] == main.EMPTY_QUERY_LABEL
    assert out["response"]


def test_multi_turn_accumulates_dialogue(build_graph):
    """同一线程连跑两轮，持久化轮次应累加到 4 条（图本身不负责跨进程持久化，
    这里只验证状态内的轮次累加语义）。"""
    llm = CountingLLM(classify_label="product_info")
    main, graph = build_graph(llm)

    first = graph.invoke({"customer_query": "手机有什么型号", "session_id": "t4"})
    assert len(first["persisted_dialogue"]) == 2

    # 把上一轮状态喂回去，模拟 checkpointer 恢复
    second = graph.invoke({**first, "customer_query": "那耳机呢"}, config=None)
    assert len(second["persisted_dialogue"]) == 4
    assert llm.call_count == 4


def test_second_turn_sees_previous_turns_in_prompt(build_graph):
    """多轮的第二轮必须把历史拼进 prompt——否则"上下文感知"是假的。"""
    llm = CountingLLM(classify_label="product_info")
    main, graph = build_graph(llm)

    first = graph.invoke({"customer_query": "手机有什么型号", "session_id": "t5"})
    graph.invoke({**first, "customer_query": "那耳机呢"})

    expert_call = llm.calls[-1]
    joined = "\n".join(str(m.content) for m in expert_call)
    assert "手机有什么型号" in joined, "第二轮 prompt 未包含第一轮的用户提问"
