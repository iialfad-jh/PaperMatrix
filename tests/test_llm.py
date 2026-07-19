import sys
import types

from papermatrix.llm import OpenAILLMClient
from papermatrix.schema import FieldSpec


class FakeOpenAI:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = types.SimpleNamespace(completions=FakeChatCompletions())
        self.responses = FakeResponses()
        self.__class__.instances.append(self)


class FakeChatCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = types.SimpleNamespace(content='{"paper_id": "paper"}')
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])


class FakeResponses:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(output_text='{"paper_id": "paper"}')


def install_fake_openai(monkeypatch):
    FakeOpenAI.instances = []
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))


def test_openai_client_reads_base_url_from_environment(monkeypatch):
    install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "relay-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.dwai.cloud/v1")

    OpenAILLMClient()

    kwargs = FakeOpenAI.instances[0].kwargs
    assert kwargs["api_key"] == "relay-key"
    assert kwargs["base_url"] == "https://api.dwai.cloud/v1"
    assert kwargs["default_headers"]["Accept"] == "application/json"
    assert "Mozilla/5.0" in kwargs["default_headers"]["User-Agent"]


def test_openai_client_prefers_explicit_base_url(monkeypatch):
    install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "relay-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")

    OpenAILLMClient(base_url="https://cli.example/v1")

    kwargs = FakeOpenAI.instances[0].kwargs
    assert kwargs["api_key"] == "relay-key"
    assert kwargs["base_url"] == "https://cli.example/v1"
    assert "User-Agent" in kwargs["default_headers"]


def test_openai_client_uses_responses_api_when_selected(monkeypatch):
    install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "relay-key")
    monkeypatch.setenv("OPENAI_API_MODE", "responses")

    client = OpenAILLMClient(model="gpt-test")
    extract = client.extract_json("paper", [])

    fake_client = FakeOpenAI.instances[0]
    assert extract == {"paper_id": "paper"}
    assert fake_client.responses.calls[0]["model"] == "gpt-test"
    assert fake_client.responses.calls[0]["store"] is False
    assert fake_client.responses.calls[0]["max_output_tokens"] == 1200
    assert "字段值请用简体中文概括" in fake_client.responses.calls[0]["input"]
    assert "instructions" not in fake_client.responses.calls[0]
    assert "temperature" not in fake_client.responses.calls[0]
    assert fake_client.chat.completions.calls == []


def test_openai_client_reads_model_from_environment(monkeypatch):
    install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "relay-key")
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("PAPERMATRIX_MODEL", "gpt-5.5")

    client = OpenAILLMClient()
    client.extract_json("paper", [])

    assert FakeOpenAI.instances[0].responses.calls[0]["model"] == "gpt-5.5"


def test_openai_client_can_request_english_output(monkeypatch):
    install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "relay-key")
    monkeypatch.setenv("OPENAI_API_MODE", "responses")

    client = OpenAILLMClient(model="gpt-test", language="en")
    client.extract_json("paper", [])

    input_text = FakeOpenAI.instances[0].responses.calls[0]["input"]
    assert "Write extracted field values in English" in input_text


def test_openai_client_includes_custom_fields_in_prompt(monkeypatch):
    install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "relay-key")
    monkeypatch.setenv("OPENAI_API_MODE", "responses")

    client = OpenAILLMClient(model="gpt-test", language="en")
    client.extract_json("paper", [], field_names=["input", "output"])

    input_text = FakeOpenAI.instances[0].responses.calls[0]["input"]
    assert "- input" in input_text
    assert "- output" in input_text
    assert '"fields": {"input":' in input_text
    assert '"output":' in input_text


def test_openai_client_includes_field_descriptions_and_keywords(monkeypatch):
    install_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "relay-key")
    monkeypatch.setenv("OPENAI_API_MODE", "responses")

    client = OpenAILLMClient(model="gpt-test", language="en")
    client.extract_json(
        "paper",
        [],
        field_specs=[
            FieldSpec(
                name="crop_species",
                description="Extract the crop or plant species studied in the paper.",
                keywords=["crop", "species", "maize"],
            )
        ],
    )

    input_text = FakeOpenAI.instances[0].responses.calls[0]["input"]
    assert "crop_species: Extract the crop or plant species studied in the paper." in input_text
    assert "Keywords: crop, species, maize" in input_text
