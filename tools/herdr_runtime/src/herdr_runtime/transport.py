"""Shared transport and response validation for Herdr resource clients."""

import json
from collections.abc import Mapping, Sequence
from typing import cast

from .errors import HerdrError
from .runner import CommandRunner


class HerdrTransport:
    def __init__(self, runner: CommandRunner, herdr_bin: str) -> None:
        self._runner = runner
        self._herdr_bin = herdr_bin

    def request(self, arguments: Sequence[str]) -> Mapping[str, object]:
        result = self._runner.run([self._herdr_bin, *arguments])
        if result.returncode != 0:
            raise HerdrError(f"Herdr command failed: {arguments[0]}")
        try:
            document = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise HerdrError("Herdr response is invalid JSON") from error
        if not isinstance(document, dict):
            raise HerdrError("Herdr response is not an object")
        payload = document.get("result")
        if not isinstance(payload, dict):
            raise HerdrError("Herdr response has no result object")
        return cast(Mapping[str, object], payload)

    @staticmethod
    def member(payload: Mapping[str, object], name: str) -> Mapping[str, object]:
        value = payload.get(name)
        if not isinstance(value, dict):
            raise HerdrError(f"Herdr response has no {name} object")
        return cast(Mapping[str, object], value)

    @staticmethod
    def string(payload: Mapping[str, object], name: str) -> str:
        value = payload.get(name)
        if not isinstance(value, str) or not value:
            raise HerdrError(f"Herdr response has no {name}")
        return value
