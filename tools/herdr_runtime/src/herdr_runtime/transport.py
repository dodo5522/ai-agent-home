"""Command transport for Herdr resource clients."""

import json
from collections.abc import Sequence
from typing import cast

from ._decoding import JsonObject, required_object
from .errors import HerdrError
from .runner import CommandRunner


class HerdrTransport:
    def __init__(self, runner: CommandRunner, herdr_bin: str) -> None:
        self._runner = runner
        self._herdr_bin = herdr_bin

    def request(self, arguments: Sequence[str]) -> JsonObject:
        result = self._runner.run([self._herdr_bin, *arguments])
        if result.returncode != 0:
            raise HerdrError(f"Herdr command failed: {arguments[0]}")
        try:
            document = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise HerdrError("Herdr response is invalid JSON") from error
        if not isinstance(document, dict):
            raise HerdrError("Herdr response is not an object")
        return required_object(cast(JsonObject, document), "result")
