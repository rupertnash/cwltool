import copy
import os.path
import subprocess


def install_udocker(docker_install_dir: str) -> str:
    """Install udocker from the internet"""
    url = "https://raw.githubusercontent.com/jorge-lip/udocker-builds/master/tarballs/udocker-1.1.4.tar.gz"
    install_cmds = [
        ["curl", url, "-o", "./udocker-tarball.tgz"],
        ["tar", "xzvf", "udocker-tarball.tgz", "udocker"],
        [
            "bash",
            "-c",
            f"UDOCKER_TARBALL={docker_install_dir}/udocker-tarball.tgz ./udocker install",
        ],
        ["rm", f"{docker_install_dir}/udocker-tarball.tgz"],
    ]

    orig_environ = copy.copy(os.environ)
    os.environ["UDOCKER_DIR"] = os.path.join(docker_install_dir, ".udocker")
    os.environ["HOME"] = docker_install_dir
    orig_dir = os.getcwd()
    if not os.path.exists(docker_install_dir):
        os.makedirs(docker_install_dir)
    os.chdir(docker_install_dir)

    results = []
    for _ in range(3):
        results = [subprocess.call(cmds) for cmds in install_cmds]
        if sum(results) == 0:
            break
        subprocess.call(["rm", "./udocker"])

    assert sum(results) == 0

    udocker_path = os.path.join(docker_install_dir, "udocker")
    os.chdir(orig_dir)
    os.environ = orig_environ
    return udocker_path


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("dest_dir")
    args = p.parse_args()

    install_udocker(args.dest_dir)
