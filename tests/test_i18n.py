"""AC-7: English and Korean messages, language choice and language-independent JSON."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import audit
from _i18n import MESSAGES, count_files, lang_from_locale, resolve_lang, t
from conftest import DEMO

SCRIPTS = Path(audit.__file__).parent
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def test_both_languages_have_exactly_the_same_keys():
    assert set(MESSAGES["en"]) == set(MESSAGES["ko"])


def test_placeholders_match_between_languages():
    for key, en in MESSAGES["en"].items():
        assert set(PLACEHOLDER.findall(en)) == set(PLACEHOLDER.findall(MESSAGES["ko"][key])), key


def test_every_key_used_in_the_scripts_exists():
    used = set()
    for path in SCRIPTS.glob("*.py"):
        used |= set(re.findall(r't\(\s*lang,\s*"([\w.\-]+)"', path.read_text(encoding="utf-8")))
    used |= {f"copy.note.{n}" for n in ("from", "remote", "heredoc", "unparsable", "variable", "outside-context", "bad-glob", "missing")}
    used |= {f"status.{s}" for s in ("ok", "excluded", "missing", "skipped", "dynamic")}
    used |= {f"explain.effect.{e}" for e in ("exclude", "include", "no-effect", "folder-skip")}
    assert used - set(MESSAGES["en"]) == set()


def test_korean_text_is_really_korean():
    for key, text in MESSAGES["ko"].items():
        if key in ("suggest.files", "compare.path", "compare.copy"):
            continue  # bare "sign + path" rows hold no words
        if key.startswith(("help.", "error.", "hint.", "secrets.", "result.", "suggest.", "compare.", "totals")):
            assert re.search("[가-힣]", text), key


@pytest.mark.parametrize(
    ("cli_value", "env", "expected"),
    [
        ("ko", {"LANG": "en_US.UTF-8"}, "ko"),
        ("en", {"BUILD_CONTEXT_AUDIT_LANG": "ko", "LANG": "ko_KR.UTF-8"}, "en"),
        (None, {"BUILD_CONTEXT_AUDIT_LANG": "ko", "LC_ALL": "en_US.UTF-8"}, "ko"),
        (None, {"BUILD_CONTEXT_AUDIT_LANG": "en", "LC_ALL": "ko_KR.UTF-8"}, "en"),
        (None, {"LC_ALL": "ko_KR.UTF-8", "LC_MESSAGES": "en_US", "LANG": "en_US"}, "ko"),
        (None, {"LC_MESSAGES": "ko_KR", "LANG": "en_US"}, "ko"),
        (None, {"LC_ALL": "", "LC_MESSAGES": "", "LANG": "ko_KR.UTF-8"}, "ko"),
        (None, {"LANG": "fr_FR.UTF-8"}, "en"),
        (None, {"BUILD_CONTEXT_AUDIT_LANG": "fr"}, "en"),
        (None, {}, "en"),
    ],
)
def test_language_priority(cli_value, env, expected):
    assert resolve_lang(cli_value, env) == expected


def test_lang_from_locale():
    assert lang_from_locale("KO") == "ko" and lang_from_locale("ko_KR.UTF-8") == "ko"
    assert lang_from_locale("C") == "en" and lang_from_locale("") == "en"


def test_count_files_forms():
    assert count_files("en", 1) == "1 file" and count_files("en", 0) == "0 files" and count_files("ko", 3) == "3개"


def test_t_falls_back_to_english_for_unknown_language():
    assert t("xx", "result.ok") == MESSAGES["en"]["result.ok"]


def test_report_in_both_languages(cli):
    ko = cli(str(DEMO), "--lang", "ko").out
    en = cli(str(DEMO), "--lang", "en").out
    assert "비밀 파일" in ko and "Secrets" not in ko
    assert "Secrets" in en and "비밀 파일" not in en
    assert ko.splitlines()[0] == "무시 파일: .dockerignore"
    assert en.splitlines()[0] == "ignore file: .dockerignore"


def test_environment_variable_switches_the_report(cli, monkeypatch):
    monkeypatch.setenv("BUILD_CONTEXT_AUDIT_LANG", "ko")
    assert "비밀 파일" in cli(str(DEMO)).out
    assert "Secrets" in cli(str(DEMO), "--lang", "en").out


def test_locale_variables_switch_the_report(cli, monkeypatch):
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    assert "비밀 파일" in cli(str(DEMO)).out


def test_errors_are_translated(cli, tmp_path):
    ko = cli(str(tmp_path / "nope"), "--lang", "ko")
    assert ko.err.startswith("오류: 컨텍스트 폴더를 찾을 수 없음: ")
    assert "고치는 법:" in ko.err


def test_syntax_error_is_translated(cli, make_ctx):
    ctx = make_ctx({"Dockerfile": "FROM scratch\n", ".dockerignore": "[]a]\n"})
    assert cli(str(ctx), "--lang", "ko").err.startswith("오류: .dockerignore:1: 잘못된 패턴 '[]a]'")


def test_help_is_translated(capsys):
    for lang, needle in (("ko", "종료 코드"), ("en", "exit codes")):
        with pytest.raises(SystemExit):
            audit.main(["--help", "--lang", lang])
        assert needle in capsys.readouterr().out


def test_json_keys_and_values_do_not_depend_on_the_language(cli):
    en = cli(str(DEMO), "--format", "json", "--lang", "en", "--suggest", "--explain", "README-secret.md").json()
    ko = cli(str(DEMO), "--format", "json", "--lang", "ko", "--suggest", "--explain", "README-secret.md").json()

    def strip_messages(node):
        if isinstance(node, dict):
            return {k: strip_messages(v) for k, v in node.items() if k not in ("message", "notes")}
        if isinstance(node, list):
            return [strip_messages(v) for v in node]
        return node

    assert strip_messages(en) == strip_messages(ko)
    assert [h["message"] for h in en["hints"]] != [h["message"] for h in ko["hints"]]
    assert {h["code"] for h in en["hints"]} == {h["code"] for h in ko["hints"]}


def test_korean_typos_are_fixed():
    ko = " ".join(MESSAGES["ko"].values())
    for bad in ("넓어", "바뀔지", "건너뜍", "잡려면"):
        assert bad not in ko
    for good in ("넣어", "바뀌지", "건너뜀", "잡으려면"):
        assert good in ko


def test_docker_wording_stays_verbatim_in_korean():
    ko = MESSAGES["ko"]
    assert "'{pattern}': syntax error in pattern" in ko["error.pattern"]
    assert 'illegal exclusion pattern: "!"' in ko["error.illegal"]
    assert ko["error.pattern.fix"].startswith("고치는 법: Docker 도 이 줄을 거부")


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("--explain", "README-secret.md"),
        ("--suggest",),
        ("--compare-ignore", str(Path(__file__).resolve().parent.parent / "demo" / "proposed.dockerignore")),
        ("-f", str(DEMO / "build.Dockerfile")),
    ],
)
def test_text_output_has_same_shape_in_both_languages(cli, args):
    ko = cli(str(DEMO), "--lang", "ko", *args).out.splitlines()
    en = cli(str(DEMO), "--lang", "en", *args).out.splitlines()
    assert len(ko) == len(en)
    heads = lambda ls: [i for i, l in enumerate(ls) if l and not l[0].isspace()]  # noqa: E731
    assert heads(ko) == heads(en)
