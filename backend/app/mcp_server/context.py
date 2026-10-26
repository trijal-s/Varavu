"""Which shop the current request belongs to. Set by the HTTP middleware from the shop's API key;
the local stdio server always uses 'local'."""
from contextvars import ContextVar

current_shop: ContextVar[str] = ContextVar("current_shop", default="local")
