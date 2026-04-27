import importlib
import sys
from typing import Any, Collection, Optional

from opentelemetry import trace as trace_api
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from wrapt import wrap_function_wrapper

from openinference.instrumentation import OITracer, TraceConfig

from ._wrapper import _AsyncCallWrapper, _SyncCallWrapper
from .version import __version__

_instruments = ('baml-py >= 0.200',)
_TARGET_CLASS = 'DoNotUseDirectlyCallManager'

_CALL_METHODS = (
    ('call_function_async', _AsyncCallWrapper),
    ('call_function_sync', _SyncCallWrapper),
)


def _discover_baml_client_module() -> Optional[str]:
    for mod_name in sys.modules:
        if not mod_name.endswith('.baml_client') or mod_name.startswith('_'):
            continue
        runtime_name = f'{mod_name}.runtime'
        runtime = sys.modules.get(runtime_name)
        if runtime and hasattr(runtime, _TARGET_CLASS):
            return mod_name
    return None


class BamlInstrumentor(BaseInstrumentor):
    __slots__ = ('_wrappers', '_module_name')

    def instrumentation_dependencies(self) -> Collection[str]:
        return _instruments

    def _instrument(self, **kwargs: Any) -> None:
        tracer_provider = kwargs.get('tracer_provider') or trace_api.get_tracer_provider()
        config = kwargs.get('config') or TraceConfig()

        baml_client_module = kwargs.get('baml_client_module') or _discover_baml_client_module()
        if not baml_client_module:
            raise ValueError(
                'Could not auto-discover a BAML generated client module. '
                "Pass 'baml_client_module' explicitly, e.g. "
                "BamlInstrumentor().instrument(baml_client_module='argus.baml_client')."
            )

        tracer = OITracer(
            trace_api.get_tracer(__name__, __version__, tracer_provider),
            config=config,
        )

        runtime_module_name = f'{baml_client_module}.runtime'
        module = importlib.import_module(runtime_module_name)

        if not hasattr(module, _TARGET_CLASS):
            raise ValueError(
                f'Module {runtime_module_name} has no {_TARGET_CLASS}. '
                'Ensure the baml_client_module points to a valid BAML generated package.'
            )

        self._module_name = runtime_module_name
        self._wrappers = []

        for method_name, wrapper_cls in _CALL_METHODS:
            wrapper = wrapper_cls(tracer)
            wrap_function_wrapper(
                runtime_module_name,
                f'{_TARGET_CLASS}.{method_name}',
                wrapper,
            )
            self._wrappers.append((method_name, wrapper))

    def _uninstrument(self, **kwargs: Any) -> None:
        if not self._module_name:
            return

        module = importlib.import_module(self._module_name)
        cls = getattr(module, _TARGET_CLASS, None)
        if cls:
            for method_name, _ in self._wrappers:
                original = getattr(cls, method_name, None)
                if original and hasattr(original, '__wrapped__'):
                    setattr(cls, method_name, original.__wrapped__)

        self._wrappers.clear()
        self._module_name = ''
