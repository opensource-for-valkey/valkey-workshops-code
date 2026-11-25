"""Natural-language weather prompt and semantic caching."""

from importlib import import_module

__all__ = ["PromptNormalizer", "WeatherQuestionService", "create_app"]


def __getattr__(name: str):
    modules = {
        "create_app": ".app",
        "PromptNormalizer": ".normalizer",
        "WeatherQuestionService": ".service",
    }
    if name not in modules:
        raise AttributeError(name)
    value = getattr(import_module(modules[name], __name__), name)
    globals()[name] = value
    return value
