"""A ChatOpenAI subclass that survives OpenRouter's transient upstream errors.

OpenRouter does not always signal a provider failure with an HTTP error code.
When the upstream provider is rate-limited or briefly unavailable it returns
HTTP 200 with an `error` object in the body, which langchain_openai raises as
a plain `ValueError`. That happens *after* the OpenAI SDK's own retry logic,
so `max_retries` never sees it and a single blip fails the whole request.

This class retries those specific failures with exponential backoff. Genuine
errors -- a bad model id, an invalid key, a malformed request -- are not
retried, because repeating them would only waste time.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from langchain_openai import ChatOpenAI


logger = logging.getLogger(__name__)


# Substrings that mark a failure worth retrying. Matched case-insensitively
# against the error text returned by OpenRouter.
TRANSIENT_ERROR_MARKERS = (
    "resourceexhausted",
    "rate limit",
    "rate-limit",
    "ratelimit",
    "request limit",
    "temporarily",
    "timeout",
    "timed out",
    "overloaded",
    "unavailable",
    "upstream error",
    "internal server error",
    "502",
    "503",
    "504",
)


def is_transient_error(error: BaseException) -> bool:
    """Return True when the failure is worth retrying."""

    text = str(error).lower()
    return any(marker in text for marker in TRANSIENT_ERROR_MARKERS)


class ResilientChatOpenAI(ChatOpenAI):
    """ChatOpenAI that retries transient OpenRouter/provider failures.

    `transient_max_attempts` counts total attempts, so 4 means the original
    call plus three retries.
    """

    transient_max_attempts: int = 4

    # A user is waiting on this request, so the backoff is deliberately
    # short. These provider errors clear in well under a second -- the
    # retry exists to dodge a busy worker, not to wait out a long outage.
    # At 0.6s doubling to a 2.5s cap, three retries add at most ~4.3s;
    # at the previous 1.5s base with no cap they added 10.5s, which was a
    # bigger latency contributor than the model itself.
    transient_backoff_seconds: float = 0.6
    transient_backoff_cap_seconds: float = 2.5

    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        last_error: BaseException | None = None

        for attempt in range(1, self.transient_max_attempts + 1):
            try:
                return super()._generate(*args, **kwargs)
            except Exception as error:
                if not is_transient_error(error):
                    raise

                last_error = error

                if attempt == self.transient_max_attempts:
                    break

                # Capped exponential backoff with jitter, so simultaneous
                # requests do not all retry at the same moment.
                delay = min(
                    self.transient_backoff_seconds * (2 ** (attempt - 1)),
                    self.transient_backoff_cap_seconds,
                )
                delay += random.uniform(0, 0.25)

                logger.warning(
                    "Transient model error on attempt %s/%s; retrying in "
                    "%.1fs: %s",
                    attempt,
                    self.transient_max_attempts,
                    delay,
                    error,
                )

                time.sleep(delay)

        assert last_error is not None
        raise last_error
