#!/usr/bin/env python3
"""The platform BEES is built and verified on, and the names of its goldens.

A golden is the recorded expected output of a trial entry: NAME.scout (stdout+stderr+exit code) and NAME.golden_fail (a compile-fail
trial's diagnostics). Its file name carries the platform identifier right before the extension, the way Silica names its own
(test.macos_applesilicon.sout): NAME.macos_applesilicon.scout, so goldens of several platforms sit in one directory and a run compares
only against its own platform's. tools/platform.mk is the same table for make.

    platform_id.py id          print the current platform's identifier
    platform_id.py native      print the current platform's native/ directory name
    platform_id.py golden NAME.scout [ID]   print NAME.ID.scout
"""
import os
import platform
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# id -> (native/ directory, uname -s, uname -m, build supported)
#
# BUILD SUPPORT SWITCH (the last field): tools/run_all_trials.sh runs the trials of a platform whose switch is True, here or on
# the remote machines of .bees_build_hosts (a line there names its platform id), and reports the others SKIPPED. linux_x86_64 is
# True since 2026-11-18: native/linux/ has its platform.mk and sources and the trials pass on Linux with their own goldens
# (NAME.linux_x86_64.scout). A board's switch flips the same way when its native/ directory and goldens exist.
PLATFORMS = {
    "macos_applesilicon": ("macos", "Darwin", "arm64", True),
    "linux_x86_64": ("linux", "Linux", "x86_64", True),
    "esp32s3": ("esp32s3", None, None, False),
    "nucleo": ("nucleo", None, None, False),
}

GOLDEN_EXTENSIONS = (".scout", ".golden_fail")


def current_id():
    """The identifier of this machine's platform, from uname; BEES_PLATFORM_ID in the environment overrides it."""
    env = os.environ.get("BEES_PLATFORM_ID")
    if env:
        return env
    key = (platform.system(), platform.machine())
    for pid, (_, s, m, _) in PLATFORMS.items():
        if (s, m) == key:
            return pid
    raise SystemExit(f"platform_id: no BEES platform for {key[0]}/{key[1]}; set BEES_PLATFORM_ID")


def native_dir(pid=None):
    return PLATFORMS[pid or current_id()][0]


def build_supported(pid):
    return PLATFORMS[pid][3] if pid in PLATFORMS else False


def golden_name(name, pid=None):
    """NAME.scout -> NAME.<id>.scout (also .golden_fail); a directory part is kept. A name already carrying an identifier, or not a
    golden, is a ValueError."""
    pid = pid or current_id()
    base, ext = os.path.splitext(name)
    if ext not in GOLDEN_EXTENSIONS:
        raise ValueError(f"{name}: not a golden (extensions {GOLDEN_EXTENSIONS})")
    if os.path.splitext(base)[1] == "." + pid:
        raise ValueError(f"{name}: already carries the platform identifier {pid}")
    return f"{base}.{pid}{ext}"


def golden_platform(name):
    """The platform identifier of a golden file name, or None when it has none (NAME.scout)."""
    base, ext = os.path.splitext(name)
    if ext not in GOLDEN_EXTENSIONS:
        return None
    infix = os.path.splitext(base)[1][1:]
    return infix if infix in PLATFORMS else None


def main(argv):
    if len(argv) >= 2 and argv[1] == "id":
        print(current_id())
    elif len(argv) >= 2 and argv[1] == "native":
        print(native_dir())
    elif len(argv) >= 3 and argv[1] == "golden":
        print(golden_name(argv[2], argv[3] if len(argv) > 3 else None))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
