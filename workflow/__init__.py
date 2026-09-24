"""流程包：LangGraph 图定义（graph）与意图分类（classifier）。

分类器是图的固定第一跳，由代码直接调用，不暴露给 LLM 做 function calling；
图结构（节点、条件边、路由表）全部在 graph.py 显式声明。
"""
