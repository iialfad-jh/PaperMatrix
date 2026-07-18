from __future__ import annotations

import json
import os
from typing import Protocol

from .schema import DEFAULT_FIELD_NAMES


EXTRACTION_SYSTEM_PROMPT = """You are an academic paper information extraction engine.
Use only the provided chunks.
Do not use external knowledge.
Do not guess.
If a field is not explicitly supported, return "unknown".
For every non-unknown field, provide evidence with chunk_id and pages.
"""
LANGUAGE_ALIASES = {
    "zh": "zh",
    "cn": "zh",
    "zh-cn": "zh",
    "chinese": "zh",
    "en": "en",
    "english": "en",
}
LANGUAGE_OUTPUT_INSTRUCTIONS = {
    "en": "Write extracted field values in English. Keep names of datasets, metrics, and methods as written when they are proper nouns.",
    "zh": "除数据集、指标、模型名等专有名词可保留原文外，字段值请用简体中文概括。缺失字段必须仍然返回字符串 \"unknown\"。",
}
DEFAULT_MODEL = "gpt-4.1-mini"


def normalize_language(language: str) -> str:
    normalized = LANGUAGE_ALIASES.get(language.strip().lower())
    if not normalized:
        raise ValueError('language must be "zh" or "en"')
    return normalized


def resolve_openai_config(
    model: str | None = None,
    base_url: str | None = None,
    api_mode: str | None = None,
    language: str = "zh",
) -> dict[str, str]:
    resolved_api_mode = (api_mode or os.getenv("OPENAI_API_MODE") or "chat").lower()
    if resolved_api_mode not in {"chat", "responses"}:
        raise ValueError('api_mode must be "chat" or "responses"')
    return {
        "model": model or os.getenv("PAPERMATRIX_MODEL") or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL,
        "api_mode": resolved_api_mode,
        "base_url": base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE") or "",
        "language": normalize_language(language),
    }


class LLMClient(Protocol):
    def extract_json(self, paper_id: str, chunks: list[dict], field_names: list[str] | None = None) -> dict:
        ...


class OpenAILLMClient:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        api_mode: str | None = None,
        language: str = "zh",
    ) -> None:
        from openai import OpenAI

        config = resolve_openai_config(model=model, base_url=base_url, api_mode=api_mode, language=language)
        self.model = config["model"]
        self.api_mode = config["api_mode"]
        self.language = config["language"]

        client_kwargs = {"api_key": api_key or os.getenv("OPENAI_API_KEY")}
        self.base_url = config["base_url"]
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
            client_kwargs["default_headers"] = {
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }
        self.client = OpenAI(**client_kwargs)

    def config_summary(self) -> dict[str, str]:
        return {
            "model": self.model,
            "api_mode": self.api_mode,
            "base_url": self.base_url or "OpenAI default",
            "language": self.language,
        }

    def extract_json(self, paper_id: str, chunks: list[dict], field_names: list[str] | None = None) -> dict:
        field_names = field_names or list(DEFAULT_FIELD_NAMES)
        payload = {
            "paper_id": paper_id,
            "chunks": [
                {
                    "chunk_id": chunk["chunk_id"],
                    "pages": chunk["pages"],
                    "text": chunk["text"],
                }
                for chunk in chunks
            ],
        }
        user_content = self._build_user_content(payload, field_names=field_names)
        if self.api_mode == "responses":
            content = self._extract_with_responses(user_content, field_names=field_names)
        else:
            content = self._extract_with_chat_completions(user_content, field_names=field_names)

        if not content:
            raise ValueError("LLM returned empty content")
        return json.loads(content)

    def _build_user_content(self, payload: dict, field_names: list[str]) -> str:
        field_shape = {
            field_name: {"value": "str", "evidence": [{"chunk_id": "str", "pages": ["int"]}]}
            for field_name in field_names
        }
        return (
            f"{LANGUAGE_OUTPUT_INSTRUCTIONS[self.language]}\n\n"
            "Extract the paper title and these fields:\n"
            + "\n".join(f"- {field_name}" for field_name in field_names)
            + "\n\n"
            "Return only one valid JSON object matching this shape: "
            '{"paper_id": str, "title": str, "fields": '
            f"{json.dumps(field_shape, ensure_ascii=False)}"
            "}.\n\n"
            f"Input:\n{json.dumps(payload, ensure_ascii=False)}"
        )

    def _extract_with_chat_completions(self, user_content: str, field_names: list[str]) -> str | None:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            store=False,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self._build_system_prompt(field_names)},
                {"role": "user", "content": user_content},
            ],
        )
        return response.choices[0].message.content

    def _extract_with_responses(self, user_content: str, field_names: list[str]) -> str | None:
        response = self.client.responses.create(
            model=self.model,
            store=False,
            max_output_tokens=1200,
            input=f"{self._build_system_prompt(field_names)}\n\n{user_content}",
        )
        content = getattr(response, "output_text", None)
        if content:
            return content
        return self._collect_response_text(response)

    def _build_system_prompt(self, field_names: list[str]) -> str:
        return EXTRACTION_SYSTEM_PROMPT + "\n\nExtract:\n- title\n" + "\n".join(f"- {field_name}" for field_name in field_names)

    def _collect_response_text(self, response: object) -> str | None:
        pieces = []
        for item in getattr(response, "output", []) or []:
            content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
            for part in content or []:
                text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
                if text:
                    pieces.append(text)
        return "".join(pieces) or None
