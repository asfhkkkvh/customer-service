"""
多智能体客服系统 —— LangGraph 工作流定义。

图结构（节点与边均在此文件显式声明）：

    classify_query ──┬─ product_info ──────→ product_agent ──→ END
                     ├─ technical_support ─→ tech_agent ─────→ END
                     ├─ billing ───────────→ billing_agent ──→ END
                     ├─ complaint ─────────→ complaint_agent → END
                     ├─ general_inquiry ───→ general_agent ──→ END
                     └─ out_of_scope ──────→ END（护栏，不调用业务 Agent）

`langgraph.json` 的作用是声明平台部署入口（本文件 + make_graph），
图结构本身由代码定义。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.config import get_config
from langgraph.graph import END, StateGraph

load_dotenv()

import config as _config  # noqa: E402
from multi_agents import (  # noqa: E402
    BillingAgent,
    ComplaintAgent,
    GeneralAgent,
    ProductAgent,
    TechAgent,
)
from workflow.classifier import CLASS_LABELS, classify_query  # noqa: E402

logger = logging.getLogger(__name__)

# 超出客服范围时的固定回复（护栏：不调用业务智能体）
OUT_OF_SCOPE_REPLY = (
    "抱歉，这里是智能客服，仅处理与产品、技术、账单、投诉及相关售后政策类问题；"
    "请用一句话说明您的具体业务诉求，我很乐意协助。"
)

#: 空查询的内部终态标签。注意：它**不是**分类器标签，
#: 只用于让空输入短路退出，不进入业务 Agent。
EMPTY_QUERY_LABEL = "empty_query"


class AgentState(TypedDict, total=False):
    """图状态。除 customer_query 外均可缺省，由 classify 节点补齐。"""

    session_id: str
    messages: List[Any]
    current_agent: str
    customer_query: str
    query_type: str
    response: str
    tools_used: List[str]
    next_agent: str
    conversation_history: List[Any]
    #: 由平台 checkpointer 持久化，跨进程续聊时用于重建上下文
    persisted_dialogue: List[Any]


# ---------------------------------------------------------------------------
# LLM 客户端（OpenAI 兼容规范，见 config.py）
# ---------------------------------------------------------------------------

_llm_instance = None


def initialize_llm_client() -> ChatOpenAI:
    """构建 OpenAI 兼容 API 客户端。"""
    if not _config.OPENAI_API_KEY:
        raise ValueError("API密钥未设置")

    return ChatOpenAI(
        model=_config.OPENAI_MODEL,
        api_key=_config.OPENAI_API_KEY,
        base_url=_config.OPENAI_BASE_URL,
        timeout=_config.HTTP_TIMEOUT,
        max_retries=_config.HTTP_MAX_RETRIES,
    )


def get_llm():
    """获取 LLM 实例（延迟初始化并缓存；失败返回 None，由各 Agent 兜底）。"""
    global _llm_instance
    if _llm_instance is None:
        if not _config.OPENAI_API_KEY:
            logger.error("API密钥未设置，无法初始化 LLM")
        else:
            try:
                _llm_instance = initialize_llm_client()
                logger.info("LLM 客户端初始化完成: %s", _config.OPENAI_MODEL)
            except Exception as exc:
                logger.error("初始化 LLM 客户端失败: %s", exc)
    return _llm_instance


# ---------------------------------------------------------------------------
# 智能体实例（模块级缓存；图节点会被反复执行，不应每次重建）
# ---------------------------------------------------------------------------

_AGENTS: Dict[str, Any] = {}

AGENT_FACTORIES = {
    "product_agent": ProductAgent,
    "tech_agent": TechAgent,
    "billing_agent": BillingAgent,
    "complaint_agent": ComplaintAgent,
    "general_agent": GeneralAgent,
}


def initialize_agents() -> Dict[str, Any]:
    """构建并缓存所有智能体实例。"""
    if not _AGENTS:
        _AGENTS.update({name: factory() for name, factory in AGENT_FACTORIES.items()})
    return _AGENTS


def _bind_llm() -> None:
    """把当前 LLM 注入所有 Agent。在节点内调用，便于测试时替换 get_llm。"""
    llm = get_llm()
    for agent in initialize_agents().values():
        agent.set_llm(llm)


# ---------------------------------------------------------------------------
# 路由表：分类标签 → 图节点（路由的唯一事实来源）
# 与 workflow.classifier.CLASS_LABELS 的一致性由 tests/test_routing.py 保证。
# ---------------------------------------------------------------------------

ROUTE_TARGETS: Dict[str, Any] = {
    "product_info": "product_agent",
    "technical_support": "tech_agent",
    "billing": "billing_agent",
    "complaint": "complaint_agent",
    "general_inquiry": "general_agent",
    "out_of_scope": END,  # 护栏：直接结束，回复已在 classify 节点写入
    EMPTY_QUERY_LABEL: END,
}

#: 需要加入图作为节点的专家 Agent。
#: 注意：不能用 ROUTE_TARGETS 的值去推断——END 在 langgraph 里是字符串 "__end__"，
#: isinstance(..., str) 会把它误判成节点名。
AGENT_NODES: List[str] = list(AGENT_FACTORIES)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _append_turn(state: AgentState, content: str, is_user: bool) -> None:
    """把一个对话轮次追加到由 checkpointer 持久化的列表。"""
    dialogue = list(state.get("persisted_dialogue") or [])
    dialogue.append({"content": str(content), "is_user": is_user, "timestamp": _now()})
    state["persisted_dialogue"] = dialogue


def _ensure_state_defaults(state: AgentState) -> None:
    for key, default in (
        ("tools_used", []),
        ("conversation_history", []),
        ("persisted_dialogue", []),
        ("messages", []),
        ("next_agent", ""),
    ):
        if state.get(key) is None:
            state[key] = default  # type: ignore[literal-required]


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------


def classify_query_node(state: AgentState) -> AgentState:
    """分类节点：绑定会话、判定查询类型、写用户轮次、执行越界护栏。"""
    try:
        cfg = get_config()
        thread_id = (cfg.get("configurable") or {}).get("thread_id")
        if thread_id:
            state["session_id"] = str(thread_id)
    except RuntimeError:
        # 脱离 LangGraph 运行时（例如单测直接调用）时 get_config 会抛错，忽略即可
        pass

    _ensure_state_defaults(state)
    if not state.get("session_id"):
        state["session_id"] = str(uuid.uuid4())

    customer_query = (state.get("customer_query") or "").strip()

    if not customer_query:
        state["query_type"] = EMPTY_QUERY_LABEL
        state["response"] = "请描述一下您遇到的问题，我会尽力帮您处理。"
        state["current_agent"] = "智能客服"
        state["tools_used"].append("empty_query_guard")
        _append_turn(state, state["response"], is_user=False)
        return state

    state["customer_query"] = customer_query
    # classify_query 内部已做异常兜底，这里不再重复 try/except
    state["query_type"] = classify_query(customer_query, get_llm())
    state["tools_used"].append("query_classification")
    _append_turn(state, customer_query, is_user=True)

    # 护栏：超出范围直接固定回复，不进入业务智能体
    if state["query_type"] == "out_of_scope":
        state["response"] = OUT_OF_SCOPE_REPLY
        state["current_agent"] = "智能客服"
        state["tools_used"].append("out_of_scope_refusal")
        _append_turn(state, OUT_OF_SCOPE_REPLY, is_user=False)

    return state


def create_agent_node(agent_name: str):
    """创建专家 Agent 处理节点。"""

    def agent_node(state: AgentState) -> AgentState:
        _bind_llm()
        _ensure_state_defaults(state)

        agent = initialize_agents().get(agent_name)
        if agent is None:
            logger.error("未找到智能体 %s", agent_name)
            state["response"] = "抱歉，服务暂时不可用，请稍后重试。"
            return state

        # 供前端/解析层读取的对话历史快照
        state["conversation_history"] = list(state.get("persisted_dialogue") or [])

        result = agent.process(state)
        if not isinstance(result, dict):
            logger.error("智能体 %s 返回了非 dict 结果: %s", agent_name, type(result))
            state["response"] = "抱歉，处理您的请求时出现异常，请稍后重试。"
            result = state

        if not result.get("response"):
            logger.error("智能体 %s 的结果缺少 response 字段", agent_name)
            result["response"] = "抱歉，处理您的请求时出现异常，请稍后重试。"

        # 助手轮次写入 checkpointer 状态
        _append_turn(result, result["response"], is_user=False)
        return result

    return agent_node


# ---------------------------------------------------------------------------
# 图
# ---------------------------------------------------------------------------


def make_graph():
    """构建 LangGraph 工作流图。"""
    workflow = StateGraph(AgentState)

    workflow.add_node("classify_query", classify_query_node)
    for node in AGENT_NODES:
        workflow.add_node(node, create_agent_node(node))

    workflow.set_entry_point("classify_query")

    # 条件边：按分类标签单分支分发
    workflow.add_conditional_edges(
        "classify_query",
        lambda state: state.get("query_type") or "general_inquiry",
        ROUTE_TARGETS,
    )

    # 各智能体处理后直接结束：回复已写入 state["response"] 与 persisted_dialogue，
    # 无需额外的最终响应节点（避免给回复添加前后缀污染展示文本）
    for node in AGENT_NODES:
        workflow.add_edge(node, END)

    app = workflow.compile()
    logger.info("LangGraph 工作流图构建完成")
    return app


if __name__ == "__main__":
    # 注意：本文件移入 workflow/ 后，必须在项目根目录以模块方式运行：
    #   python -m workflow.graph
    # 直接 python workflow/graph.py 会导致 sys.path[0] 指向 workflow/，包内相对导入失败。
    logging.basicConfig(level=_config.LOG_CONFIG["level"], format=_config.LOG_CONFIG["format"])
    graph = make_graph()
    print("图结构自检：")
    print(f"  节点: {sorted(graph.get_graph().nodes)}")
    print(f"  入口: classify_query → 条件路由 {len(ROUTE_TARGETS)} 个分支")
    print(f"  路由表: { {k: v for k, v in ROUTE_TARGETS.items()} }")
    assert set(ROUTE_TARGETS) - {EMPTY_QUERY_LABEL} == set(CLASS_LABELS), (
        "路由表与分类标签集不一致"
    )
    print("✅ 路由表与分类标签集一致")
    print("🚀 多智能体客服系统准备就绪（依赖 langgraph dev 提供持久化）")
