"""Private types and validators for decoded Herdr JSON."""

from .errors import HerdrError

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | JsonObject
type JsonObject = dict[str, JsonValue]


def required_object(payload: JsonObject, name: str) -> JsonObject:
    """Return one required JSON object field."""
    value = payload.get(name)
    if not isinstance(value, dict):
        raise HerdrError(f"Herdr response has no {name} object")
    return value


def required_string(payload: JsonObject, name: str) -> str:
    """Return one required non-empty JSON string field."""
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise HerdrError(f"Herdr response has no {name}")
    return value


def optional_string(payload: JsonObject, name: str) -> str | None:
    """Return an optional non-empty JSON string field."""
    if name not in payload or payload[name] is None:
        return None
    return required_string(payload, name)
