"""Build novacoind from the bundled C++ sources.

The GUI does not ship a prebuilt daemon.  This helper configures the
standalone headless CMake project in ``novacoin-master/src`` and copies the
resulting binary to ``bin`` so that the normal GUI discovery order finds it on
the next start.  The headless project avoids the Qt5 build requirements of the
full wallet build.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "novacoin-master" / "src"
DEFAULT_BUILD = ROOT / "build" / "novacoind"
DEFAULT_OUTPUT = ROOT / "bin"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Read command line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="path to the novacoin source tree",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=DEFAULT_BUILD,
        help="CMake build directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="directory for the finished novacoind binary",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=os.cpu_count() or 2,
        help="parallel compiler jobs",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="remove the build directory before configuring",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the commands without executing them",
    )
    return parser.parse_args(argv)


def detect_cmake_args(root: Path) -> list[str]:
    """Add local library and Berkeley DB hints for common Linux layouts."""
    args: list[str] = []
    liboqs_root = Path(os.environ.get("LIBOQS_DIR", root / ".deps" / "liboqs"))
    liboqs_config = liboqs_root / "lib" / "cmake" / "liboqs"
    if liboqs_config.is_dir():
        args.append(f"-Dliboqs_DIR={liboqs_config}")
    for include_dir in (Path("/usr/include/db5.3"), Path("/usr/include")):
        if (include_dir / "db_cxx.h").is_file():
            args.append(f"-DBerkeleyDB_INC={include_dir}")
            break
    for lib_dir in (Path("/usr/lib"), Path("/usr/lib64")):
        candidates = sorted(lib_dir.glob("libdb_cxx-*.so"))
        if candidates:
            library = max(candidates, key=lambda path: len(path.name))
            args.extend(
                [
                    f"-DBerkeleyDB_LIBS={lib_dir}",
                    f"-DBerkeleyDB_LIB_name={library.stem}",
                ]
            )
            break
    return args


def run(command: list[str], workdir: Path, dry_run: bool) -> None:
    """Run one build command, aborting on a non-zero exit code."""
    printable = " ".join(str(item) for item in command)
    print(f"[phoenix] {printable}")
    if dry_run:
        return
    try:
        subprocess.run(command, cwd=workdir, check=True)
    except FileNotFoundError as error:
        raise SystemExit(f"Не найдена команда: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"Сборка остановлена с кодом {error.returncode}") from error


def main(argv: list[str] | None = None) -> int:
    """Configure, build and install the daemon."""
    args = parse_args(argv)
    source = args.source.resolve()
    build_dir = args.build_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not (source / "CMakeLists.txt").is_file():
        print(f"Не найден CMakeLists.txt в {source}", file=sys.stderr)
        return 2
    if args.clean and build_dir.exists() and not args.dry_run:
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    run(
        [
            "cmake",
            "-S",
            str(source),
            "-B",
            str(build_dir),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DWITH_TOOLS=NO",
            *detect_cmake_args(ROOT),
        ],
        ROOT,
        args.dry_run,
    )
    run(
        [
            "cmake",
            "--build",
            str(build_dir),
            "--target",
            "novacoind",
            "--parallel",
            str(max(1, args.jobs)),
        ],
        ROOT,
        args.dry_run,
    )

    candidates = (
        build_dir / "novacoind",
        build_dir / "novacoind.exe",
        build_dir / "src" / "novacoind",
        build_dir / "src" / "novacoind.exe",
    )
    binary = next((path for path in candidates if path.is_file()), None)
    if binary is None:
        if args.dry_run:
            binary = candidates[0]
        else:
            print(
                "Сборка завершилась, но бинарник novacoind не найден.", file=sys.stderr
            )
            return 1
    target = output_dir / binary.name
    print(f"[phoenix] Копирование {binary} -> {target}")
    if not args.dry_run:
        shutil.copy2(binary, target)
        target.chmod(target.stat().st_mode | 0o755)
        print(f"[phoenix] Готово: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
