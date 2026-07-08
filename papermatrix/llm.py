from __future__ import annotations

import json
import os
from typing import Protocol


EXTRACTION_SYSTEM_PROMPT = """You are an academic paper information extraction engine.
Use only the provided chunks.
Do not use external knowledge.
Do not guess.
If a field is not explicitly supported, return "unknown".
For every non-unknown field, provide evidence with chunk_id and pages.

Extract:
- title
- problem
- method
- dataset
- metric
- result
- limitation
"""


class LLMClient(Protocol):
    def extract_json(self, paper_id: str, chunks: list[dict]) -> dict:
        ...


class OpenAILLMClient:
    def __init__(
        self,
        model: str = "gpt-4.1-mini",
        api_key: str | None = None,
        base_url: str | None = None,
        api_mode: str | None = None,
    ) -> None:
        from openai import OpenAI

        self.model = model
        self.api_mode = (api_mode or os.getenv("OPENAI_API_MODE") or "chat").lower()
        if self.api_mode not in {"chat", "responses"}:
            raise ValueError('api_mode must be "chat" or "responses"')

        client_kwargs = {"api_key": api_key or os.getenv("OPENAI_API_KEY")}
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")
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
        }

    def extract_json(self, paper_id: str, chunks: list[dict]) -> dict:
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
        user_content = self._build_user_content(payload)
        if self.api_mode == "responses":
            content = self._extract_with_responses(user_content)
        else:
            content = self._extract_with_chat_completions(user_content)

        if not content:
            raise ValueError("LLM returned empty content")
        return json.loads(content)

    def _build_user_content(self, payload: dict) -> str:
        return (
            "Return only one valid JSON object matching this shape: "
            '{"paper_id": str, "title": str, '
            '"problem": {"value": str, "evidence": [{"chunk_id": str, "pages": [int]}]}, '
            '"method": {"value": str, "evidence": []}, '
            '"dataset": {"value": str, "evidence": []}, '
            '"metric": {"value": str, "evidence": []}, '
            '"result": {"value": str, "evidence": []}, '
            '"limitation": {"value": str, "evidence": []}}.\n\n'
            f"Input:\n{json.dumps(payload, ensure_ascii=False)}"
        )

    def _extract_with_chat_completions(self, user_content: str) -> str | None:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            store=False,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        return response.choices[0].message.content

    def _extract_with_responses(self, user_content: str) -> str | None:
        response = self.client.responses.create(
            model=self.model,
            store=False,
            max_output_tokens=1200,
            input=f"{EXTRACTION_SYSTEM_PROMPT}\n\n{user_content}",
        )
        content = getattr(response, "output_text", None)
        if content:
            return content
        return self._collect_response_text(response)

    def _collect_response_text(self, response: object) -> str | None:
        pieces = []
        for item in getattr(response, "output", []) or []:
            content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
            for part in content or []:
                text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
                if text:
                    pieces.append(text)
        return "".join(pieces) or None
