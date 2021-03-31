"""Test passing of environment variables to tools."""
from abc import ABC, abstractmethod
import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Set, Union, cast

import pytest

from .util import get_tool_env, needs_docker, needs_singularity

# None => accept anything, just require the key is present
# str => string equality
# Callable => call the function with the value - True => OK, False => fail
# TODO: maybe add regex?
CheckerTypes = Union[None, str, Callable[[str], bool]]
EnvChecks = Dict[str, CheckerTypes]


def assert_envvar_matches(check: CheckerTypes, k: str, v: str) -> None:
    """Assert that the check is satisfied by the key-value."""
    if check is None:
        pass
    elif isinstance(check, str):
        assert v == check, f'Environment variable {k} != "{check}"'
    else:
        assert check(v), f'Environment variable {k}="{v}" fails check'


def assert_env_matches(
    checks: EnvChecks, env: Mapping[str, str], allow_unexpected: bool = False
) -> None:
    """Assert that all checks are satisfied by the Mapping.

    Optional flag `allow_unexpected` (default = False) will allow the
    Mapping to contain extra keys which are not checked.
    """
    e = dict(env)
    for k, check in checks.items():
        v = e.pop(k)
        assert_envvar_matches(check, k, v)

    if not allow_unexpected:
        assert (
            len(e) == 0
        ), f"Unexpected environment variable(s): {', '.join(env.keys())}"


class CheckHolder(ABC):
    """Base class for check factory functions and other data required to parametrize the tests below."""

    @staticmethod
    @abstractmethod
    def checks(tmp_prefix: str) -> EnvChecks:
        """Return a mapping from environment variable names to how to check for correctness."""
        pass

    # Any flags to pass to cwltool to force use of the correct container
    flags: List[str]
    pass


class NoContainer(CheckHolder):
    """No containers at all, just run in the host."""

    @staticmethod
    def checks(tmp_prefix: str) -> EnvChecks:
        """Create checks."""
        return {
            "TMPDIR": lambda v: v.startswith(tmp_prefix),
            "HOME": lambda v: v.startswith(tmp_prefix),
            "PATH": os.environ["PATH"],
        }

    flags = ["--no-container"]


class Docker(CheckHolder):
    """Run in a Docker container."""

    @staticmethod
    def checks(tmp_prefix: str) -> EnvChecks:
        """Create checks."""

        def HOME(v: str) -> bool:
            # Want /whatever
            parts = os.path.split(v)
            return len(parts) == 2 and parts[0] == "/"

        return {
            "HOME": HOME,
            "TMPDIR": "/tmp",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOSTNAME": None,
        }

    flags = ["--default-container=debian"]


class Singularity(CheckHolder):
    """Run in a Singularity container."""

    @staticmethod
    def checks(tmp_prefix: str) -> EnvChecks:
        """Create checks."""
        return {
            "HOME": None,
            "LANG": "C",
            "LD_LIBRARY_PATH": None,
            "PATH": None,
            "PROMPT_COMMAND": None,
            "PWD": None,
            "SINGULARITY_COMMAND": "exec",
            "SINGULARITY_CONTAINER": None,
            "SINGULARITY_ENVIRONMENT": None,
            "SINGULARITY_NAME": None,
            "TERM": None,
        }

    flags = ["--default-container=debian", "--singularity"]


# CRT = container runtime
CRT_PARAMS = pytest.mark.parametrize(
    "crt_params",
    [
        NoContainer(),
        pytest.param(Docker(), marks=needs_docker),
        pytest.param(Singularity(), marks=needs_singularity),
    ],
)


@CRT_PARAMS
def test_basic(crt_params: CheckHolder, tmp_path: Path, monkeypatch: Any) -> None:
    """Test that basic env vars (only) show up."""
    tmp_prefix = str(tmp_path / "canary")
    extra_env = {
        "USEDVAR": "VARVAL",
        "UNUSEDVAR": "VARVAL",
    }
    args = crt_params.flags + [f"--tmpdir-prefix={tmp_prefix}"]
    env = get_tool_env(tmp_path, args, extra_env=extra_env, monkeypatch=monkeypatch)
    checks = crt_params.checks(tmp_prefix)
    assert_env_matches(checks, env)


@CRT_PARAMS
def test_preserve_single(
    crt_params: CheckHolder, tmp_path: Path, monkeypatch: Any
) -> None:
    """Test that preserving a single env var works."""
    tmp_prefix = str(tmp_path / "canary")
    extra_env = {
        "USEDVAR": "VARVAL",
        "UNUSEDVAR": "VARVAL",
    }
    args = crt_params.flags + [
        f"--tmpdir-prefix={tmp_prefix}",
        "--preserve-environment=USEDVAR",
    ]
    env = get_tool_env(tmp_path, args, extra_env=extra_env, monkeypatch=monkeypatch)
    checks = crt_params.checks(tmp_prefix)
    checks["USEDVAR"] = extra_env["USEDVAR"]
    assert_env_matches(checks, env)


@CRT_PARAMS
def test_preserve_all(
    crt_params: CheckHolder, tmp_path: Path, monkeypatch: Any
) -> None:
    """Test that preserving all works."""
    tmp_prefix = str(tmp_path / "canary")
    extra_env = {
        "USEDVAR": "VARVAL",
        "UNUSEDVAR": "VARVAL",
    }
    args = crt_params.flags + [
        f"--tmpdir-prefix={tmp_prefix}",
        "--preserve-entire-environment",
    ]
    env = get_tool_env(tmp_path, args, extra_env=extra_env, monkeypatch=monkeypatch)
    checks = crt_params.checks(tmp_prefix)
    checks["USEDVAR"] = extra_env["USEDVAR"]
    checks.pop("PATH")

    for vname, val in env.items():
        try:
            assert_envvar_matches(checks[vname], vname, val)
        except KeyError:
            assert val == os.environ[vname]
