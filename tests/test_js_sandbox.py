from typing import Any

import pytest

from cwltool import sandboxjs
from cwltool.factory import Factory

from .util import get_data

node_versions = [
    ("v0.8.26\n", False),
    ("v0.10.25\n", False),
    ("v0.10.26\n", True),
    ("v4.4.2\n", True),
    ("v7.7.3\n", True),
]


@pytest.mark.parametrize("version,supported", node_versions)
def test_node_version(version: str, supported: bool, mocker: Any) -> None:
    mocked_subprocess = mocker.patch("cwltool.sandboxjs.subprocess")
    mocked_subprocess.check_output = mocker.Mock(return_value=version)

    assert sandboxjs.check_js_threshold_version("node") == supported


def test_value_from_two_concatenated_expressions() -> None:
    factory = Factory()
    echo = factory.make(get_data("tests/wf/vf-concat.cwl"))
    file = {"class": "File", "location": get_data("tests/wf/whale.txt")}

    assert echo(file1=file) == {"out": "a string\n"}


def test_caches_js_processes(mocker: Any) -> None:
    sandboxjs.exec_js_process("7", context="{}")

    mocked_new_js_proc = mocker.patch("cwltool.sandboxjs.new_js_proc")
    sandboxjs.exec_js_process("7", context="{}")

    mocked_new_js_proc.assert_not_called()
