"""chatbot_fifa_extension — framework-neutral FIFA World Cup betting capability.

The package exposes its betting operations as neutral :class:`ToolSpec`
descriptors (see :mod:`chatbot_fifa_extension.tools`) that any agent framework
(OpenAI Agents SDK, MCP, REST, ...) can bind to. It does NOT depend on any LLM
SDK; the binding lives in the consuming host.

Typical use from a host::

    from chatbot_fifa_extension import build_context, get_toolspecs
    ctx = build_context(conf["chatbot_fifa_extension"])
    for spec in get_toolspecs():
        ...  # adapt spec to the host's tool format, calling spec.handler(ctx, params)
"""

from .context import FifaContext, build_context
from .tools import ToolSpec, TOOLSPECS, get_toolspecs


__all__ = [
    "FifaContext",
    "build_context",
    "ToolSpec",
    "TOOLSPECS",
    "get_toolspecs",
]
