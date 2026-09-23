"""
本地召回层。

设计意图：把「领域知识」从 Agent 代码里剥离，Agent 只依赖 recall() / render()
两个接口。当前实现是静态 JSON 数据源 + 关键词打分，替换成向量库或业务 API
时不需要改动任何 Agent。

关键词打分是刻意保留的确定性方案：召回结果可复现、可单测、零额外成本，
对本项目"分类已由 LLM 完成、领域内候选条目只有个位数"的场景足够；
规模变大或需要语义泛化时再换向量检索即可。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "knowledge"

#: 同一知识库只加载一次（Agent 实例可能被反复创建）
_CACHE: Dict[str, "KnowledgeBase"] = {}


@dataclass(frozen=True)
class Category:
    """一个知识类目，例如「退款政策」。"""

    name: str
    keywords: Tuple[str, ...]
    items: Dict[str, str]

    def score(self, query_lower: str) -> int:
        """类目命中关键词的个数；0 表示不相关。"""
        return sum(1 for kw in self.keywords if kw.lower() in query_lower)


@dataclass(frozen=True)
class RecallHit:
    category: Category
    score: int


class KnowledgeBase:
    """领域知识库：关键词召回 + 片段渲染。"""

    def __init__(self, name: str, categories: Sequence[Category]):
        self.name = name
        self.categories: Tuple[Category, ...] = tuple(categories)

    # --- 构造 ---------------------------------------------------------------

    @classmethod
    def load(cls, name: str) -> "KnowledgeBase":
        """按名字加载 data/knowledge/<name>.json，结果带缓存。"""
        if name in _CACHE:
            return _CACHE[name]

        path = DATA_DIR / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"知识库文件不存在: {path}")

        raw = json.loads(path.read_text(encoding="utf-8"))
        categories = [
            Category(
                name=item["name"],
                keywords=tuple(item.get("keywords", ())),
                items=dict(item.get("items", {})),
            )
            for item in raw.get("categories", [])
        ]
        kb = cls(raw.get("name", name), categories)
        _CACHE[name] = kb
        return kb

    # --- 召回 ---------------------------------------------------------------

    def recall(self, query: str, top_n: int = 3) -> List[RecallHit]:
        """
        返回命中的类目，按命中关键词数降序；命中数相同时按配置顺序，
        保证结果稳定可复现。无命中时返回空列表——**不做全库兜底**。
        """
        query_lower = (query or "").lower()
        scored: List[Tuple[int, int, Category]] = []
        for idx, category in enumerate(self.categories):
            hit = category.score(query_lower)
            if hit > 0:
                scored.append((hit, idx, category))

        scored.sort(key=lambda row: (-row[0], row[1]))
        return [RecallHit(category=cat, score=score) for score, _, cat in scored[:top_n]]

    @staticmethod
    def render(hits: Sequence[RecallHit], max_items: int = 4) -> str:
        """把召回结果渲染成注入 prompt 的文本片段。"""
        blocks: List[str] = []
        for hit in hits:
            lines = [f"【{hit.category.name}】"]
            for i, (key, value) in enumerate(hit.category.items.items()):
                if i >= max_items:
                    lines.append("…")
                    break
                lines.append(f"• {key}：{value}")
            blocks.append("\n".join(lines))
        return "\n".join(blocks)

    @property
    def category_names(self) -> List[str]:
        return [c.name for c in self.categories]
