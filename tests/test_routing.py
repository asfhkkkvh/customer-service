"""路由表与分类标签集的一致性。

这类「两个地方各写一份常量」的一致性问题项目里最容易悄悄失配，
而且失配后表现为"某类查询静默走到兜底"，很难发现——所以必须由测试守住。
"""

from conftest import node_ids

from workflow.classifier import CLASS_LABELS


def test_route_table_covers_every_classifier_label():
    from workflow.graph import EMPTY_QUERY_LABEL, ROUTE_TARGETS

    assert set(ROUTE_TARGETS) - {EMPTY_QUERY_LABEL} == set(CLASS_LABELS), (
        "路由表与分类标签集不一致：新增标签后必须同步 ROUTE_TARGETS"
    )


def test_empty_query_label_is_not_a_classifier_label():
    """空查询是内部终态，不应混进分类器标签集。"""
    from workflow.graph import EMPTY_QUERY_LABEL

    assert EMPTY_QUERY_LABEL not in CLASS_LABELS


def test_graph_contains_entry_and_all_agent_nodes():
    from workflow.graph import AGENT_NODES, make_graph

    ids = node_ids(make_graph())
    assert "classify_query" in ids, "图缺少分类入口节点"
    for node in AGENT_NODES:
        assert node in ids, f"路由表声明了 {node} 但图里没有该节点"


def test_graph_is_deterministic():
    """同样输入两次构建出的图结构应一致。"""
    from workflow.graph import make_graph

    assert node_ids(make_graph()) == node_ids(make_graph())
