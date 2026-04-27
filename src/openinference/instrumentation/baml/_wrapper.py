from typing import Any

import baml_py
from opentelemetry.context import _SUPPRESS_INSTRUMENTATION_KEY, get_value
from opentelemetry.trace import Status, StatusCode, use_span

from openinference.instrumentation import OITracer

from ._span_attributes import get_initial_attributes, get_span_name, set_span_attributes_from_log

_BAML_OPTIONS_ATTR = '_DoNotUseDirectlyCallManager__baml_options'
_COLLECTOR_NAME = 'openinference'


def _inject_collector(instance: Any, collector: baml_py.Collector) -> None:
    opts = getattr(instance, _BAML_OPTIONS_ATTR)
    existing = opts.get('collector')
    if existing is None:
        opts['collector'] = collector
    elif isinstance(existing, list):
        existing.append(collector)
    else:
        opts['collector'] = [existing, collector]


class _AsyncCallWrapper:
    def __init__(self, tracer: OITracer) -> None:
        self._tracer = tracer

    async def __call__(
        self,
        wrapped: Any,
        instance: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        if get_value(_SUPPRESS_INSTRUMENTATION_KEY):
            return await wrapped(*args, **kwargs)

        collector = baml_py.Collector(_COLLECTOR_NAME)
        _inject_collector(instance, collector)

        function_name = kwargs['function_name']

        span = self._tracer.start_span(
            get_span_name(function_name),
            openinference_span_kind='llm',
            attributes=get_initial_attributes(),
        )
        with use_span(span, end_on_exit=False, record_exception=False, set_status_on_exception=False):
            try:
                result = await wrapped(*args, **kwargs)
                if log := collector.last:
                    set_span_attributes_from_log(span, log)
                span.set_status(Status(StatusCode.OK))
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise
            finally:
                span.end()
                collector.clear()


class _SyncCallWrapper:
    def __init__(self, tracer: OITracer) -> None:
        self._tracer = tracer

    def __call__(
        self,
        wrapped: Any,
        instance: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        if get_value(_SUPPRESS_INSTRUMENTATION_KEY):
            return wrapped(*args, **kwargs)

        collector = baml_py.Collector(_COLLECTOR_NAME)
        _inject_collector(instance, collector)

        function_name = kwargs['function_name']

        span = self._tracer.start_span(
            get_span_name(function_name),
            openinference_span_kind='llm',
            attributes=get_initial_attributes(),
        )
        with use_span(span, end_on_exit=False, record_exception=False, set_status_on_exception=False):
            try:
                result = wrapped(*args, **kwargs)
                if log := collector.last:
                    set_span_attributes_from_log(span, log)
                span.set_status(Status(StatusCode.OK))
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise
            finally:
                span.end()
                collector.clear()
