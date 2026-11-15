"""Turn the report dict into text or Markdown. The JSON output is the dict itself."""
from __future__ import annotations

from _i18n import count_files, t


def _rule_suffix(lang: str, rule: dict | None) -> str:
    if not rule:
        return ""
    return t(lang, "list.rule", file=rule["file"], line=rule["line"], pattern=rule["pattern"])


def _ignore_line(rep: dict, lang: str) -> str:
    name, reason = rep["ignore_file"], rep["ignore_file_reason"]
    if reason == "none":
        return t(lang, "ignore.none")
    if reason == "explicit":
        return t(lang, "ignore.explicit", name=name)
    if reason == "dockerfile-specific":
        return t(lang, "ignore.specific" if rep["root_ignore_unused"] else "ignore.specific.alone", name=name)
    return t(lang, "ignore.root", name=name)


def _sections(rep: dict, lang: str, max_list: int) -> list[tuple[str | None, list[str]]]:
    out: list[tuple[str | None, list[str]]] = []
    out.append((None, [_ignore_line(rep, lang)]))
    meta = f"{t(lang, 'label.context')}: {rep['context']}   {t(lang, 'label.dockerfile')}: {rep['dockerfile'] or t(lang, 'label.none')}"
    out.append((None, [meta, *[n["message"] for n in rep["notes"]]]))
    tot = rep["totals"]
    out.append(
        (
            None,
            [
                t(
                    lang,
                    "totals",
                    inc_files=count_files(lang, tot["included_files"]),
                    inc_bytes=tot["included_bytes"],
                    exc_files=count_files(lang, tot["excluded_files"]),
                    exc_bytes=tot["excluded_bytes"],
                )
            ],
        )
    )
    if rep["top_dirs"]:
        out.append(
            (
                t(lang, "top.header"),
                [t(lang, "top.row", path=d["path"], bytes=d["bytes"], files=count_files(lang, d["files"])) for d in rep["top_dirs"]],
            )
        )
    if rep["dockerfile"]:
        rows: list[str] = []
        for c in rep["copy_checks"]:
            status = c["status"]
            detail = ""
            if status in ("skipped", "dynamic") and c["note"]:
                detail = t(lang, f"copy.note.{c['note']}")
            rows.append(
                t(
                    lang,
                    "copy.row",
                    dockerfile=rep["dockerfile"],
                    line=c["dockerfile_line"],
                    instruction=c["instruction"],
                    source=c["source"],
                    status=t(lang, f"status.{status}"),
                    detail=detail,
                )
            )
            if status == "excluded" and c["rule"]:
                r = c["rule"]
                rows.append(t(lang, "copy.by", file=r["file"], line=r["line"], pattern=r["pattern"]))
            elif status == "missing":
                rows.append(t(lang, "copy.note.missing") if not c["note"] else t(lang, f"copy.note.{c['note']}"))
        if not rows:
            rows.append(t(lang, "copy.none"))
        out.append((t(lang, "copy.header", dockerfile=rep["dockerfile"]), rows))
    if rep["secrets"]:
        out.append(
            (
                t(lang, "secrets.header", n=len(rep["secrets"])),
                [t(lang, "secrets.row", path=s["path"], kind=s["kind"], hint=s["rule_hint"]) for s in rep["secrets"]],
            )
        )
    else:
        out.append((None, [t(lang, "secrets.none")]))
    if rep["hints"]:
        rows = []
        for h in rep["hints"]:
            if h["code"] == "escape-directive":
                where = t(lang, "hints.where.escape")
                shown = h["line"]
                rows.append(t(lang, "hints.row", where=where, line=shown, code=h["code"], message=h["message"]))
            else:
                rows.append(
                    t(
                        lang,
                        "hints.row",
                        where=rep["ignore_file"] or "",
                        line=f"{h['line']} '{h['pattern']}'",
                        code=h["code"],
                        message=h["message"],
                    )
                )
        out.append((t(lang, "hints.header"), rows))
    if rep.get("files") is not None:
        files = rep["files"]
        shown = files[:max_list]
        rows = [
            t(lang, "list.row.in" if f["included"] else "list.row.out", size=f["size"], path=f["path"], rule=_rule_suffix(lang, f["rule"]))
            for f in shown
        ]
        out.append((t(lang, "list.header", mode=rep["list_mode"], shown=len(shown), total=len(files)), rows))
    for ex in rep["explain"]:
        rows = []
        if not ex["included"]:
            r = ex["rule"]
            rows.append(t(lang, "explain.excluded", path=ex["path"], file=r["file"], line=r["line"], pattern=r["pattern"]))
        elif ex["rule"]:
            r = ex["rule"]
            rows.append(t(lang, "explain.included.rule", path=ex["path"], file=r["file"], line=r["line"], pattern=r["pattern"]))
        else:
            rows.append(t(lang, "explain.included.none", path=ex["path"]))
        if ex["kind"] == "unknown":
            rows.append(t(lang, "explain.unknown"))
        for h in ex["history"]:
            rows.append(
                t(
                    lang,
                    "explain.row",
                    file=h["file"],
                    line=h["line"],
                    pattern=h["pattern"],
                    effect=t(lang, f"explain.effect.{h['effect']}", folder=h.get("folder"), fix=h.get("fix")),
                    mark=t(lang, "explain.mark") if h["deciding"] else "",
                )
            )
        rows.extend(ex["notes"])
        out.append((None, rows))
    if rep["suggest_requested"]:
        if rep["suggestions"]:
            rows = []
            for s in rep["suggestions"]:
                rows.append(t(lang, "suggest.row", line=s["add_line"], target=s["target"]))
                eff = s["side_effects"]
                rows.append(
                    t(
                        lang,
                        "suggest.ok" if s["verified"] else "suggest.bad",
                        target=s["target"],
                        added=count_files(lang, len(eff["added"])),
                        removed=count_files(lang, len(eff["removed"])),
                    )
                )
                for sign, key in (("+", "added"), ("-", "removed")):
                    for p in eff[key][:5]:
                        rows.append(t(lang, "suggest.files", sign=sign, path=p))
            out.append((t(lang, "suggest.header", file=rep["suggestions"][0]["append_to"]), rows))
        else:
            out.append((None, [t(lang, "suggest.none")]))
    cmp_ = rep["compare"]
    if cmp_:
        rows = [
            t(lang, "compare.files", removed=count_files(lang, len(cmp_["removed"])), added=count_files(lang, len(cmp_["added"])), delta=f"{cmp_['bytes_delta']:+d}"),
        ]
        for sign, key in (("-", "removed"), ("+", "added")):
            for p in cmp_[key][:max_list]:
                rows.append(t(lang, "compare.path", sign=sign, path=p))
        before_total = rep["totals"]["included_bytes"]
        after_total = before_total + cmp_["bytes_delta"]
        smaller = cmp_["bytes_delta"] <= 0
        word = ("smaller" if smaller else "larger") if lang != "ko" else ("감소" if smaller else "증가")
        rows.append(t(lang, "compare.total", before=before_total, after=after_total, diff=abs(cmp_["bytes_delta"]), word=word))
        rows.append(t(lang, "compare.secrets", before=cmp_["secrets_before"], after=cmp_["secrets_after"]))
        if cmp_["copy_changes"]:
            for c in cmp_["copy_changes"]:
                rows.append(
                    t(
                        lang,
                        "compare.copy",
                        dockerfile=rep["dockerfile"] or "Dockerfile",
                        line=c["dockerfile_line"],
                        instruction=c["instruction"],
                        source=c["source"],
                        before=t(lang, f"status.{c['before']}"),
                        after=t(lang, f"status.{c['after']}"),
                    )
                )
        else:
            rows.append(t(lang, "compare.copy.none"))
        out.append((t(lang, "compare.header", file=cmp_["file"]), rows))
    summary = rep["summary"]
    if summary["copy_problems"] or summary["secrets"]:
        result = t(lang, "result.problems", copy=summary["copy_problems"], secrets=summary["secrets"])
    else:
        result = t(lang, "result.ok")
    out.append((None, [result]))
    return out


def render_text(rep: dict, lang: str, max_list: int) -> str:
    lines: list[str] = []
    for heading, rows in _sections(rep, lang, max_list):
        if heading:
            lines.append(heading)
        lines.extend(rows)
    return "\n".join(lines) + "\n"


def render_md(rep: dict, lang: str, max_list: int) -> str:
    lines = [f"# {t(lang, 'title')}", ""]
    for heading, rows in _sections(rep, lang, max_list):
        if heading:
            if lines[-1] != "":
                lines.append("")
            lines.append(f"## {heading.rstrip(':')}")
            lines.append("")
        for row in rows:
            lines.append(f"- `{row.strip()}`")
    return "\n".join(lines).rstrip() + "\n"
