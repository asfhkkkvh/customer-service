"""技术支持专家智能体：技术问题诊断与排查。"""

from .base_agent import BaseAgent


class TechAgent(BaseAgent):
    domain_prompt = """请根据客户的技术问题提供专业的解决方案：
1. 仔细分析问题的技术细节
2. 提供清晰的解决步骤
3. 说明可能的原因和预防措施
4. 如果问题复杂，建议联系专业技术人员

回答要专业、准确，技术术语要通俗易懂。如果问题超出你的专业范围，请说明并建议转接给相应的技术专家。"""

    knowledge_label = "技术解决方案"
    llm_failure_reply = "抱歉，处理您的技术问题时遇到系统错误，请稍后重试。"

    def __init__(self):
        super().__init__(
            name="技术支持专家",
            role="技术问题诊断和解决",
            expertise=["故障诊断", "系统优化", "软件配置", "硬件维修"],
            knowledge_file="tech",
        )
