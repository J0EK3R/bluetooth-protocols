"""
Build and run the host test driver of the pure C firmware logic
(tests/c/follow_driver.c). Used by test_ble_csa.py and test_ble_follow.py to
compare the C code with the Python models.

The driver needs a host C compiler (cc / gcc / clang); without one
`driver_path()` returns None and the tests that need it are skipped.
"""

import os
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRMWARE_SRC = os.path.join(HERE, "..", "firmware", "src")
SOURCES = [os.path.join(HERE, "c", "follow_driver.c")] + [
    os.path.join(FIRMWARE_SRC, name) for name in ("ble_csa.c", "ble_pdu.c", "ble_follow.c")]

_built = None            # (path or None) after the first attempt
_tmpdir = None


def driver_path():
    """Compile the driver once per test run; returns its path or None (no compiler)."""
    global _built, _tmpdir
    if _built is not None:
        return _built or None
    compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if compiler is None:
        _built = ""
        return None
    _tmpdir = tempfile.mkdtemp(prefix="follow_driver_")
    exe = os.path.join(_tmpdir, "follow_driver")
    # strict warnings: the same C files are built with warnings visible in the firmware build
    cmd = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", FIRMWARE_SRC,
           *SOURCES, "-o", exe]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("host build of the C logic failed:\n" + result.stderr)
    _built = exe
    return exe


def run_script(lines):
    """Feed script lines to the C driver and return its output lines."""
    exe = driver_path()
    result = subprocess.run([exe], input="\n".join(lines) + "\n", capture_output=True,
                            text=True, check=True)
    return result.stdout.splitlines()
