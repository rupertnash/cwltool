"""Test optional udocker feature."""
import copy
import os
import subprocess
import sys

from pathlib import Path

import pytest
from _pytest.tmpdir import TempPathFactory

from .install_udocker import install_udocker
from .util import get_data, get_main_output

LINUX = sys.platform in ("linux", "linux2")


@pytest.fixture(scope="session")
def udocker(tmp_path_factory: TempPathFactory) -> str:
    """Udocker fixture, returns the path to the udocker script."""
    try:
        preinstalled_udocker = os.environ["CWLTOOL_TESTS_UDOCKER_DIR"]
        exe = os.path.join(preinstalled_udocker, "udocker")
        assert os.path.exists(exe)
        return exe
    except KeyError:
        # Have to install ourselves
        pass
    docker_install_dir = str(tmp_path_factory.mktemp("udocker"))
    return install_udocker(docker_install_dir)


@pytest.mark.skipif(not LINUX, reason="LINUX only")
def test_udocker_usage_should_not_write_cid_file(udocker: str, tmp_path: Path) -> None:
    """Confirm that no cidfile is made when udocker is used."""
    cwd = Path.cwd()
    os.chdir(tmp_path)

    test_file = "tests/wf/wc-tool.cwl"
    job_file = "tests/wf/wc-job.json"
    error_code, stdout, stderr = get_main_output(
        [
            "--debug",
            "--default-container",
            "debian",
            "--user-space-docker-cmd=" + udocker,
            get_data(test_file),
            get_data(job_file),
        ]
    )

    cidfiles_count = sum(1 for _ in tmp_path.glob("*.cid"))
    os.chdir(cwd)

    assert "completed success" in stderr, stderr
    assert cidfiles_count == 0


@pytest.mark.skipif(
    not LINUX,
    reason="Linux only",
)
def test_udocker_should_display_memory_usage(udocker: str, tmp_path: Path) -> None:
    """Confirm that memory ussage is logged even with udocker."""
    cwd = Path.cwd()
    os.chdir(tmp_path)
    error_code, stdout, stderr = get_main_output(
        [
            "--enable-ext",
            "--default-container=debian",
            "--user-space-docker-cmd=" + udocker,
            get_data("tests/wf/timelimit.cwl"),
        ]
    )
    os.chdir(cwd)

    assert "completed success" in stderr, stderr
    assert "Max memory" in stderr, stderr
