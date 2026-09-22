"""Errors exposed by shared command and Herdr runtime boundaries."""


class HerdrRuntimeError(Exception):
    """Base class for expected runtime boundary failures."""


class RuntimeCommandError(HerdrRuntimeError):
    """An external command could not be executed."""


class HerdrError(HerdrRuntimeError):
    """A Herdr command or response failed validation."""
