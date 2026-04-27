# OpenInference BAML Instrumentation

[![pypi](https://badge.fury.io/py/openinference-instrumentation-baml.svg)](https://pypi.org/project/openinference-instrumentation-baml/)

Python auto-instrumentation library for [BAML](https://github.com/BoundaryML/baml) (baml-py).

The traces emitted by this instrumentation follow the [OpenInference](https://github.com/Arize-ai/openinference) semantic conventions and are fully OpenTelemetry compatible. They can be sent to any OpenTelemetry collector, such as [Arize Phoenix](https://github.com/Arize-ai/phoenix).

## Installation

```shell
pip install openinference-instrumentation-baml
```

## Quickstart

In this example we will instrument a BAML application and observe traces via [Arize Phoenix](https://github.com/Arize-ai/phoenix).

Install packages.

```shell
pip install openinference-instrumentation-baml "baml-py>=0.200" arize-phoenix-otel
```

Assuming you have a BAML project with a generated Python client (e.g. `my_app.baml_client`), instrument it as follows:

```python
from phoenix.otel import register

tracer_provider = register(
    batch=True,
    auto_instrument=True,  # automatically discovers openinference-instrumentation-baml
)

# That's it! All BAML function calls will now emit traces.
```

Or, if you prefer manual setup:

```python
from openinference.instrumentation.baml import BamlInstrumentor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk import trace as trace_sdk
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

endpoint = "http://127.0.0.1:6006/v1/traces"
tracer_provider = trace_sdk.TracerProvider()
tracer_provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint)))

BamlInstrumentor().instrument(
    tracer_provider=tracer_provider,
    baml_client_module="my_app.baml_client",
)
```

Now run your application and observe the traces in Phoenix.

```shell
python your_file.py
```

## How It Works

BAML generates a `DoNotUseDirectlyCallManager` class that all LLM function calls pass through. This instrumentor patches its `call_function_async` and `call_function_sync` methods to:

1. Inject a per-call `Collector` to capture the `FunctionLog`
2. Extract trace data (model name, input/output messages, token counts, timing)
3. Emit an OpenTelemetry span with OpenInference semantic conventions

### Auto-Discovery

When using `auto_instrument=True` via `phoenix.otel.register()`, the instrumentor automatically scans loaded modules for a BAML generated client. This works as long as the `baml_client` module has been imported before `register()` is called.

If auto-discovery fails, pass the module explicitly:

```python
BamlInstrumentor().instrument(
    tracer_provider=tracer_provider,
    baml_client_module="my_app.baml_client",
)
```

### Captured Attributes

The following OpenInference attributes are populated on each span:

| Attribute | Source |
|---|---|
| `openinference.span.kind` | `"LLM"` |
| `llm.system` | `"baml"` |
| `llm.provider` | BAML client provider (e.g. `"openai-generic"`) |
| `llm.model_name` | Model name from the HTTP request body |
| `llm.input_messages.*` | Parsed from the LLM request messages |
| `llm.output_messages.*` | Parsed from the LLM response choices |
| `llm.token_count.prompt` | Input token count |
| `llm.token_count.completion` | Output token count |
| `llm.token_count.total` | Sum of prompt + completion tokens |
| `llm.invocation_parameters` | Request parameters (temperature, max_tokens, etc.) |
| `input.value` | BAML function arguments (JSON) |
| `output.value` | LLM response content |

## Limitations

**Streaming calls are not instrumented.** Only `call_function_async` and `call_function_sync` (non-streaming) are patched. For streaming calls (`create_async_stream` / `create_sync_stream`), the stream is consumed asynchronously by user code, so the instrumentor cannot reliably determine when the stream completes to capture the full response. Streaming support may be added in a future release.

**Provider-specific attribute parsing.** Input/output messages, model name, and invocation parameters are parsed from the raw HTTP request/response bodies, which vary by provider. The following providers are supported:

| Provider | `llm.input_messages` | `llm.output_messages` | `llm.model_name` | `llm.invocation_parameters` | Cache tokens |
|---|---|---|---|---|---|
| `openai`, `openai-generic`, `openrouter`, `ollama` | ✓ | ✓ | ✓ | ✓ | cache_read (via BAML) |
| `anthropic` | ✓ | ✓ | ✓ | ✓ | cache_read + cache_write |

For unsupported providers, a one-time warning is logged and these attributes are skipped. Token counts (`prompt`, `completion`, `total`, `cache_read`) are always extracted from BAML's provider-agnostic `Usage` object regardless of provider.

## Disclaimer

This is **not** an official OpenInference library. It is a community-maintained extension and is provided as-is without warranty. The author is not responsible for any issues arising from its use.

The OpenInference project does not currently accept large-scale contributions, so this instrumentor is maintained separately. Contributions and feedback from the community are welcome. If the OpenInference team decides to build official BAML instrumentation in the future, users are encouraged to migrate to the official version.

## More Info

* [More info on OpenInference and Phoenix](https://docs.arize.com/phoenix)
* [How to customize spans to track sessions, metadata, etc.](https://github.com/Arize-ai/openinference/tree/main/python/openinference-instrumentation#customizing-spans)
* [How to account for private information and span payload customization](https://github.com/Arize-ai/openinference/tree/main/python/openinference-instrumentation#tracing-configuration)
