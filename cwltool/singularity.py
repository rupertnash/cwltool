"""Support for executing Docker containers using the Singularity 2.x engine."""

import os
import os.path
import re
import shutil
import sys
from subprocess import (  # nosec
    DEVNULL,
    PIPE,
    Popen,
    TimeoutExpired,
    check_call,
    check_output,
)
from typing import Callable, Dict, List, MutableMapping, Optional, Tuple, cast

from schema_salad.sourceline import SourceLine

from .builder import Builder
from .context import RuntimeContext
from .errors import UnsupportedRequirement, WorkflowException
from .job import ContainerCommandLineJob
from .loghandler import _logger
from .pathmapper import MapperEnt, PathMapper
from .utils import CWLObjectType, create_tmp_dir, ensure_non_writable, ensure_writable

_USERNS = None  # type: Optional[bool]
_SINGULARITY_VERSION = ""


def _singularity_supports_userns() -> bool:
    global _USERNS  # pylint: disable=global-statement
    if _USERNS is None:
        try:
            hello_image = os.path.join(os.path.dirname(__file__), "hello.simg")
            result = Popen(  # nosec
                ["singularity", "exec", "--userns", hello_image, "true"],
                stderr=PIPE,
                stdout=DEVNULL,
                universal_newlines=True,
            ).communicate(timeout=60)[1]
            _USERNS = (
                "No valid /bin/sh" in result
                or "/bin/sh doesn't exist in container" in result
                or "executable file not found in" in result
            )
        except TimeoutExpired:
            _USERNS = False
    return _USERNS


def get_version() -> str:
    global _SINGULARITY_VERSION  # pylint: disable=global-statement
    if not _SINGULARITY_VERSION:
        _SINGULARITY_VERSION = check_output(  # nosec
            ["singularity", "--version"], universal_newlines=True
        )
        if _SINGULARITY_VERSION.startswith("singularity version "):
            _SINGULARITY_VERSION = _SINGULARITY_VERSION[20:]
    return _SINGULARITY_VERSION


def is_version_2_6() -> bool:
    return get_version().startswith("2.6")


def is_version_3_or_newer() -> bool:
    return int(get_version()[0]) >= 3


def is_version_3_1_or_newer() -> bool:
    version = get_version().split(".")
    return int(version[0]) >= 4 or (int(version[0]) == 3 and int(version[1]) >= 1)


def _normalize_image_id(string: str) -> str:
    return string.replace("/", "_") + ".img"


def _normalize_sif_id(string: str) -> str:
    return string.replace("/", "_") + ".sif"


