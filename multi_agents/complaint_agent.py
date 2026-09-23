"""投诉处理专家智能体：客户投诉与建议处理。"""

from .base_agent import BaseAgent


class ComplaintAgent(BaseAgent):
    domain_prompt = """请以专业、耐心的态度处理客户投诉：
1. 认真倾听客户的问题和不满
2. 表达理解和歉意
3. 提供具体的解决方案和时间承诺
4. 如果问题复杂，说明后续处理流程

回答要真诚、专业，体现对客户的重视。如果投诉超出你的处理权限，请说明并承诺转交给相关部门处理。"""

    knowledge_label = "投诉处理政策"
    context_closing = "请基于以上对话历史和当前查询，提供连贯的处理方案。"
    llm_failure_reply = "抱歉，处理您的投诉时遇到系统错误，请稍后重试。"

    def __init__(self):
        super().__init__(
            name="投诉处理专家",
            role="客户投诉和建议处理",
            expertise=["问题记录", "解决方案", "补偿措施", "服务改进"],
            knowledge_file="complaint",
        )
