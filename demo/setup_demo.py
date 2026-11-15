#!/usr/bin/env python3
"""Copy demo/context to a folder and add the placeholder .env file.

The repository does not track a file named .env (it would trip secret scanners),
so the demo creates it on demand:

    python3 demo/setup_demo.py /tmp/bca-demo
    python3 skills/build-context-audit/scripts/audit.py /tmp/bca-demo

DEST may be a new path, an empty folder, or an earlier demo copy (only demo files
and .env inside). Anything else is left untouched and the exit code is 2.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
SOURCE = DEMO_DIR / "context"
ENV_TEXT = "APP_MODE=demo\n"  # placeholder value, not a real secret

# 언어 선택은 스킬과 같은 규칙을 쓴다(스킬 파일은 고치지 않고 가져다 쓰기만 한다)
sys.path.insert(0, str(DEMO_DIR.parent / "skills" / "build-context-audit" / "scripts"))
from _i18n import LANGS, resolve_lang  # noqa: E402

# 이 스크립트가 화면에 내는 문구는 모두 이 표에 있다(두 언어의 키가 같아야 한다)
MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "help.description": "Copy demo/context to DEST and add the placeholder .env file that the repository does not track.",
        "help.epilog": (
            "DEST may be a new path, an empty folder, or an earlier demo copy (only demo files and .env inside). "
            "An earlier copy is written again, so changes you made to its demo files are lost. "
            "Anything else (other files, a file, a symbolic link, demo/context itself, a path inside it "
            "or a folder that contains it) "
            "is left untouched and the exit code is 2."
        ),
        "help.dest": "folder to create, for example /tmp/bca-demo",
        "help.lang": "message language, en or ko (default: BUILD_CONTEXT_AUDIT_LANG, then LC_ALL, LC_MESSAGES, LANG)",
        "help.help": "show this help message and exit",
        "error.not_demo_copy": "error: {dest} already exists and is not a demo copy; choose a new folder or remove it yourself",
        "error.cannot_create": "error: cannot create {dest}: {reason}",
    },
    "ko": {
        "help.description": "demo/context 를 DEST 로 복사하고, 레포가 추적하지 않는 자리표시자 .env 파일을 만듭니다.",
        "help.epilog": (
            "DEST 는 새 경로, 빈 폴더, 이전 데모 복사본(안에 데모 파일과 .env 만 있음) 중 하나여야 합니다. "
            "이전 복사본은 다시 쓰므로 그 안의 데모 파일에 고친 내용은 사라집니다. "
            "그 밖의 경우(다른 파일이 있음, 파일, 심볼릭 링크, demo/context 자신, 그 안의 경로, 그것을 담은 폴더)는 "
            "아무것도 건드리지 않고 종료 코드 2 로 끝납니다."
        ),
        "help.dest": "만들 폴더 (예: /tmp/bca-demo)",
        "help.lang": "메시지 언어 en 또는 ko (기본: BUILD_CONTEXT_AUDIT_LANG, LC_ALL, LC_MESSAGES, LANG 순)",
        "help.help": "도움말을 표시하고 종료",
        "error.not_demo_copy": "오류: {dest} 가 이미 있고 데모 복사본이 아닙니다. 새 폴더를 고르거나 직접 지우세요",
        "error.cannot_create": "오류: {dest} 를 만들 수 없습니다: {reason}",
    },
}


def t(lang: str, key: str, **kwargs: object) -> str:
    return MESSAGES[lang][key].format(**kwargs)


class Refused(Exception):
    """DEST must not be touched; ``key`` names the message in MESSAGES."""

    def __init__(self, key: str, dest: Path) -> None:
        super().__init__(t("en", key, dest=dest))
        self.key = key
        self.dest = dest


def demo_entries() -> tuple[set[str], set[str]]:
    """Relative paths (files, folders) that a demo copy may hold: demo/context plus .env."""
    files: set[str] = {".env"}
    folders: set[str] = set()
    for root, dirnames, filenames in os.walk(SOURCE):
        here = Path(root).relative_to(SOURCE)
        folders.update((here / name).as_posix() for name in dirnames)
        files.update((here / name).as_posix() for name in filenames)
    return files, folders


def holds_only_demo_files(dest: Path) -> bool:
    """True when every entry below ``dest`` is a demo file or folder of the same kind (an empty folder counts)."""
    files, folders = demo_entries()
    unreadable: list[OSError] = []
    for root, dirnames, filenames in os.walk(dest, onerror=unreadable.append):
        here = Path(root).relative_to(dest)
        for name in dirnames:
            # 링크는 따라가지 않는다: 데모 복사본에는 링크가 없으니 링크가 있으면 사용자 폴더다
            if (Path(root) / name).is_symlink() or (here / name).as_posix() not in folders:
                return False
        for name in filenames:
            path = Path(root) / name
            if path.is_symlink() or not path.is_file() or (here / name).as_posix() not in files:
                return False
    return not unreadable  # 읽지 못한 하위 폴더가 있으면 무엇이 들었는지 모르므로 거부


def _same_folder(a: Path, b: Path) -> bool:
    """Same file system object (also catches 'demo/Context' on a case-insensitive disk)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False  # 없는 경로는 같은 폴더가 아니다


