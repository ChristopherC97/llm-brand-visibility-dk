"""Selftest for the rendered report. Runs without a single API call.

The seven invariants in the design handoff are methodological, not aesthetic:
break one and the report is wrong, however good it looks. So they are tests.

Run:  python3 analyze.py && python3 report.py && python3 report_selftest.py
"""

from __future__ import annotations

import html as html_lib
import json
import re
import sys
from pathlib import Path

import config
import report

FAILURES: list[str] = []
CHECKS = 0


def check(condition: bool, description: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(description)


def section(html: str, section_id: str) -> str:
    match = re.search(
        rf'<section class="[^"]*" id="{section_id}">(.*?)</section>', html, re.S
    )
    return match.group(1) if match else ""


def blocks(html: str, pattern: str) -> list[str]:
    return re.findall(pattern, html, re.S)


def names_in(html: str) -> list[str]:
    """Entity names as written in the matrix, with HTML escapes undone."""
    return [
        html_lib.unescape(name).strip()
        for name in re.findall(r'<td class="name">([^<]+)', html)
    ]


# --- 1. The four cells are never summed into one figure -----------------------


def test_no_pooled_figure(html: str, metrics: dict) -> None:
    """Every bar in the matrix must equal a rate that exists in the data.

    An average, a total or a weighting would not survive this: the printed
    number would match no cell.
    """
    known = {
        round(stat["mention_rate"] * 100)
        for entity in metrics["entities"].values()
        for stat in entity["cells"].values()
    }
    printed = {
        int(value)
        for value in re.findall(r'<div class="num [^"]*">(\d+)&nbsp;%', html)
    }
    check(bool(printed), "matrixen skal indeholde tal")
    unknown = printed - known
    check(not unknown, f"tal uden ophav i en enkelt celle: {sorted(unknown)}")

    source = Path(report.__file__).read_text(encoding="utf-8")
    for forbidden in ("statistics.mean", "sum(rates", "/ len(cells)", "pooled"):
        check(forbidden not in source, f"report.py må ikke indeholde {forbidden!r}")


# --- 2. Bands, never rank numbers ---------------------------------------------


def test_no_rankings(html: str) -> None:
    headers = re.findall(r"<th[^>]*>(.*?)</th>", html, re.S)
    for header in headers:
        text = re.sub(r"<[^>]+>", "", header).strip().lower()
        check(
            text not in {"#", "nr.", "nr", "rang", "rank", "placering", "plads"},
            f"kolonneoverskrift ligner en rangorden: {text!r}",
        )
    check(
        re.search(r'class="[^"]*rank', html) is None,
        "ingen kolonne må hedde rank",
    )
    check(
        re.search(r"<t[dh][^>]*>\s*(nr\.?|#)\s*\d", html, re.I) is None,
        "ingen celle må tildele et pladsnummer",
    )
    for name in names_in(html):
        check(
            not re.match(r"^\d+[.)]", name),
            f"entitetsnavn er nummereret: {name!r}",
        )
    for band in ("synlig", "marginal", "usynlig"):
        check(f">{band}</div>" in html, f"båndet {band!r} skal stå ved tallene")


# --- 3. Stores and brands never share a chart ---------------------------------


def test_families_are_separate(html: str, metrics: dict) -> None:
    type_of = {e["display"]: e["type"] for e in metrics["entities"].values()}
    tables = blocks(html, r'<table class="m">(.*?)</table>')
    check(len(tables) == 2, f"forventede to matrixtabeller, fandt {len(tables)}")
    for table in tables:
        types = {type_of.get(name) for name in names_in(table)}
        check(
            len(types) == 1,
            f"en matrixtabel blander entitetstyper: {sorted(t or '?' for t in types)}",
        )


# --- 4. Question level is counts, never percentages ----------------------------


def test_question_level_has_no_percentages(html: str) -> None:
    scopes = (
        blocks(html, r'<div class="detail qpanel"[^>]*>(.*?)\n</div>')
        + blocks(html, r'<button class="qrow"[^>]*>(.*?)</button>')
        + blocks(html, r'<button class="itile"[^>]*>(.*?)</button>')
    )
    check(len(scopes) >= 35, f"forventede mindst 35 spørgsmålsblokke, fandt {len(scopes)}")
    for scope in scopes:
        check("%" not in scope, f"procent i spørgsmålskontekst: {scope[:80]!r}")
    check(
        "af 3</span>" in html or "af 3<" in html,
        "spørgsmålsniveauet skal opgøres i tællinger (« … af 3»)",
    )


# --- 5. The limitations are a full section ------------------------------------


def test_limitations_are_a_section(html: str) -> None:
    body = section(html, "forbehold")
    check(bool(body), "sektionen «Hvad målingen ikke kan sige» mangler")
    check("hidden" not in body, "forbeholdene må ikke kunne skjules")
    check("aria-expanded" not in body, "forbeholdene må ikke kunne foldes sammen")
    check("<details" not in body, "forbeholdene må ikke ligge i et accordion")
    check("<footer" not in body, "forbeholdene må ikke ligge i en footer")
    check(len(re.findall(r'<div class="lim">', body)) == 6, "der skal stå seks forbehold")


# --- 6. The expiry stamp is visible without scrolling -------------------------


def test_stamp_is_above_the_fold(html: str, css: str) -> None:
    stamp = html.find('class="stampbox"')
    first_section = html.find("<section")
    check(stamp != -1, "holdbarhedsstemplet mangler")
    check(0 < stamp < first_section, "stemplet skal stå på forsiden, før første sektion")
    check(
        ".stampbox{order:-1}" in css.replace(" ", "").replace("\n", ""),
        "på én kolonne skal stemplet flyttes op over rubrikken",
    )
    check(
        re.search(r'class="b">\d{2}\.\d{2}\.\d{4}<', html) is not None,
        "udløbsdatoen skal stå som dato",
    )


# --- 7. No advice to named companies ------------------------------------------


def test_no_recommendations(html: str, metrics: dict) -> None:
    for quote in blocks(html, r'<div class="quote">(.*?)</div>\s*</div>'):
        check("modellens ord" in quote, "et citat mangler kildelinjen «modellens ord»")
    prose = re.sub(r"<[^>]+>", " ", html)
    names = [e["display"] for e in metrics["entities"].values()]
    for name in names:
        for verb in ("bør", "skal begynde", "anbefales at", "må se at"):
            check(
                f"{name} {verb}" not in prose,
                f"rapporten rådgiver en navngiven virksomhed: {name!r} {verb!r}",
            )


# --- Three more that a refactor breaks easily ---------------------------------


def test_no_entity_is_hidden(html: str, metrics: dict) -> None:
    for etype in ("maerke", "butik"):
        expected = [
            e["display"]
            for e in metrics["entities"].values()
            if e["type"] == etype
            and any(stat["mentions"] for stat in e["cells"].values())
        ]
        rows = names_in(html)
        missing = [name for name in expected if name not in rows]
        check(not missing, f"entiteter udeladt af matrixen: {missing}")
    check(
        "opacity:.5" in html.replace(" ", ""),
        "kun den lyse båndfarve bruger opacity — den skal stadig findes",
    )
    check(
        not re.search(r'class="[^"]*(row|name)[^"]*"[^>]*style="[^"]*opacity', html),
        "ingen entitetsrække må nedtones",
    )


def test_nothing_on_the_gradient(html: str) -> None:
    match = re.search(r'<div class="aurora"([^>]*)></div>', html)
    check(match is not None, "gradientbåndet mangler eller indeholder indhold")
    check('aria-hidden="true"' in (match.group(1) if match else ""),
          "gradientbåndet skal være aria-hidden")


def test_numbers_are_not_written_into_the_markup() -> None:
    """No measured figure may be typed into report.py by hand.

    Band boundaries (10 %, 40 %) are pre-registered thresholds, not
    measurements, so they are allowed to appear as prose.
    """
    source = Path(report.__file__).read_text(encoding="utf-8")
    allowed = {"10", "40", "95", "100"}
    literals = re.findall(r"(?<![\w.])(\d{1,3})&nbsp;%", source)
    stray = sorted({value for value in literals if value not in allowed})
    check(not stray, f"tal skrevet direkte i markup: {stray}")


# --- Runner -------------------------------------------------------------------


def main() -> int:
    if not config.REPORT_PATH.exists():
        print(f"Mangler {config.REPORT_PATH}. Kør:  python3 report.py")
        return 1
    raw = config.REPORT_PATH.read_text(encoding="utf-8")
    css = re.search(r"<style>(.*?)</style>", raw, re.S).group(1)
    metrics = json.loads(config.METRICS_PATH.read_text(encoding="utf-8"))

    # The transcripts are the models' words, not the report's. They are evidence,
    # and the invariants are about what the report itself says — so the data blob
    # and the scripts come out before anything is asserted about the prose.
    html = re.sub(r"<script.*?</script>", "", raw, flags=re.S)

    test_no_pooled_figure(html, metrics)
    test_no_rankings(html)
    test_families_are_separate(html, metrics)
    test_question_level_has_no_percentages(html)
    test_limitations_are_a_section(html)
    test_stamp_is_above_the_fold(html, css)
    test_no_recommendations(html, metrics)
    test_no_entity_is_hidden(html, metrics)
    test_nothing_on_the_gradient(html)
    test_numbers_are_not_written_into_the_markup()

    print(f"Kørte {CHECKS} kontroller mod {config.REPORT_PATH.name} uden et API-kald.")
    if FAILURES:
        print(f"\n{len(FAILURES)} FEJLEDE:\n")
        for failure in FAILURES:
            print(f"  ✗ {failure}")
        return 1
    print("Alle invarianter holder.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
