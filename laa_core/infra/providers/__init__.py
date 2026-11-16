"""Provider gateway + adapters (Fake + DeepSeek/OpenAI-compatible)."""
from .gateway import ProviderGateway, ProviderRouter  # noqa: F401
from .fake import FakeProvider  # noqa: F401
from .openai_compat import OpenAICompatProvider  # noqa: F401