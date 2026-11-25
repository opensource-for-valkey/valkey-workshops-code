"""OpenWeatherMap One Call API 4.0 proxy package."""

from importlib import import_module

__all__ = [
    "OpenWeatherMapClient",
    "OpenWeatherMapError",
    "OpenWeatherMapGeocodingClient",
    "ValkeyJsonCache",
    "build_cache_key",
    "create_app",
]


def __getattr__(name: str):
    modules = {
        "create_app": ".app",
        "ValkeyJsonCache": ".cache",
        "build_cache_key": ".cache",
        "OpenWeatherMapClient": ".client",
        "OpenWeatherMapError": ".client",
        "OpenWeatherMapGeocodingClient": ".geocoding",
    }
    if name not in modules:
        raise AttributeError(name)
    value = getattr(import_module(modules[name], __name__), name)
    globals()[name] = value
    return value
