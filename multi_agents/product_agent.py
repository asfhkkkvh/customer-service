"""产品专家智能体：产品信息咨询与选型推荐。"""

from .base_agent import BaseAgent


class ProductAgent(BaseAgent):
    domain_prompt = """请根据客户查询提供专业、详细的产品信息，包括：
- 产品规格和功能特点
- 价格区间和性价比分析
- 适用场景和用户群体
- 与竞品的对比优势

回答要专业、准确、有说服力。如果客户询问的产品不在你的知识范围内，请说明并建议联系销售代表获取最新信息。"""

    knowledge_label = "产品信息"
    llm_failure_reply = "抱歉，处理您的产品查询时遇到技术问题，请稍后重试。"

    def __init__(self):
        super().__init__(
            name="产品专家",
            role="产品信息咨询和推荐",
            expertise=["产品规格", "价格比较", "功能特点", "市场分析"],
            knowledge_file="product",
        )
