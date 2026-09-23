"""账单专家智能体：财务与账单问题处理。"""

from .base_agent import BaseAgent


class BillingAgent(BaseAgent):
    domain_prompt = """请根据客户的账单问题提供专业的解答：
1. 仔细分析客户的具体问题
2. 提供明确的处理流程和时间预期
3. 说明需要提供的相关材料
4. 如果问题复杂，建议联系专门的财务人员

回答要准确、专业，涉及金额和时间的信息要具体明确。如果问题超出你的权限范围，请说明并建议转接给相关部门。"""

    knowledge_label = "账单政策信息"
    llm_failure_reply = "抱歉，处理您的账单问题时遇到系统错误，请稍后重试。"

    def __init__(self):
        super().__init__(
            name="账单专家",
            role="财务和账单问题处理",
            expertise=["退款处理", "发票管理", "价格计算", "支付问题"],
            knowledge_file="billing",
        )
