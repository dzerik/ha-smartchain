"""Argument bounds for the built-in search tools.

`dispatcher.dispatch` validates a tool call against its JSON schema only for
YAML-declared tools. The built-ins never pass through it: their arguments come
off `tool_args` and go straight into the executor, so a `minimum`/`maximum` in
a built-in's schema is advice to the model and nothing more. A model that does
not honour it — a local one, most often — hands the executor whatever integer
it wrote.

Clamping happens in the executor rather than at the dispatch site because the
executors are the boundary every caller shares: the conversation entity's
tool-call loop today, anything else later.
"""

import logging

from ...const import BUILTIN_SEARCH_MIN_TOP_K

LOGGER = logging.getLogger(__name__)


def clamp_top_k(value: int, maximum: int, tool: str) -> int:
    """`value` brought inside [BUILTIN_SEARCH_MIN_TOP_K, maximum].

    Clamped, not rejected: an out-of-range `top_k` is the model being sloppy
    about a bound that only ever mattered to us, and the query it asked is
    still answerable. It is logged at WARNING every time, so a model that
    routinely ignores the schema is visible in the log rather than silently
    accommodated.
    """
    clamped = max(BUILTIN_SEARCH_MIN_TOP_K, min(int(value), maximum))
    if clamped != value:
        LOGGER.warning(
            "%s: top_k=%r is outside [%d, %d]; using %d",
            tool,
            value,
            BUILTIN_SEARCH_MIN_TOP_K,
            maximum,
            clamped,
        )
    return clamped
