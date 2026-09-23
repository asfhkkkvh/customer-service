"""pytest 公共夹具：路径注入、requests 假响应、可计数的假 LLM。"""

import json
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class FakeResponse:
    """最小 requests.Response 替身。"""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.text = json.dumps(self._payload, ensure_ascii=False)

    def json(self):
        return self._payload


class CountingLLM:
    """
    记录每次调用的消息列表的假 LLM。

    用它来验证「单轮固定 2 次 LLM 调用」这类量化声明——
    这类声明只有数出来才算验证过。
    """

    #: 分类节点的 system prompt 里有这个特征词，用它区分分类调用与专家调用
    CLASSIFIER_MARKER = "查询分类专家"

    def __init__(self, classify_label="general_inquiry", reply="已为您处理。"):
        self.classify_label = classify_label
        self.reply = reply
        self.calls = []

    def invoke(self, messages, **kwargs):
        messages = list(messages)
        self.calls.append(messages)
        joined = "\n".join(str(getattr(m, "content", "")) for m in messages)
        if self.CLASSIFIER_MARKER in joined:
            return AIMessage(content=self.classify_label)
        return AIMessage(content=self.reply)

    @property
    def call_count(self):
        return len(self.calls)


@pytest.fixture
def fake_llm():
    return CountingLLM()


@pytest.fixture
def build_graph(monkeypatch):
    """返回一个构造器：传入假 LLM，得到 (主模块, 已编译的图)。"""
    def _build(llm):
        import multi_agent_customer_service as main
        monkeypatch.setattr(main, "get_llm", lambda: llm)
        return main, main.make_graph()

    return _build


def node_ids(graph):
    """兼容不同 langgraph 版本：图节点集合可能是 dict 或可迭代对象。"""
    nodes = graph.get_graph().nodes
    if isinstance(nodes, dict):
        return set(nodes.keys())
    return {n if isinstance(n, str) else getattr(n, "id", str(n)) for n in nodes}
