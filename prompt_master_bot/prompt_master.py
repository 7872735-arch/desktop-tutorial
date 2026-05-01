import re
import anthropic
from typing import AsyncIterator

from storage import Prompt


_VAR_RE = re.compile(r"\{(\w+)\}")


def extract_variables(template: str) -> list[str]:
    return list(dict.fromkeys(_VAR_RE.findall(template)))


def render(template: str, variables: dict[str, str]) -> str:
    def replacer(m: re.Match) -> str:
        return variables.get(m.group(1), m.group(0))
    return _VAR_RE.sub(replacer, template)


def build_messages(prompt: Prompt, user_input: str, variables: dict[str, str]) -> list[dict]:
    system = render(prompt.template, variables)
    return [
        {
            "role": "user",
            "content": user_input,
        }
    ], system


async def ask_claude(
    client: anthropic.AsyncAnthropic,
    system: str,
    messages: list[dict],
    model: str = "claude-sonnet-4-6",
) -> AsyncIterator[str]:
    # Use prompt caching for the system prompt to reduce costs on repeated calls
    async with client.messages.stream(
        model=model,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text


DEFAULT_PROMPTS: list[Prompt] = [
    Prompt(
        name="translate-zh",
        template="你是一位專業翻譯，將使用者的文字翻譯成繁體中文，保持原意並使用自然流暢的語氣。",
        description="繁體中文翻譯",
        category="language",
    ),
    Prompt(
        name="code-review",
        template=(
            "You are a senior {language} engineer conducting a thorough code review. "
            "Focus on: correctness, performance, security, and readability. "
            "Be concise and actionable."
        ),
        description="Code review assistant (supports {language} variable)",
        category="coding",
    ),
    Prompt(
        name="summarize",
        template=(
            "You are an expert at summarizing content. "
            "Provide a clear, structured summary in {format} format. "
            "Highlight key points, decisions, and action items."
        ),
        description="Summarize content (supports {format} variable)",
        category="writing",
    ),
    Prompt(
        name="brainstorm",
        template=(
            "You are a creative brainstorming partner. "
            "Generate diverse, innovative ideas for the given topic. "
            "Present ideas as a numbered list with a one-line explanation each."
        ),
        description="Creative brainstorming",
        category="writing",
    ),
    Prompt(
        name="explain-simple",
        template=(
            "You are an expert teacher. Explain concepts simply, "
            "as if talking to a {audience}. Use analogies and concrete examples."
        ),
        description="Simple explanation (supports {audience} variable)",
        category="education",
    ),
]
