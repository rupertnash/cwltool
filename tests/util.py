import contextlib
import io
import json
import os
import shutil
from pathlib import Path
from typing import Dict, Generator, List, Mapping, Optional, Tuple, Union

import pytest
from pkg_resources import Requirement, ResolutionError, resource_filename

from cwltool.main import main
from cwltool.singularity import is_version_2_6, is_version_3_or_newer


def force_default_container(default_container_id: str, _: str) -> str:
    return default_container_id


def get_data(filename: str) -> str:
    # normalizing path depending on OS or else it will cause problem when joining path
    filename = os.path.normpath(filename)
    filepath = None
    try:
        filepath = resource_filename(Requirement.parse("cwltool"), filename)
    except ResolutionError:
        pass
    if not filepath or not os.path.isfile(filepath):
        filepath = os.path.join(os.path.dirname(__file__), os.pardir, filename)
    return str(Path(filepath).resolve())


needs_docker = pytest.mark.skipif(
    not bool(shutil.which("docker")),
    reason="Requires the docker executable on the system path.",
)

needs_singularity = pytest.mark.skipif(
    not bool(shutil.which("singularity")),
    reason="Requires the singularity executable on the system path.",
)

needs_singularity_2_6 = pytest.mark.skipif(
    not bool(shutil.which("singularity") and is_version_2_6()),
    reason="Requires that version 2.6.x of singularity executable version is on the system path.",
)

needs_singularity_3_or_newer = pytest.mark.skipif(
    (not bool(shutil.which("singularity"))) or (not is_version_3_or_newer()),
    reason="Requires that version 3.x of singularity executable version is on the system path.",
)


def get_main_output(
    args: List[str],
    replacement_env: Optional[Mapping[str, str]] = None,
    extra_env: Optional[Mapping[str, str]] = None,
    monkeypatch: Optional[pytest.MonkeyPatch] = None,
) -> Tuple[Optional[int], str, str]:
    """Run cwltool main.

    args: the command line args to call it with

    replacement_env: a total replacement of the environment

    extra_env: add these to the environment used

    monkeypatch: required if changing the environment

    Returns (return code, stdout, stderr)
    """
    stdout = io.StringIO()
    stderr = io.StringIO()
    if replacement_env is not None:
        assert monkeypatch is not None
        monkeypatch.setattr(os, "environ", replacement_env)

    if extra_env is not None:
        assert monkeypatch is not None
        for k, v in extra_env.items():
            monkeypatch.setenv(k, v)

    try:
        rc = main(argsl=args, stdout=stdout, stderr=stderr)
    except SystemExit as e:
        rc = e.code
    return (
        rc,
        stdout.getvalue(),
        stderr.getvalue(),
    )


def get_tool_env(
    tmp_path: Path,
    flag_args: List[str],
    inputs_file: Optional[str] = None,
    replacement_env: Optional[Mapping[str, str]] = None,
    extra_env: Optional[Mapping[str, str]] = None,
    monkeypatch: Optional[pytest.MonkeyPatch] = None,
) -> Dict[str, str]:
    """Get the env vars for a tool's invocation."""
    args = flag_args + [get_data("tests/env3.cwl")]
    if inputs_file:
        args.append(inputs_file)

    with working_directory(tmp_path):
        rc, stdout, _ = get_main_output(
            args,
            replacement_env=replacement_env,
            extra_env=extra_env,
            monkeypatch=monkeypatch,
        )
        assert rc == 0

        output = json.loads(stdout)
        env_path = output["env"]["path"]
        tool_env = {}
        with open(env_path) as _:
            for line in _:
                key, val = line.split("=", 1)
                tool_env[key] = val[:-1]

        return tool_env


@contextlib.contextmanager
def working_directory(path: Union[str, Path]) -> Generator[None, None, None]:
    """Change working directory and returns to previous on exit."""
    prev_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev_cwd)
