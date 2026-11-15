"""AC-2: demo/setup_demo.py creates or re-creates a demo copy and leaves every other folder alone."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import setup_demo
from conftest import REPO, SOURCE_DEMO

SCRIPT = REPO / "demo" / "setup_demo.py"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def run(capsys, *argv: str, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    """Call setup_demo.main in-process; returns (exit code, stdout, stderr)."""
    code = setup_demo.main(list(argv), env={"LANG": "C"} if env is None else env)
    out = capsys.readouterr()
    return code, out.out, out.err


def snapshot(folder: Path) -> dict[str, object]:
    """Every entry below ``folder``: file bytes, link targets and folder markers (links are not followed)."""
    found: dict[str, object] = {}
    for root, dirnames, filenames in os.walk(folder):
        for name in dirnames + filenames:
            path = Path(root) / name
            rel = path.relative_to(folder).as_posix()
            if path.is_symlink():
                found[rel] = ("link", os.readlink(path))
            elif path.is_dir():
                found[rel] = "dir"
            else:
                found[rel] = path.read_bytes()
    return found


def demo_files() -> set[str]:
    return {p.relative_to(SOURCE_DEMO).as_posix() for p in SOURCE_DEMO.rglob("*") if p.is_file()} | {".env"}


def copy_files(dest: Path) -> set[str]:
    return {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}


def refusal(dest: Path, lang: str = "en") -> str:
    return setup_demo.t(lang, "error.not_demo_copy", dest=dest) + "\n"


# --- folders it may create or re-create ------------------------------------------------------


def test_new_folder_gets_the_demo_files_and_env(tmp_path, capsys):
    dest = tmp_path / "new" / "deeper"  # missing parent folders are created too
    code, out, err = run(capsys, str(dest))
    assert (code, out, err) == (0, f"{dest}\n", "")
    assert copy_files(dest) == demo_files()
    assert (dest / ".env").read_text(encoding="utf-8") == "APP_MODE=demo\n"
    assert (dest / "app" / "config.yaml").read_bytes() == (SOURCE_DEMO / "app" / "config.yaml").read_bytes()


def test_empty_folder_is_filled(tmp_path, capsys):
    dest = tmp_path / "empty"
    dest.mkdir()
    assert run(capsys, str(dest))[0] == 0
    assert copy_files(dest) == demo_files()


def test_rerun_rewrites_an_earlier_copy(tmp_path, capsys):
    dest = tmp_path / "bca-demo"
    assert run(capsys, str(dest))[0] == 0
    (dest / "app" / "main.py").write_text("changed\n", encoding="utf-8")
    (dest / "docs" / "guide.md").unlink()
    (dest / ".env").unlink()
    assert run(capsys, str(dest))[0] == 0  # the README line can be run again and again
    assert snapshot(dest) == snapshot(setup_demo.build(tmp_path / "fresh"))


def test_a_partial_copy_still_counts_as_a_demo_copy(tmp_path, capsys):
    dest = tmp_path / "partial"
    (dest / "app").mkdir(parents=True)
    (dest / "app" / "main.py").write_text("half written\n", encoding="utf-8")
    (dest / ".env").write_text("APP_MODE=demo\n", encoding="utf-8")
    assert run(capsys, str(dest))[0] == 0
    assert copy_files(dest) == demo_files()


# --- folders it must leave alone --------------------------------------------------------------


@pytest.mark.parametrize("extra", ["userwork/notes.txt", "notes.txt", "app/extra.py", ".DS_Store"])
def test_any_other_file_blocks_and_nothing_changes(tmp_path, capsys, extra):
    dest = setup_demo.build(tmp_path / "bca-demo")
    (dest / extra).parent.mkdir(parents=True, exist_ok=True)
    (dest / extra).write_text("mine\n", encoding="utf-8")
    (dest / "app" / "main.py").write_text("my edit\n", encoding="utf-8")
    before = snapshot(dest)
    code, out, err = run(capsys, str(dest))
    assert (code, out, err) == (2, "", refusal(dest))
    assert snapshot(dest) == before  # nothing deleted, nothing written
    assert (dest / extra).read_text(encoding="utf-8") == "mine\n"


def test_an_extra_empty_folder_blocks(tmp_path, capsys):
    dest = setup_demo.build(tmp_path / "bca-demo")
    (dest / "userdir").mkdir()
    assert run(capsys, str(dest))[0] == 2
    assert (dest / "userdir").is_dir()


def test_a_demo_name_with_the_wrong_kind_blocks(tmp_path, capsys):
    dest = tmp_path / "odd"
    dest.mkdir()
    (dest / "app").write_text("a file where the demo has a folder\n", encoding="utf-8")
    assert run(capsys, str(dest))[0] == 2
    assert (dest / "app").read_text(encoding="utf-8").startswith("a file")


def test_a_link_inside_blocks_and_its_target_stays(tmp_path, capsys):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep\n", encoding="utf-8")
    dest = setup_demo.build(tmp_path / "bca-demo")
    (dest / "app" / "main.py").unlink()
    (dest / "app" / "main.py").symlink_to(outside / "keep.txt")  # a demo name, but a link
    assert run(capsys, str(dest))[0] == 2
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    assert (dest / "app" / "main.py").is_symlink()


def test_dest_that_is_a_file_is_refused(tmp_path, capsys):
    dest = tmp_path / "notes.txt"
    dest.write_text("mine\n", encoding="utf-8")
    code, out, err = run(capsys, str(dest))
    assert (code, out, err) == (2, "", refusal(dest))
    assert dest.read_text(encoding="utf-8") == "mine\n"


def test_dest_that_is_a_link_to_an_empty_folder_is_refused(tmp_path, capsys):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    code, out, err = run(capsys, str(link))  # used to end in "Cannot call rmtree on a symbolic link"
    assert (code, out, err) == (2, "", refusal(link))
    assert link.is_symlink() and list(target.iterdir()) == []


def test_dangling_link_is_refused(tmp_path, capsys):
    link = tmp_path / "dangling"
    link.symlink_to(tmp_path / "nowhere")
    assert run(capsys, str(link))[0] == 2
    assert link.is_symlink() and not (tmp_path / "nowhere").exists()


@pytest.mark.parametrize("which", ["demo/context", "demo", "repo root"])
def test_tracked_demo_folder_and_the_folders_above_it_are_refused(capsys, which):
    dest = {"demo/context": SOURCE_DEMO, "demo": SOURCE_DEMO.parent, "repo root": REPO}[which]
    tracked = snapshot(SOURCE_DEMO)
    top = sorted(os.listdir(REPO))
    code, out, err = run(capsys, str(dest))
    assert (code, out, err) == (2, "", refusal(dest))
    assert snapshot(SOURCE_DEMO) == tracked and not (SOURCE_DEMO / ".env").exists()
    assert sorted(os.listdir(REPO)) == top


@pytest.mark.parametrize("rel", ["new-folder", "app", "docs/sub"])
def test_paths_inside_the_tracked_demo_folder_are_refused(capsys, rel):
    tracked = snapshot(SOURCE_DEMO)
    dest = SOURCE_DEMO / rel
    code, out, err = run(capsys, str(dest))
    assert (code, out, err) == (2, "", refusal(dest))  # the plan's one refusal message, even for a new path
    assert snapshot(SOURCE_DEMO) == tracked


def test_a_relative_dot_path_from_the_repo_root_is_refused(capsys, monkeypatch):
    monkeypatch.chdir(REPO)
    tracked = snapshot(SOURCE_DEMO)
    for rel in (".", "demo", "demo/context", "demo/../demo/context"):
        assert run(capsys, rel)[0] == 2, rel
    assert snapshot(SOURCE_DEMO) == tracked


@pytest.mark.skipif(not (SOURCE_DEMO.parent / "CONTEXT").exists(), reason="case-sensitive file system")
def test_other_letter_case_of_the_demo_folder_is_refused(capsys):
    tracked = snapshot(SOURCE_DEMO)
    assert run(capsys, str(SOURCE_DEMO.parent / "Context"))[0] == 2
    assert run(capsys, str(SOURCE_DEMO.parent / "Context" / "new"))[0] == 2
    assert snapshot(SOURCE_DEMO) == tracked


def test_a_path_below_a_file_gives_one_error_line(tmp_path, capsys):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x\n", encoding="utf-8")
    code, out, err = run(capsys, str(blocker / "sub"))
    assert (code, out) == (2, "")
    assert err.startswith(f"error: cannot create {blocker / 'sub'}: ") and err.count("\n") == 1
    assert "Traceback" not in err


# --- language, help and usage -----------------------------------------------------------------


def test_lang_ko_prints_the_korean_message(tmp_path, capsys):
    dest = tmp_path / "notes.txt"
    dest.write_text("mine\n", encoding="utf-8")
    code, _, err = run(capsys, str(dest), "--lang", "ko")
    assert code == 2
    assert err == f"오류: {dest} 가 이미 있고 데모 복사본이 아닙니다. 새 폴더를 고르거나 직접 지우세요\n"


def test_english_message_is_the_planned_text(tmp_path, capsys):
    dest = tmp_path / "notes.txt"
    dest.write_text("mine\n", encoding="utf-8")
    err = run(capsys, str(dest), "--lang", "en")[2]
    assert err == f"error: {dest} already exists and is not a demo copy; choose a new folder or remove it yourself\n"


@pytest.mark.parametrize(
    ("argv", "env", "lang"),
    [
        ([], {"BUILD_CONTEXT_AUDIT_LANG": "ko"}, "ko"),
        ([], {"LANG": "ko_KR.UTF-8"}, "ko"),
        ([], {"LC_ALL": "en_US.UTF-8", "LANG": "ko_KR.UTF-8"}, "en"),
        (["--lang", "en"], {"BUILD_CONTEXT_AUDIT_LANG": "ko"}, "en"),
        (["--lang=ko"], {"LANG": "C"}, "ko"),
        ([], {}, "en"),
    ],
)
def test_language_order_matches_the_skill(tmp_path, capsys, argv, env, lang):
    dest = tmp_path / "notes.txt"
    dest.write_text("mine\n", encoding="utf-8")
    err = run(capsys, str(dest), *argv, env=env)[2]
    assert err == refusal(dest, lang)


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_prints_help_and_creates_nothing(tmp_path, capsys, monkeypatch, flag):
    monkeypatch.chdir(tmp_path)
    code, out, err = run(capsys, flag)
    assert (code, err) == (0, "")
    assert out.startswith("usage: setup_demo.py") and "DEST" in out
    assert "lost" in out  # the help says that edits to an earlier copy are lost
    assert list(tmp_path.iterdir()) == []  # no folder named '--help' and no marker file


def test_help_in_korean(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out, _ = run(capsys, "--help", "--lang", "ko")
    assert code == 0
    flat = " ".join(out.split())  # argparse wraps long lines
    assert " ".join(setup_demo.MESSAGES["ko"]["help.description"].split()) in flat and "사라집니다" in flat
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("argv", [[], ["a", "b"], ["x", "--lang", "fr"], ["--unknown", "x"]])
def test_usage_errors_exit_2_and_create_nothing(tmp_path, capsys, monkeypatch, argv):
    monkeypatch.chdir(tmp_path)
    code, out, err = run(capsys, *argv)
    assert (code, out) == (2, "")
    assert err.startswith("usage: setup_demo.py")
    assert list(tmp_path.iterdir()) == []


def test_message_tables_have_the_same_keys_and_placeholders():
    en, ko = setup_demo.MESSAGES["en"], setup_demo.MESSAGES["ko"]
    assert set(en) == set(ko)
    for key in en:
        assert set(PLACEHOLDER.findall(en[key])) == set(PLACEHOLDER.findall(ko[key])), key
        assert re.search("[가-힣]", ko[key]), key


def test_no_marker_file_is_written_next_to_the_copy(tmp_path, capsys):
    assert run(capsys, str(tmp_path / "bca-demo"))[0] == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bca-demo"]


# --- the real command line, as the README runs it --------------------------------------------


def run_script(cwd: Path, *argv: str, lang: str = "C") -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "LANG": lang}  # no PYTHONPATH: the script finds the skill itself
    return subprocess.run(
        [sys.executable, str(SCRIPT), *argv], cwd=cwd, env=env, capture_output=True, text=True, timeout=60
    )


def test_script_runs_directly_and_twice(tmp_path):
    dest = tmp_path / "bca-demo"
    first = run_script(tmp_path, str(dest))
    second = run_script(tmp_path, str(dest))
    assert (first.returncode, first.stdout, first.stderr) == (0, f"{dest}\n", "")
    assert (second.returncode, second.stdout, second.stderr) == (0, f"{dest}\n", "")
    assert copy_files(dest) == demo_files()


def test_script_help_and_korean_refusal(tmp_path):
    shown = run_script(tmp_path, "--help")
    assert shown.returncode == 0 and shown.stdout.startswith("usage: setup_demo.py")
    assert list(tmp_path.iterdir()) == []
    (tmp_path / "mine.txt").write_text("mine\n", encoding="utf-8")
    refused = run_script(tmp_path, ".", lang="ko_KR.UTF-8")
    assert refused.returncode == 2
    assert refused.stderr == "오류: . 가 이미 있고 데모 복사본이 아닙니다. 새 폴더를 고르거나 직접 지우세요\n"
    assert (tmp_path / "mine.txt").read_text(encoding="utf-8") == "mine\n"
