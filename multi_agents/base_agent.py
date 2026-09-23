"""
基础智能体类。

所有专家 Agent 共享同一条处理模板：

    读持久化对话 → 本地召回 → 拼消息（上下文 / 系统提示 / 知识片段） → 调 LLM → 写回状态

子类不再各自实现 process，只声明元信息、领域提示词、知识库名和兜底话术。
新增一个专家只需要十几行。
"""

from __future__ import annotations

import logging
from abc import ABC
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from .knowledge import KnowledgeBase, RecallHit

logger = logging.getLogger(__name__)

#: 拼接在 system prompt 末尾的上下文使用说明
CONTEXT_INSTRUCTION = """

重要：请结合对话历史上下文，理解客户之前的问题和需求，提供连贯、个性化的回答。
如果这是多轮对话，请参考之前的对话内容，避免重复信息，并基于客户的新问题提供补充信息。
保持对话的连贯性和自然性，让客户感受到你理解他们的完整需求。"""


class BaseAgent(ABC):
    """专家 Agent 基类：统一 process 模板，子类只声明领域内容。"""

    # --- 子类覆盖点 ---------------------------------------------------------

    #: 领域指令，拼进 system prompt
    domain_prompt: str = ""
    #: 知识片段注入消息时使用的标题，例如「产品信息」
    knowledge_label: str = "领域知识"
    #: 对话历史与当前查询之间的衔接语
    context_closing: str = "请基于以上对话历史和当前查询，提供连贯、准确的回答。"
    #: LLM 调用失败时的兜底回复
    llm_failure_reply: str = "抱歉，处理您的问题时遇到系统错误，请稍后重试。"
    #: 召回的类目数量上限
    recall_top_n: int = 3
    #: 每个类目最多注入多少条明细
    recall_max_items: int = 4

    def __init__(
        self,
        name: str,
        role: str,
        expertise: Sequence[str],
        knowledge_file: Optional[str] = None,
    ):
        self.name = name
        self.role = role
        self.expertise: List[str] = list(expertise)
        self.llm = None  # 运行时注入
        self.knowledge: Optional[KnowledgeBase] = (
            KnowledgeBase.load(knowledge_file) if knowledge_file else None
        )

    # --- 运行时注入 ---------------------------------------------------------

    def set_llm(self, llm: Any) -> None:
        """注入 LLM 客户端（测试时可替换为假实现）。"""
        self.llm = llm

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "expertise": self.expertise,
            "knowledge_categories": (
                self.knowledge.category_names if self.knowledge else []
            ),
        }

    # --- 处理模板 -----------------------------------------------------------

    def process(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """处理一轮客户查询。子类通常不需要覆盖。"""
        query = state.get("customer_query", "") or ""
        hits = self.recall(query)

        messages = self._build_messages(state, query, hits)
        state["response"] = self._invoke_llm(messages)
        state["current_agent"] = self.name

        tools_used = state.setdefault("tools_used", [])
        tools_used.append(f"{self.name}_processing")
        if self.knowledge is not None:
            tools_used.append(f"{self.name}_recall:{len(hits)}")

        return state

    def recall(self, query: str) -> List[RecallHit]:
        """本地召回。未配置知识库时返回空列表。"""
        if self.knowledge is None:
            return []
        return self.knowledge.recall(query, top_n=self.recall_top_n)

    # --- 内部实现 -----------------------------------------------------------

    def _system_prompt(self) -> str:
        head = (
            f"你是{self.name}，专门负责{self.role}。\n"
            f"你的专业领域包括：{', '.join(self.expertise)}"
        )
        return f"{head}\n\n{self.domain_prompt}{CONTEXT_INSTRUCTION}"

    def _build_messages(
        self,
        state: Dict[str, Any],
        query: str,
        hits: Sequence[RecallHit],
    ) -> List[BaseMessage]:
        messages: List[BaseMessage] = []

        conversation_context = self._get_conversation_context(state)
        if conversation_context:
            messages.append(
                SystemMessage(
                    content=(
                        f"对话历史上下文：\n{conversation_context}\n\n"
                        f"{self.context_closing}"
                    )
                )
            )

        messages.append(SystemMessage(content=self._system_prompt()))

        if hits and self.knowledge is not None:
            knowledge_text = self.knowledge.render(hits, max_items=self.recall_max_items)
            messages.append(
                HumanMessage(
                    content=f"{self.knowledge_label}：\n{knowledge_text}\n\n"
                    f"当前查询：{query}"
                )
            )
        else:
            messages.append(HumanMessage(content=query))

        return messages

    def _invoke_llm(self, messages: Sequence[BaseMessage]) -> str:
        if self.llm is None:
            logger.error("%s 未注入 LLM", self.name)
            return self.llm_failure_reply
        try:
            response = self.llm.invoke(list(messages))
            return getattr(response, "content", "") or self.llm_failure_reply
        except Exception as exc:  # 单个 Agent 失败不应中断整个图
            logger.error("%s 调用 LLM 失败: %s", self.name, exc)
            return self.llm_failure_reply

    def _get_conversation_context(
        self,
        state: Optional[Dict[str, Any]] = None,
        max_messages: int = 12,
    ) -> str:
        """读取由 checkpointer 持久化的最近若干轮对话。"""
        if state is None:
            return ""
        records = state.get("persisted_dialogue")
        if not records:
            return ""
        lines = []
        for msg in records[-max_messages:]:
            role = "用户" if msg.get("is_user", True) else "AI"
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")
            lines.append(f"[{timestamp}] {role}: {content}")
        return "\n".join(lines)

    def _enhance_system_prompt_with_context(self, base_prompt: str) -> str:
        """保留以兼容旧调用方；新代码请直接用 _system_prompt()。"""
        return base_prompt + CONTEXT_INSTRUCTION
