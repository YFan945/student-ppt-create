"""Build and invoke the suite-owned Open XML SDK schema validator."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

OPENXML_SDK_VERSION = "3.5.1"


def _project_root() -> Path:
    return Path(__file__).with_name("openxml_validator")


def managed_dotnet_root() -> Path:
    configured = os.environ.get("STUDENT_PRESENTATION_DOTNET_ROOT")
    if configured:
        return Path(configured).expanduser()
    local_data = os.environ.get("LOCALAPPDATA")
    if local_data:
        return Path(local_data) / "student-presentation-suite" / "dotnet"
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base / "student-presentation-suite" / "dotnet"


def _dotnet() -> str:
    names = ("dotnet.exe", "dotnet") if os.name == "nt" else ("dotnet",)
    candidates = [
        *(Path(root) / name for root in filter(None, [os.environ.get("DOTNET_ROOT")]) for name in names),
        *(managed_dotnet_root() / name for name in names),
    ]
    executable = next((str(path) for path in candidates if path.is_file()), None) or shutil.which("dotnet")
    if not executable or not _has_sdk(executable):
        raise RuntimeError("dotnet 8+ is required for complete Open XML schema validation")
    return executable


def _has_sdk(executable: str) -> bool:
    try:
        completed = subprocess.run(
            [executable, "--list-sdks"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and any(
        line.partition(".")[0].isdigit() and int(line.partition(".")[0]) >= 8
        for line in completed.stdout.splitlines()
    )


def dotnet_sdk_path() -> str | None:
    try:
        return _dotnet()
    except RuntimeError:
        return None


def build_openxml_validator() -> Path:
    project = _project_root()
    sources = [
        project / "OpenXmlValidator.csproj",
        project / "Program.cs",
        project / "packages.lock.json",
    ]
    if not all(path.is_file() for path in sources):
        raise RuntimeError("Open XML validator source files are missing")
    digest = hashlib.sha256(b"".join(path.read_bytes() for path in sources)).hexdigest()[:16]
    output = Path(tempfile.gettempdir()) / "student-presentation-suite" / "openxml" / digest
    assembly = output / "OpenXmlValidator.dll"
    if assembly.is_file():
        return assembly
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True)
    completed = subprocess.run(
        [
            _dotnet(),
            "publish",
            str(sources[0]),
            "--configuration",
            "Release",
            "--framework",
            "net8.0",
            "--output",
            str(temporary),
            "--property:RestoreLockedMode=true",
            f"--property:BaseIntermediateOutputPath={temporary / 'obj'}{os.sep}",
            f"--property:BaseOutputPath={temporary / 'bin'}{os.sep}",
            "--nologo",
            "--verbosity",
            "quiet",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if completed.returncode or not (temporary / assembly.name).is_file():
        shutil.rmtree(temporary, ignore_errors=True)
        detail = completed.stderr or completed.stdout or "dotnet publish produced no output"
        raise RuntimeError(f"failed to build Open XML validator: {detail.strip()}")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Windows AV transiently locks a freshly written assembly (same flake
        # class build.py fixed for deck.pptx): retry the swap before giving up.
        last_error: OSError | None = None
        for _ in range(6):
            try:
                temporary.replace(output)
                last_error = None
                break
            except OSError as exc:
                last_error = exc
                time.sleep(0.3)
        if last_error is not None:
            raise last_error
    except OSError:
        if not assembly.is_file():
            raise
        shutil.rmtree(temporary, ignore_errors=True)
    return assembly


def validate_openxml(path: Path) -> dict:
    assembly = build_openxml_validator()
    completed = subprocess.run(
        [_dotnet(), str(assembly), str(path.resolve())],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Open XML validator returned invalid JSON: "
            + (completed.stderr or completed.stdout or "empty output").strip()
        ) from exc
    if completed.returncode not in {0, 1, 2}:
        raise RuntimeError(
            f"Open XML validator exited with {completed.returncode}: "
            + (completed.stderr or completed.stdout).strip()
        )
    result["performed"] = True
    result["sdk_package_version"] = OPENXML_SDK_VERSION
    return result
