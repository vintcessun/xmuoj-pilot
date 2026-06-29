from __future__ import annotations

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from xmuoj_pilot.config import AIConfig


class AIProvider:
    def __init__(self, config: AIConfig) -> None:
        if not config.api_key:
            raise ValueError("AI API key is not configured.")
        self.config = config
        self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)

    async def explain_problem(self, problem_statement: str) -> str:
        return await self._chat(
            "请用中文解释这道算法题的题意、输入输出和关键约束，不要给出完整可提交代码。",
            problem_statement,
        )

    async def generate_solution_hint(self, problem_statement: str) -> str:
        return await self._chat(
            "请给出这道算法题的解题思路、复杂度、边界情况和容易出错的点。"
            "可以给伪代码或关键代码片段，但不要直接代替用户完成整题提交。",
            problem_statement,
        )

    async def study_problem(self, problem_statement: str) -> str:
        return await self._chat(
            "你是算法学习教练。请按以下格式输出：\n"
            "1. 题意复述\n"
            "2. 输入输出要点\n"
            "3. 解题思路\n"
            "4. 边界情况\n"
            "5. 复杂度\n"
            "6. C++ 实现提示（不要给完整可直接提交代码）\n",
            problem_statement,
        )

    async def draft_cpp_solution(self, problem_statement: str) -> str:
        return await self._chat(
            "你是严谨的 C++17 算法助教。请先简短分析题意、输出格式、边界情况和可能歧义，"
            "再给出完整可编译代码。\n"
            "要求：可以在代码块外写简短分析；必须包含一个 Markdown 代码块：\n"
            "```c++\n"
            "中间是完整可编译 C++17 代码\n"
            "```\n"
            "代码块中只能放代码。",
            problem_statement,
        )

    async def revise_cpp_solution(self, messages: list[ChatCompletionMessageParam]) -> str:
        return await self.chat(messages)

    async def chat(
        self,
        messages: list[ChatCompletionMessageParam],
        *,
        temperature: float = 0.2,
    ) -> str:
        """通用多轮对话补全，供 ReAct 循环复用同一条对话上下文。"""
        response = await self.client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    async def _chat(self, system_prompt: str, user_prompt: str) -> str:
        response = await self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content or ""
