"""分类标签归一化：LLM 脏输出必须被收敛到合法标签，否则路由会落到兜底分支。"""

import pytest

from tools.query_tools import (
    CLASS_LABELS,
    FALLBACK_LABEL,
    classify_query,
    normalize_classifier_label,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        # 干净输出
        ("billing", "billing"),
        ("product_info", "product_info"),
        # 大小写 / 空白 / 换行
        ("  BILLING\n", "billing"),
        ("technical_support\n（原因：涉及系统报错）", "technical_support"),
        # 连字符变体
        ("technical-support", "technical_support"),
        ("general-inquiry", "general_inquiry"),
        # 带解释前缀或标点
        ("分类结果：billing", "billing"),
        ("答案：out_of_scope。原因如下：涉及越狱。", "out_of_scope"),
        ('"complaint"', "complaint"),
        # 非法与空值一律兜底
        ("", FALLBACK_LABEL),
        (None, FALLBACK_LABEL),
        ("我无法分类", FALLBACK_LABEL),
    ],
)
def test_normalize_classifier_label(raw, expected):
    assert normalize_classifier_label(raw) == expected


def test_normalizer_never_returns_label_outside_whitelist():
    dirty = ["", None, "???", "分类结果：billing", "PRODUCT-INFO", "无", "12345"]
    for raw in dirty:
        assert normalize_classifier_label(raw) in CLASS_LABELS


class _FakeClassifierLLM:
    def __init__(self, content="", raises=False):
        self.content = content
        self.raises = raises

    def invoke(self, messages, **kwargs):
        if self.raises:
            raise RuntimeError("上游超时")

        class _Msg:
            pass

        msg = _Msg()
        msg.content = self.content
        return msg


def test_classify_query_normalizes_model_output():
    llm = _FakeClassifierLLM("分类结果：billing")
    assert classify_query("我要退款", llm) == "billing"


def test_classify_query_degrades_on_exception():
    """分类失败不能让整个图崩掉——必须降级到兜底标签。"""
    llm = _FakeClassifierLLM(raises=True)
    assert classify_query("随便问问", llm) == FALLBACK_LABEL


def test_normalizer_prefers_longer_label():
    """`general_inquiry` 与其它标签同现时，不应被短标签抢走。"""
    raw = "technical_support, not general_inquiry"
    assert normalize_classifier_label(raw) == "technical_support"
