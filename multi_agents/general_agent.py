"""综合客服智能体：一般咨询与信息查询。"""

from .base_agent import BaseAgent


class GeneralAgent(BaseAgent):
    domain_prompt = """请以友好、专业的态度处理客户的一般咨询：
1. 耐心倾听客户的问题
2. 提供准确、有用的信息
3. 如果问题超出你的专业范围，建议转接给相关专家
4. 确保客户得到满意的答复

回答要友好、专业，体现良好的服务态度。如果问题复杂或需要专业知识，请说明并建议转接给相应的专业智能体。"""

    knowledge_label = "服务信息"
    context_closing = "请基于以上对话历史和当前查询，提供连贯的咨询。"
    llm_failure_reply = "抱歉，处理您的咨询时遇到系统错误，请稍后重试。"

    def __init__(self):
        super().__init__(
            name="综合客服",
            role="一般咨询处理",
            expertise=["信息查询", "基础服务", "问题转接"],
            knowledge_file="general",
        )
