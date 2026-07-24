import os

import pytest

from papermatrix.llm import OpenAILLMClient


RUN_LLM = (
    os.getenv("PAPERMATRIX_RUN_INTEGRATION") == "1"
    and os.getenv("PAPERMATRIX_RUN_LLM_INTEGRATION") == "1"
    and bool(os.getenv("OPENAI_API_KEY"))
)


@pytest.mark.integration
@pytest.mark.skipif(
    not RUN_LLM,
    reason="set PAPERMATRIX_RUN_INTEGRATION=1, PAPERMATRIX_RUN_LLM_INTEGRATION=1, and OPENAI_API_KEY",
)
def test_real_llm_extraction():
    client = OpenAILLMClient(language="en", max_retries=2)

    result = client.extract_json(
        "integration-paper",
        [
            {
                "chunk_id": "integration-paper_c0",
                "paper_id": "integration-paper",
                "pages": [1],
                "text": "This paper studies robust retry handling for document extraction pipelines.",
            }
        ],
        field_names=["problem"],
    )

    assert result["paper_id"] == "integration-paper"
    assert "problem" in result["fields"]
