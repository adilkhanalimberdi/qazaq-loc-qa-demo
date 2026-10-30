"""Errors that map to CLI exit codes."""


class LocqaError(Exception):
    exit_code = 2


class InputError(LocqaError):
    """Bad input: missing file, broken ARB, invalid flags. Exit code 2."""

    exit_code = 2


class LLMError(LocqaError):
    """LLM layer failed: no key, budget exceeded, network. Exit code 3."""

    exit_code = 3
