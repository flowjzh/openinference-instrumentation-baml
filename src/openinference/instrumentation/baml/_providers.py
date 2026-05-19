import json
import logging
from typing import Any

from openinference.instrumentation import (
    REDACTED_VALUE,
    get_llm_input_message_attributes,
    get_llm_invocation_parameter_attributes,
    get_llm_model_name_attributes,
    get_llm_output_message_attributes,
    get_llm_token_count_attributes,
)
from openinference.instrumentation._types import Message, TokenCount
from openinference.instrumentation.config import DEFAULT_BASE64_IMAGE_MAX_LENGTH, is_base64_url

logger = logging.getLogger(__name__)

_OPENAI_COMPAT_PROVIDERS = frozenset({'openai-generic', 'openai', 'openrouter', 'ollama'})
_ANTHROPIC_PROVIDER = 'anthropic'

_warned_providers: set[str] = set()


def get_provider_parser(provider: str) -> '_ProviderParser | None':
    if provider in _OPENAI_COMPAT_PROVIDERS:
        return _openai_compat_parser
    if provider == _ANTHROPIC_PROVIDER:
        return _anthropic_parser
    if provider not in _warned_providers:
        _warned_providers.add(provider)
        logger.warning("Unsupported BAML provider '%s' — skipping request/response attribute extraction", provider)
    return None


class _ProviderParser:
    _excluded_req_keys: frozenset[str]

    def parse_request(self, body: dict) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if model := body.get('model'):
            attrs.update(get_llm_model_name_attributes(str(model)))
        if isinstance(body.get('messages'), list):
            attrs.update(get_llm_input_message_attributes(_parse_chat_messages(body['messages'])))
        params = {k: v for k, v in body.items() if k not in self._excluded_req_keys}
        if params:
            attrs.update(get_llm_invocation_parameter_attributes(params))
        return attrs

    def _extract_cache_details(self, resp_usage: dict) -> dict[str, Any]:
        if not isinstance(resp_usage, dict):
            return {}
        token_count: TokenCount = {}
        prompt_details: dict[str, int] = {}
        if (cache_read := resp_usage.get('cached_tokens')) is not None:
            prompt_details['cache_read'] = cache_read
        if (cache_write := resp_usage.get('cache_creation_input_tokens')) is not None:
            prompt_details['cache_write'] = cache_write
        if prompt_details:
            token_count['prompt_details'] = prompt_details
        return get_llm_token_count_attributes(token_count)


def _normalize_message(msg: dict) -> Message:
    result: Message = {'role': msg['role']}
    content = msg.get('content')
    if isinstance(content, str):
        result['content'] = content
    elif isinstance(content, list):
        contents: list[dict] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'text' and isinstance(block.get('text'), str):
                contents.append({'type': 'text', 'text': block['text']})
            elif block.get('type') == 'image_url':
                url = (block.get('image_url') or {}).get('url') if isinstance(block.get('image_url'), dict) else block.get('url')
                if isinstance(url, str):
                    url = REDACTED_VALUE if is_base64_url(url) and len(url) > DEFAULT_BASE64_IMAGE_MAX_LENGTH else url
                    contents.append({'type': 'image', 'image': {'url': url}})
        if contents:
            result['contents'] = contents
    if isinstance(msg.get('tool_calls'), list):
        result['tool_calls'] = msg['tool_calls']
    return result


def _parse_chat_messages(raw_messages: list[Any]) -> list[Message]:
    messages: list[Message] = []
    for msg in raw_messages:
        if not isinstance(msg, dict) or not msg.get('role'):
            continue
        messages.append(_normalize_message(msg))
    return messages


class _OpenAICompatParser(_ProviderParser):
    _excluded_req_keys = frozenset({'model', 'messages'})

    def _extract_cache_details(self, resp_usage: dict) -> dict[str, Any]:
        if not isinstance(resp_usage, dict):
            return {}
        details = resp_usage.get('prompt_tokens_details')
        if not isinstance(details, dict):
            return {}
        token_count: TokenCount = {}
        prompt_details: dict[str, int] = {}
        if (cache_read := details.get('cached_tokens')) is not None:
            prompt_details['cache_read'] = cache_read
        if (cache_write := details.get('cache_creation_input_tokens')) is not None:
            prompt_details['cache_write'] = cache_write
        if prompt_details:
            token_count['prompt_details'] = prompt_details
        return get_llm_token_count_attributes(token_count)

    def parse_response(self, body: dict) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        choices = body.get('choices')
        if isinstance(choices, list):
            output_msgs: list[Message] = []
            for choice in choices:
                msg = choice.get('message') if isinstance(choice, dict) else None
                if isinstance(msg, dict):
                    output_msgs.append(_normalize_message(msg))
            if output_msgs:
                attrs.update(get_llm_output_message_attributes(output_msgs))
        attrs.update(self._extract_cache_details(body.get('usage', {})))
        return attrs


class _AnthropicParser(_ProviderParser):
    _excluded_req_keys = frozenset({'model', 'messages', 'system'})

    def parse_response(self, body: dict) -> dict[str, Any]:
        attrs: dict[str, Any] = {}

        content = body.get('content')
        if isinstance(content, list):
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get('type') == 'text' and isinstance(text := block.get('text'), str):
                    text_parts.append(text)
                elif block.get('type') == 'tool_use':
                    tc: dict[str, Any] = {}
                    if isinstance(tid := block.get('id'), str):
                        tc['id'] = tid
                    if isinstance(fn := block.get('name'), str):
                        tc['function'] = {'name': fn}
                        if isinstance(args := block.get('input'), dict):
                            tc['function']['arguments'] = json.dumps(args)
                    if tc:
                        tool_calls.append(tc)
            if text_parts or tool_calls:
                msg: Message = {'role': 'assistant'}
                if text_parts:
                    msg['content'] = '\n'.join(text_parts)
                if tool_calls:
                    msg['tool_calls'] = tool_calls
                attrs.update(get_llm_output_message_attributes([msg]))

        attrs.update(self._extract_cache_details(body.get('usage', {})))
        return attrs


_openai_compat_parser = _OpenAICompatParser()
_anthropic_parser = _AnthropicParser()