class SingularityCommandLineJob(ContainerCommandLineJob):
    def __init__(
        self,
        builder: Builder,
        joborder: CWLObjectType,
        make_path_mapper: Callable[..., PathMapper],
        requirements: List[CWLObjectType],
        hints: List[CWLObjectType],
        name: str,
    ) -> None:
        """Builder for invoking the Singularty software container engine."""
        super().__init__(builder, joborder, make_path_mapper, requirements, hints, name)

    @staticmethod
    def get_image(
        dockerRequirement: Dict[str, str],
        pull_image: bool,
        force_pull: bool = False,
    ) -> bool:
        """
        Acquire the software container image in the specified dockerRequirement.

        Uses Singularity and returns the success as a bool. Updates the
        provided dockerRequirement with the specific dockerImageId to the full
        path of the local image, if found. Likewise the
        dockerRequirement['dockerPull'] is updated to a docker:// URI if needed.
        """
        found = False

        candidates = []

        cache_folder = None
        if "CWL_SINGULARITY_CACHE" in os.environ:
            cache_folder = os.environ["CWL_SINGULARITY_CACHE"]
        elif is_version_2_6() and "SINGULARITY_PULLFOLDER" in os.environ:
            cache_folder = os.environ["SINGULARITY_PULLFOLDER"]

        if (
            "dockerImageId" not in dockerRequirement
            and "dockerPull" in dockerRequirement
        ):
            match = re.search(
                pattern=r"([a-z]*://)", string=dockerRequirement["dockerPull"]
            )
            img_name = _normalize_image_id(dockerRequirement["dockerPull"])
            candidates.append(img_name)
            if is_version_3_or_newer():
                sif_name = _normalize_sif_id(dockerRequirement["dockerPull"])
                candidates.append(sif_name)
                dockerRequirement["dockerImageId"] = sif_name
            else:
                dockerRequirement["dockerImageId"] = img_name
            if not match:
                dockerRequirement["dockerPull"] = (
                    "docker://" + dockerRequirement["dockerPull"]
                )
        elif "dockerImageId" in dockerRequirement:
            if os.path.isfile(dockerRequirement["dockerImageId"]):
                found = True
            candidates.append(dockerRequirement["dockerImageId"])
            candidates.append(_normalize_image_id(dockerRequirement["dockerImageId"]))
            if is_version_3_or_newer():
                candidates.append(_normalize_sif_id(dockerRequirement["dockerPull"]))

        targets = [os.getcwd()]
        if "CWL_SINGULARITY_CACHE" in os.environ:
            targets.append(os.environ["CWL_SINGULARITY_CACHE"])
        if is_version_2_6() and "SINGULARITY_PULLFOLDER" in os.environ:
            targets.append(os.environ["SINGULARITY_PULLFOLDER"])
        for target in targets:
            for dirpath, _subdirs, files in os.walk(target):
                for entry in files:
                    if entry in candidates:
                        path = os.path.join(dirpath, entry)
                        if os.path.isfile(path):
                            _logger.info(
                                "Using local copy of Singularity image found in %s",
                                dirpath,
                            )
                            dockerRequirement["dockerImageId"] = path
                            found = True
        if (force_pull or not found) and pull_image:
            cmd = []  # type: List[str]
            if "dockerPull" in dockerRequirement:
                if cache_folder:
                    env = os.environ.copy()
                    if is_version_2_6():
                        env["SINGULARITY_PULLFOLDER"] = cache_folder
                        cmd = [
                            "singularity",
                            "pull",
                            "--force",
                            "--name",
                            dockerRequirement["dockerImageId"],
                            str(dockerRequirement["dockerPull"]),
                        ]
                    else:
                        cmd = [
                            "singularity",
                            "pull",
                            "--force",
                            "--name",
                            "{}/{}".format(
                                cache_folder, dockerRequirement["dockerImageId"]
                            ),
                            str(dockerRequirement["dockerPull"]),
                        ]

                    _logger.info(str(cmd))
                    check_call(cmd, env=env, stdout=sys.stderr)  # nosec
                    dockerRequirement["dockerImageId"] = "{}/{}".format(
                        cache_folder, dockerRequirement["dockerImageId"]
                    )
                    found = True
                else:
                    cmd = [
                        "singularity",
                        "pull",
                        "--force",
                        "--name",
                        str(dockerRequirement["dockerImageId"]),
                        str(dockerRequirement["dockerPull"]),
                    ]
                    _logger.info(str(cmd))
                    check_call(cmd, stdout=sys.stderr)  # nosec
                    found = True

            elif "dockerFile" in dockerRequirement:
                raise WorkflowException(
                    SourceLine(dockerRequirement, "dockerFile").makeError(
                        "dockerFile is not currently supported when using the "
                        "Singularity runtime for Docker containers."
                    )
                )
            elif "dockerLoad" in dockerRequirement:
                if is_version_3_1_or_newer():
                    if "dockerImageId" in dockerRequirement:
                        name = "{}.sif".format(dockerRequirement["dockerImageId"])
                    else:
                        name = "{}.sif".format(dockerRequirement["dockerLoad"])
                    cmd = [
                        "singularity",
                        "build",
                        name,
                        "docker-archive://{}".format(dockerRequirement["dockerLoad"]),
                    ]
                    _logger.info(str(cmd))
                    check_call(cmd, stdout=sys.stderr)  # nosec
                    found = True
                    dockerRequirement["dockerImageId"] = name
                raise WorkflowException(
                    SourceLine(dockerRequirement, "dockerLoad").makeError(
                        "dockerLoad is not currently supported when using the "
                        "Singularity runtime (version less than 3.1) for Docker containers."
                    )
                )
            elif "dockerImport" in dockerRequirement:
                raise WorkflowException(
                    SourceLine(dockerRequirement, "dockerImport").makeError(
                        "dockerImport is not currently supported when using the "
                        "Singularity runtime for Docker containers."
                    )
                )

        return found

    def get_from_requirements(
        self,
        r: CWLObjectType,
        pull_image: bool,
        force_pull: bool,
        tmp_outdir_prefix: str,
    ) -> Optional[str]:
        """
        Return the filename of the Singularity image.

        (e.g. hello-world-latest.{img,sif}).
        """
        if not bool(shutil.which("singularity")):
            raise WorkflowException("singularity executable is not available")

        if not self.get_image(cast(Dict[str, str], r), pull_image, force_pull):
            raise WorkflowException(
                "Container image {} not found".format(r["dockerImageId"])
            )

        return os.path.abspath(cast(str, r["dockerImageId"]))

    @staticmethod
    def append_volume(
        runtime: List[str], source: str, target: str, writable: bool = False
    ) -> None:
        runtime.append("--bind")
        runtime.append(
            "{}:{}:{}".format(
                source,
                target,
                "rw" if writable else "ro",
            )
        )

    def add_file_or_directory_volume(
        self, runtime: List[str], volume: MapperEnt, host_outdir_tgt: Optional[str]
    ) -> None:
        if host_outdir_tgt is not None:
            # workaround for lack of overlapping mounts in Singularity
            # revert to daa923d5b0be3819b6ed0e6440e7193e65141052
            # once https://github.com/sylabs/singularity/issues/1607
            # is fixed
            if volume.type == "File":
                shutil.copy(volume.resolved, host_outdir_tgt)
            else:
                shutil.copytree(volume.resolved, host_outdir_tgt)
            ensure_non_writable(host_outdir_tgt)
        elif not volume.resolved.startswith("_:"):
            self.append_volume(runtime, volume.resolved, volume.target)

    def add_writable_file_volume(
        self,
        runtime: List[str],
        volume: MapperEnt,
        host_outdir_tgt: Optional[str],
        tmpdir_prefix: str,
    ) -> None:
        if host_outdir_tgt is not None:
            # workaround for lack of overlapping mounts in Singularity
            # revert to daa923d5b0be3819b6ed0e6440e7193e65141052
            # once https://github.com/sylabs/singularity/issues/1607
            # is fixed
            if self.inplace_update:
                try:
                    os.link(os.path.realpath(volume.resolved), host_outdir_tgt)
                except os.error:
                    shutil.copy(volume.resolved, host_outdir_tgt)
            else:
                shutil.copy(volume.resolved, host_outdir_tgt)
            ensure_writable(host_outdir_tgt)
        elif self.inplace_update:
            self.append_volume(runtime, volume.resolved, volume.target, writable=True)
            ensure_writable(volume.resolved)
        else:
            file_copy = os.path.join(
                create_tmp_dir(tmpdir_prefix),
                os.path.basename(volume.resolved),
            )
            shutil.copy(volume.resolved, file_copy)
            # volume.resolved = file_copy
            self.append_volume(runtime, file_copy, volume.target, writable=True)
            ensure_writable(file_copy)

    def add_writable_directory_volume(
        self,
        runtime: List[str],
        volume: MapperEnt,
        host_outdir_tgt: Optional[str],
        tmpdir_prefix: str,
    ) -> None:
        if volume.resolved.startswith("_:"):
            if host_outdir_tgt is not None:
                new_dir = host_outdir_tgt
            else:
                new_dir = os.path.join(
                    create_tmp_dir(tmpdir_prefix),
                    os.path.basename(volume.resolved),
                )
            os.makedirs(new_dir)
        else:
            if host_outdir_tgt is not None:
                # workaround for lack of overlapping mounts in Singularity
                # revert to daa923d5b0be3819b6ed0e6440e7193e65141052
                # once https://github.com/sylabs/singularity/issues/1607
                # is fixed
                shutil.copytree(volume.resolved, host_outdir_tgt)
                ensure_writable(host_outdir_tgt)
            else:
                if not self.inplace_update:
                    dir_copy = os.path.join(
                        create_tmp_dir(tmpdir_prefix),
                        os.path.basename(volume.resolved),
                    )
                    shutil.copytree(volume.resolved, dir_copy)
                    source = dir_copy
                    # volume.resolved = dir_copy
                else:
                    source = volume.resolved
                self.append_volume(runtime, source, volume.target, writable=True)
                ensure_writable(source)

    def _required_env(self) -> Dict[str, str]:
        return {
            "TMPDIR": self.CONTAINER_TMPDIR,
            "HOME": self.builder.outdir,
        }

    def create_runtime(
        self, env: MutableMapping[str, str], runtime_context: RuntimeContext
    ) -> Tuple[List[str], Optional[str]]:
        """Return the Singularity runtime list of commands and options."""
        any_path_okay = self.builder.get_requirement("DockerRequirement")[1] or False
        runtime = [
            "singularity",
            "--quiet",
            "exec",
            "--contain",
            "--ipc",
            "--cleanenv",
        ]
        if _singularity_supports_userns():
            runtime.append("--userns")
        else:
            runtime.append("--pid")

        container_HOME: Optional[str] = None
        if is_version_3_1_or_newer():
            # Remove HOME, as passed in a special way (restore it below)
            container_HOME = self.environment.pop("HOME")
            runtime.append("--home")
            runtime.append(
                "{}:{}".format(
                    os.path.realpath(self.outdir),
                    container_HOME,
                )
            )
        else:
            runtime.append("--bind")
            runtime.append(
                "{}:{}:rw".format(
                    os.path.realpath(self.outdir),
                    self.builder.outdir,
                )
            )
        runtime.append("--bind")
        runtime.append(
            "{}:{}:rw".format(
                os.path.realpath(self.tmpdir),
                self.CONTAINER_TMPDIR,
            )
        )

        self.add_volumes(
            self.pathmapper,
            runtime,
            any_path_okay=True,
            secret_store=runtime_context.secret_store,
            tmpdir_prefix=runtime_context.tmpdir_prefix,
        )
        if self.generatemapper is not None:
            self.add_volumes(
                self.generatemapper,
                runtime,
                any_path_okay=any_path_okay,
                secret_store=runtime_context.secret_store,
                tmpdir_prefix=runtime_context.tmpdir_prefix,
            )

        runtime.append("--pwd")
        runtime.append(self.builder.outdir)

        if runtime_context.custom_net:
            raise UnsupportedRequirement(
                "Singularity implementation does not support custom networking"
            )
        elif runtime_context.disable_net:
            runtime.append("--net")

        for name, value in self.environment.items():
            env[f"SINGULARITYENV_{name}"] = str(value)

        if container_HOME:
            # Restore HOME if we removed it above.
            self.environment["HOME"] = container_HOME
        return (runtime, None)
