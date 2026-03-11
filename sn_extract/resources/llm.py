# from langchain_openai import ChatOpenAI

# def get_llm(
#     temperature: float = 0.0,
#     model: str = "gpt-4o",
# ):
#     """
#     Central LLM factory.
#     All nodes MUST use this.
#     """
#     return ChatOpenAI(
#         model=model,
#         temperature=temperature,
#     )


# ── WAIP (Wipro AI Platform) integration ───────────────────────────
# Uncomment the class below and swap get_llm() to use WaipChatModel
# when ready to route all LLM calls through the Wipro API gateway.
#
import os
import json
import requests
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    BaseMessage, AIMessage, HumanMessage, SystemMessage,
)
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.runnables import RunnableLambda
from pydantic import Field
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv(override=True)


class WaipChatModel(BaseChatModel):
    """LangChain chat model that routes all calls through the Wipro AI Platform (WAIP) gateway."""

    model_name: str = "gpt-4o"
    temperature: float = 0.0
    max_output_tokens: int = 4096
    waip_api_key: str = Field(default="")
    waip_base_url: str = Field(default="")
    verify_ssl: bool = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.waip_api_key:
            self.waip_api_key = os.getenv("WAIP_API_KEY", "")
        if not self.waip_base_url:
            self.waip_base_url = os.getenv("WAIP_API_ENDPOINT", "")
        self.waip_base_url = self.waip_base_url.rstrip("/")
        if not self.waip_api_key:
            raise ValueError("WAIP_API_KEY not found — add it to .env")
        if not self.waip_base_url:
            raise ValueError("WAIP_API_ENDPOINT not found — add it to .env")

    @property
    def _llm_type(self) -> str:
        return "waip-chat"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "temperature": self.temperature,
            "waip_base_url": self.waip_base_url,
        }

    def _format_messages(self, messages: List[BaseMessage]) -> List[Dict]:
        """WAIP completion endpoint does not accept role 'system'.
        Fold any system messages into the first user message as a preamble."""
        system_parts = []
        formatted = []

        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_parts.append(msg.content)
            elif isinstance(msg, AIMessage):
                formatted.append({"content": msg.content, "role": "assistant"})
            else:
                formatted.append({"content": msg.content, "role": "user"})

        if system_parts and formatted:
            preamble = "\n".join(system_parts)
            first = formatted[0]
            first["content"] = f"{preamble}\n\n{first['content']}"

        return formatted

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        url = f"{self.waip_base_url}/v1.1/skills/completion/query"

        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
            "Authorization": f"Bearer {self.waip_api_key}",
        }

        payload = {
            "messages": self._format_messages(messages),
            "skill_parameters": {
                "model_name": self.model_name,
                "emb_type": "openai",
                "max_output_tokens": self.max_output_tokens,
            },
            "stream_response": False,
        }

        response = requests.post(
            url, json=payload, headers=headers, verify=self.verify_ssl,
        )
        if not response.ok:
            try:
                detail = response.json()
            except Exception:
                detail = response.text[:500]
            raise RuntimeError(
                f"WAIP API {response.status_code}: {detail}"
            )

        data = response.json()

        if "data" in data and "content" in data["data"]:
            content = data["data"]["content"]
        elif "choices" in data:
            content = data["choices"][0]["message"]["content"]
        elif "response" in data:
            content = data["response"]
        elif "result" in data:
            content = data["result"]
        else:
            content = json.dumps(data)

        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )

    def with_structured_output(self, schema, **kwargs):
        """Prompt-based structured output — injects JSON instructions, parses response into *schema*."""
        schema_desc = json.dumps(schema.model_json_schema(), indent=2)
        json_suffix = (
            "\n\nYou MUST respond with valid JSON matching this schema:\n"
            f"{schema_desc}\n"
            "Return ONLY the raw JSON object. No markdown fences, no explanation."
        )

        model = self

        def _invoke_and_parse(input_val, config=None):
            if isinstance(input_val, list):
                messages = list(input_val)
            elif hasattr(input_val, "to_messages"):
                messages = input_val.to_messages()
            else:
                messages = [HumanMessage(content=str(input_val))]

            last = messages[-1]
            messages[-1] = type(last)(content=last.content + json_suffix)

            ai_msg = model.invoke(messages, config=config)
            text = ai_msg.content.strip()

            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            return schema(**json.loads(text))

        return RunnableLambda(_invoke_and_parse)


def get_llm(
    temperature: float = 0.0,
    model: str = "gpt-4o",
):
    """
    Central LLM factory — routes through the Wipro AI Platform (WAIP).
    All nodes MUST use this.
    """
    return WaipChatModel(
        model_name=model,
        temperature=temperature,
    )
