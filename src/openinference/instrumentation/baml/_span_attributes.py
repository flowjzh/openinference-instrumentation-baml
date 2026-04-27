import json
from typing import Any

from opentelemetry.trace import Span
from opentelemetry.util.types import AttributeValue

from openinference.instrumentation import (
    get_input_attributes,
    get_llm_provider_attributes,
    get_llm_system_attributes,
    get_llm_token_count_attributes,
    get_output_attributes,
    get_span_kind_attributes,
)
from openinference.instrumentation._types import TokenCount
from openinference.semconv.trace import OpenInferenceSpanKindValues

from ._providers import get_provider_parser

_BAML_SYSTEM = 'baml'


def get_span_name(function_name: str) -> str:
    return f'BAML.{function_name}'


def get_initial_attributes() -> dict[str, AttributeValue]:
    attrs: dict[str, AttributeValue] = {}
    attrs.update(get_span_kind_attributes(OpenInferenceSpanKindValues.LLM))
    attrs.update(get_llm_system_attributes(_BAML_SYSTEM))
    return attrs


def _safe_parse_body(http_msg: Any) -> dict | None:
    try:
        body = http_msg.body.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def set_span_attributes_from_log(
    span: Span,
    log: Any,
) -> None:
    attrs: dict[str, AttributeValue] = {}

    usage = log.usage
    if usage:
        token_count: TokenCount = {}
        if (inp := usage.input_tokens) is not None:
            token_count['prompt'] = inp
        if (out := usage.output_tokens) is not None:
            token_count['completion'] = out
        if inp is not None and out is not None:
            token_count['total'] = inp + out
        if (cached := usage.cached_input_tokens) is not None:
            token_count.setdefault('prompt_details', {})['cache_read'] = cached
        attrs.update(get_llm_token_count_attributes(token_count or None))

    call = log.selected_call
    if call:
        attrs.update(get_llm_provider_attributes(call.provider))

        parser = get_provider_parser(call.provider)
        if parser:
            if call.http_request:
                if body := _safe_parse_body(call.http_request):
                    attrs.update(get_input_attributes(body))
                    attrs.update(parser.parse_request(body))
            if call.http_response:
                if body := _safe_parse_body(call.http_response):
                    attrs.update(parser.parse_response(body))

    if log.raw_llm_response:
        attrs.update(get_output_attributes(log.raw_llm_response))

    for k, v in attrs.items():
        span.set_attribute(k, v)
