"""The package's one configured ``AsyncClient`` and its error mapping (conventions §6)."""

import httpx
from xippios.core import AsyncClient, ClientConfig, RateLimit, XippiosError

from xippios.faostat._version import __version__

SOURCE = "faostat"
BASE_URL = "https://faostatservices.fao.org/api/v1"
API_KEY_ENV: str | None = None
# A self-imposed pace: upstream documents no per-second or per-minute limit (ADR-0010 decision 1).
RATE_LIMIT = RateLimit(per_minute=30, burst=1)


def classify(response: httpx.Response) -> XippiosError | None:
    """Upstream's documented error shapes as taxonomy errors, else ``None`` (conventions §6).

    The ``ClientConfig.classify`` hook: it sees every response before core's status mapping.
    """
    return None


config = ClientConfig(
    source=SOURCE,
    version=__version__,
    base_url=BASE_URL,
    rate_limit=RATE_LIMIT,
    classify=classify,
)

# A source with a documented hourly or daily quota installs a QuotaPolicy of its own on
# config (conventions §6, ADR-0015); core's README shows how.

client = AsyncClient(config)

__all__ = [
    "API_KEY_ENV",
    "BASE_URL",
    "RATE_LIMIT",
    "SOURCE",
    "classify",
    "client",
    "config",
]