def check(dest: Path) -> None:
    """Raise Refused unless ``dest`` is new, an empty folder, or an earlier demo copy."""
    if dest.is_symlink():
        raise Refused("error.not_demo_copy", dest)  # 링크가 가리키는 곳은 건드리지 않는다(빈 폴더를 가리켜도)
    source = Path(os.path.realpath(SOURCE))
    if any(_same_folder(dest, folder) for folder in (source, *source.parents)):
        raise Refused("error.not_demo_copy", dest)  # demo/context 자신, demo/, 레포 루트 같은 상위 폴더
    if any(_same_folder(folder, source) for folder in Path(os.path.realpath(dest)).parents):
        raise Refused("error.not_demo_copy", dest)  # 추적되는 데모 폴더 안에는 만들지 않는다(plan 대로 같은 문구)
    if not dest.exists():
        return  # 새 경로
    if not dest.is_dir() or not holds_only_demo_files(dest):
        raise Refused("error.not_demo_copy", dest)  # 파일이거나, 데모가 아닌 것이 하나라도 있다


def build(dest: Path) -> Path:
    """Create ``dest`` as a full demo context (copy + .env) and return it; raise Refused if it is not safe."""
    check(dest)
    if dest.is_dir():
        # 여기 왔다면 안에는 데모 파일만 있다. 지우는 것은 그 데모 파일들뿐이고 폴더는 그대로 둔다
        files, _ = demo_entries()
        for rel in sorted(files):
            old = dest / rel
            if old.is_file() and not old.is_symlink():
                old.unlink()
    shutil.copytree(SOURCE, dest, dirs_exist_ok=True)
    (dest / ".env").write_text(ENV_TEXT, encoding="utf-8")
    return dest


def _lang_in_argv(argv: Sequence[str]) -> str | None:
    """Find --lang before argparse runs, so the help text itself can be translated."""
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def build_parser(lang: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="setup_demo.py",
        description=t(lang, "help.description"),
        epilog=t(lang, "help.epilog"),
        allow_abbrev=False,
        add_help=False,
    )
    p.add_argument("-h", "--help", action="help", help=t(lang, "help.help"))
    p.add_argument("dest", metavar="DEST", help=t(lang, "help.dest"))
    p.add_argument("--lang", choices=list(LANGS), help=t(lang, "help.lang"))
    return p


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    args_list = list(sys.argv[1:] if argv is None else argv)
    lang = resolve_lang(_lang_in_argv(args_list), env)
    try:
        args = build_parser(lang).parse_args(args_list)
    except SystemExit as stop:  # -h 는 도움말 후 0, 잘못된 인자는 usage 후 2
        return 0 if stop.code in (0, None) else 2
    lang = resolve_lang(args.lang, env)
    dest = Path(args.dest)
    try:
        build(dest)
    except Refused as refused:
        print(t(lang, refused.key, dest=dest), file=sys.stderr)
        return 2
    except OSError as exc:  # 권한 없음, 상위 경로가 파일 등: 트레이스백 대신 한 줄
        print(t(lang, "error.cannot_create", dest=dest, reason=exc.strerror or exc), file=sys.stderr)
        return 2
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
