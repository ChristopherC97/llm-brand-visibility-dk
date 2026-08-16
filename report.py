"""Builds the report: one self-contained HTML file, no build step, no CDN.

Usage:
    python3 analyze.py && python3 report.py

Writes docs/index.html — a single file with inlined CSS, no external fonts,
no chart library, no network calls. It must still open in three years, and it
must render with the network cable pulled out.

Visual direction follows the Knowit design handoff (design_handoff_synlighedsmaaling):
one weight, hierarchy from size alone, rounded windows on Knowit White, charts on
a dark surface, a red expiry date and nothing else in red. Every number on the page
is computed here from data/metrics.json — none of them are written into the markup
by hand. That is the point of the data contract, not a style preference.

Deviations from the prototype, all forced by the real dataset:
  * the prototype had 8 entities per family; the measurement has 74. The matrix
    shows all of them, grouped by band (never ranked, never dimmed, never hidden).
  * the prototype had 3 of 35 questions rendered verbatim; all 35 are here, with
    all 420 answers behind them.
  * per-cell toplines, Wilson boundary daggers and the full metric table exist in
    the data and had nowhere to live in the prototype, so they got places.
"""

from __future__ import annotations

import html
import json
import math
import re
from datetime import datetime, timedelta, timezone

import config

CELL_LABELS = {
    "claude/nosearch": ("Claude", "uden søgning"),
    "claude/search": ("Claude", "med søgning"),
    "gpt/nosearch": ("GPT", "uden søgning"),
    "gpt/search": ("GPT", "med søgning"),
}
CELL_ORDER = ["claude/nosearch", "claude/search", "gpt/nosearch", "gpt/search"]

TYPE_LABEL = {"maerke": "Mærker", "butik": "Butikker"}
TYPE_SINGULAR = {"maerke": "mærke", "butik": "butik"}
FAM_KEY = {"maerke": "brands", "butik": "shops"}

INTENT_LABEL = {
    "pris": "pris",
    "smag": "smag",
    "anvendelse": "anvendelse",
    "vaerdier": "værdier",
    "sammenligning": "sammenligning",
}


# --- Small helpers -----------------------------------------------------------


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def pct(rate: float | None, decimals: int = 0) -> str:
    """Danish percent: comma decimal separator, non-breaking space before %."""
    if rate is None:
        return "—"
    value = rate * 100
    text = f"{value:.{decimals}f}".replace(".", ",")
    return f"{text}&nbsp;%"


def dec(value: float, decimals: int = 2) -> str:
    return f"{value:.{decimals}f}".replace(".", ",")


def cell_name(cell: str) -> str:
    model, condition = CELL_LABELS.get(cell, (cell, ""))
    return f"{model} {condition}".strip()


def dk_date(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}"


def load() -> dict:
    if not config.METRICS_PATH.exists():
        raise SystemExit(
            f"Mangler {config.METRICS_PATH}.\nKør først:  python3 analyze.py"
        )
    return json.loads(config.METRICS_PATH.read_text(encoding="utf-8"))


def load_answers() -> list[dict]:
    """All 420 answers, published in full alongside the report.

    The artifact's central claim is that anyone can re-run it and get the same
    numbers. Keeping the evidence behind the numbers hidden would weaken exactly
    that claim, so the transcripts ship with the page.
    """
    path = config.DATA_DIR / "answers.json"
    if not path.exists():
        raise SystemExit(f"Mangler {path}.\nKør først:  python3 analyze.py")
    return json.loads(path.read_text(encoding="utf-8"))


# --- Derived views over the metrics ------------------------------------------


def band_of(rate: float) -> str:
    for name, low, high in config.VISIBILITY_BANDS:
        if low <= rate < high:
            return name
    return config.VISIBILITY_BANDS[-1][0]


def band_class(band: str) -> str:
    return {"synlig": "vis", "marginal": "mar", "usynlig": "usy"}[band]


def family(result: dict, etype: str) -> dict:
    """One entity family: every entity of that type that was ever mentioned.

    Sorted by highest rate across cells. That is an ordering, not a ranking —
    the bands carry the claim, and the table says so.
    """
    cells = [c for c in CELL_ORDER if c in result["meta"]["cells"]]
    rows = [
        data
        for data in result["entities"].values()
        if data["type"] == etype
        and any(stat["mentions"] for stat in data["cells"].values())
    ]
    rows.sort(key=lambda d: -max(s["mention_rate"] for s in d["cells"].values()))

    ceiling = max(
        (s["ci_high"] for d in rows for s in d["cells"].values()), default=0.1
    )
    axis = min(1.0, math.ceil(ceiling * 10) / 10)

    for data in rows:
        best = max(s["mention_rate"] for s in data["cells"].values())
        data["_best"] = best
        data["_band"] = band_of(best)
        data["_worst"] = min(s["mention_rate"] for s in data["cells"].values())

    return {
        "type": etype,
        "fam": FAM_KEY[etype],
        "label": TYPE_LABEL[etype],
        "rows": rows,
        "axis": axis,
        "cells": cells,
        "never": [
            data["display"]
            for data in result["entities"].values()
            if data["type"] == etype
            and not any(stat["mentions"] for stat in data["cells"].values())
        ],
    }


def extreme(fam: dict) -> dict:
    """Highest single-cell rate in a family, plus the same entity's lowest cell.

    Never an average across cells — the four cells are four populations.
    """
    best_entity, best_cell, best_rate = None, None, -1.0
    for data in fam["rows"]:
        for cell in fam["cells"]:
            rate = data["cells"][cell]["mention_rate"]
            if rate > best_rate:
                best_entity, best_cell, best_rate = data, cell, rate
    low_cell = min(fam["cells"], key=lambda c: best_entity["cells"][c]["mention_rate"])
    return {
        "entity": best_entity,
        "cell": best_cell,
        "rate": best_rate,
        "low_cell": low_cell,
        "low_rate": best_entity["cells"][low_cell]["mention_rate"],
    }


def invisible_everywhere(fam: dict) -> int:
    return sum(1 for d in fam["rows"] if d["_band"] == "usynlig")


def display_names(result: dict, keys: list[str]) -> list[str]:
    out = []
    for key in keys:
        data = result["entities"].get(key)
        out.append(data["display"] if data else key)
    return out


# --- Section 0: masthead and cover -------------------------------------------


def cover(result: dict, measured: str, expires: str) -> str:
    meta = result["meta"]
    models = " · ".join(meta["models"].values())
    passes = len(meta["passes"])
    cells = len(meta["cells"])
    return f"""
<div class="top">
  <span><b>Rapport</b></span>
  <span>Synlighed i sprogmodeller · dansk mejeri</span>
  <span>Måling {esc(dk_date(measured))}</span>
  <span class="r">Uafhængig måling · egne API-nøgler · version 1.0</span>
</div>

<div class="aurora" aria-hidden="true"></div>

<div class="hero">
  <div>
    <h1>Når en dansker spørger en sprogmodel om mejeri, <em>hvem bliver så nævnt</em>
      — og hvem findes slet ikke i svaret?</h1>
    <p class="stand">Der er ikke spurgt om et eneste mærke. De
      {esc(meta['questions'])} spørgsmål er stillet, som en forbruger ville stille dem, og
      navnene i svarene er dem, modellerne selv trak ind.
      {esc(meta['questions'])} spørgsmål på dansk blev stillet i {esc(cells)} kombinationer og
      kørt {esc(passes)} gange i hver: {esc(meta['answers'])} svar. Ingen af spørgsmålene
      nævner et mærke- eller butiksnavn. Rapporten kan læses fra opsummeringen og ned,
      eller åbnes ved et enkelt spørgsmål — alle {esc(meta['answers'])} svar ligger i den
      her fil.</p>
  </div>
  <div class="heroside">
    <div class="stampbox">
      <div class="a">Mindst holdbar til</div>
      <div class="b">{esc(expires)}</div>
      <div class="c">{esc(config.SHELF_LIFE_DAYS)} dage efter måling. Herefter er tallene
        historik, ikke status.</div>
    </div>
    <div class="facts">
      <dl>
        <dt>Omfang</dt><dd>{esc(meta['questions'])} spørgsmål · {esc(cells)} kombinationer ·
          {esc(passes)} kørsler</dd>
        <dt>Grundlag</dt><dd>{esc(meta['answers'])} svar</dd>
        <dt>Modeller</dt><dd>{esc(models)}</dd>
        <dt>Forbehold</dt><dd>Afsnit 5</dd>
      </dl>
    </div>
  </div>
</div>
"""


# --- Section 1: kort fortalt --------------------------------------------------


def summary_cards(result: dict, brands: dict, shops: dict) -> str:
    top_brand = extreme(brands)
    top_shop = extreme(shops)
    defunct = result["defunct"]["per_cell"]

    worst_cell = max(defunct, key=lambda c: defunct[c]["answers_with_error"])
    same_model = worst_cell.split("/")[0]
    other = f"{same_model}/{'search' if worst_cell.endswith('nosearch') else 'nosearch'}"
    clean_cells = [c for c in CELL_ORDER if defunct.get(c, {}).get("answers_with_error") == 0]

    nos = result["disagreement"]["nosearch"]["jaccard"]
    sea = result["disagreement"]["search"]["jaccard"]

    inv_b, inv_s = invisible_everywhere(brands), invisible_everywhere(shops)
    n_b, n_s = len(brands["rows"]), len(shops["rows"])

    # The stores never reach the top band in any cell. That is a finding, and it
    # is computed, not assumed — if a future run breaks it, the sentence changes.
    no_visible_shop = all(d["_band"] != "synlig" for d in shops["rows"])
    shop_tail = (
        " Ingen dagligvarekæde når over 40&nbsp;% i nogen af de fire kombinationer."
        if no_visible_shop else ""
    )

    cards = [
        {
            "lb": "Mest nævnte mærke",
            "fig": pct(top_brand["rate"]),
            "who": top_brand["entity"]["display"],
            "sen": (
                f"af de {result['meta']['cell_sizes'][top_brand['cell']]} svar i kombinationen "
                f"{esc(cell_name(top_brand['cell']))} nævner "
                f"{esc(top_brand['entity']['display'])} mindst én gang. I "
                f"{esc(cell_name(top_brand['low_cell']))} er det "
                f"{pct(top_brand['low_rate'])} — samme spørgsmål, samme dag."
            ),
            "ref": (
                f"kombination: {esc(cell_name(top_brand['cell']))} · modsat yderpunkt: "
                f"{esc(cell_name(top_brand['low_cell']))}"
            ),
        },
        {
            "lb": "Mest nævnte butik",
            "fig": pct(top_shop["rate"]),
            "who": top_shop["entity"]["display"],
            "sen": (
                f"af svarene i kombinationen {esc(cell_name(top_shop['cell']))} nævner "
                f"{esc(top_shop['entity']['display'])}. I "
                f"{esc(cell_name(top_shop['low_cell']))} er det "
                f"{pct(top_shop['low_rate'])}.{shop_tail}"
            ),
            "ref": (
                f"kombination: {esc(cell_name(top_shop['cell']))} · butiks- og mærketal har "
                f"hver sin akse"
            ),
        },
        {
            "lb": "Usynlige i alle fire kombinationer",
            "fig": f"{inv_b} af {n_b}",
            "who": "mejerimærker",
            "sen": (
                f"ligger under 10&nbsp;% i <em>alle</em> fire kombinationer — nævnt, men "
                f"praktisk taget uden for svaret uanset hvilken model forbrugeren "
                f"bruger. For butikker: {inv_s} af {n_s}."
            ),
            "ref": "bånd: under 10&nbsp;% = usynlig · ingen entitet er udeladt af tabellen",
        },
        {
            "lb": "Faktuelt forkert købsråd",
            "fig": (
                f"{defunct[worst_cell]['answers_with_error']} → "
                f"{defunct[other]['answers_with_error']}"
            ),
            "small": f"af {defunct[worst_cell]['answers']}",
            "alert": True,
            "who": "lukkede kæder",
            "sen": (
                f"svar anbefaler en dagligvarekæde, der ikke findes længere, uden at "
                f"nævne lukningen. Websøgning skærer fejlen ned — den fjerner den ikke. "
                + (
                    f"{esc(' og '.join(cell_name(c) for c in clean_cells))}: 0 fejl."
                    if clean_cells else ""
                )
            ),
            "ref": f"kombinationer: {esc(cell_name(worst_cell))} → {esc(cell_name(other))}",
        },
        {
            "lb": "Enighed mellem modellerne",
            "fig": f"{dec(nos)} → {dec(sea)}",
            "who": "overlap på de mest omtalte",
            "sen": (
                "Uden søgning peger de to modeller på stort set de samme navne. Med "
                "søgning gør de ikke. Hvorfor, kan målingen ikke sige."
            ),
            "ref": "Jaccard, beregnet inden for samme betingelse",
        },
    ]

    html_cards = "".join(card_html(c) for c in cards)

    intent_cards = "".join(
        f'<div class="intblock int-{esc(intent)}">{card_html(intent_card(result, intent, data))}</div>'
        for intent, data in result["by_intent"].items()
    )

    return f"""
<section class="window lpurple" id="kort">
  <div class="wtop">
    <h2>Kort fortalt</h2>
    <div class="r">Hvert tal hører til én navngiven kombination · ingen af tallene er et
      gennemsnit af de fire</div>
  </div>
  <div class="cards">{html_cards}{intent_cards}</div>
  <p class="small" style="margin:24px 0 0">Der findes ikke ét samlet synlighedstal i
    rapporten, og det er ikke tilbageholdenhed: de fire kombinationer måler ikke det samme, og
    et gennemsnit af dem ville være et tal, ingen bruger nogensinde har mødt. Derfor står
    hvert tal med den kombination, det kommer fra — og hvor det er relevant, står tallet fra
    den kombination, hvor det ser dårligst ud, lige ved siden af.</p>
</section>
"""


def card_html(c: dict) -> str:
    unit = f'<small>{c["small"]}</small>' if c.get("small") else ""
    return (
        f'<div class="card{" accent" if c.get("accent") else ""}">'
        f'<div class="lb">{c["lb"]}</div>'
        f'<div class="fig{" alert" if c.get("alert") else ""}">{c["fig"]}{unit}</div>'
        f'<div class="who">{c["who"]}</div>'
        f'<p class="sen">{c["sen"]}</p>'
        f'<div class="ref">{c["ref"]}</div></div>'
    )


def intent_card(result: dict, intent: str, data: dict) -> dict:
    stores = display_names(result, data["top_stores"])
    brands = display_names(result, data["top_brands"])
    return {
        "accent": True,
        "lb": f"Den valgte intention: «{esc(INTENT_LABEL.get(intent, intent))}»",
        "fig": str(data["questions"]),
        "small": "spørgsmål",
        "who": "fremkalder oftest netop disse",
        "sen": (
            f"Butikker: {esc(', '.join(stores))}. Mærker: {esc(', '.join(brands))}. "
            f"{data['answers']} svar i intentionen, "
            f"{data['store_mentions']} butiksomtaler og {data['brand_mentions']} "
            f"mærkeomtaler i alt."
        ),
        "ref": "kvalitativ liste · ingen placeringer",
    }


# --- Section 2: the questions -------------------------------------------------


def questions_section(result: dict, answers: list[dict]) -> str:
    meta = result["meta"]
    by_intent: dict[str, list[dict]] = {}
    for question in result["questions"]:
        by_intent.setdefault(question["intent"], []).append(question)

    n_cells = len(meta["cells"])
    n_runs = len(meta["passes"])
    per_q = n_cells * n_runs

    tiles = "".join(
        intent_tile(intent, items, per_q) for intent, items in by_intent.items()
    )
    n_err = sum(
        1
        for q in result["questions"]
        if any(c.get("defunct_errors") for c in q["cells"].values())
    )

    lists = "".join(
        f'<div class="intblock int-{esc(intent)}">'
        f'<div class="label">Spørgsmål i intentionen «{esc(INTENT_LABEL.get(intent, intent))}»'
        f" — {len(items)} i alt</div>"
        + "".join(question_row(q, per_q) for q in items)
        + "</div>"
        for intent, items in by_intent.items()
    )

    chips = "".join(
        f'<div class="intblock int-{esc(intent)}">'
        f'<div class="label" style="margin-top:14px">Butikker</div>'
        f'<div class="chips">'
        + "".join(
            f'<span class="chip">{esc(n)}</span>'
            for n in display_names(result, result["by_intent"][intent]["top_stores"])
        )
        + '</div><div class="label">Mærker</div><div class="chips">'
        + "".join(
            f'<span class="chip">{esc(n)}</span>'
            for n in display_names(result, result["by_intent"][intent]["top_brands"])
        )
        + "</div></div>"
        for intent in by_intent
    )

    panels = "".join(
        question_panel(q, per_q, n_runs) for q in result["questions"]
    )

    return f"""
<section class="window plain" id="spoergsmaal">
  <div class="wtop">
    <h2>Spørgsmålene</h2>
    <div class="r">Alle {esc(meta['questions'])} spørgsmål er gengivet ordret ·
      klik for at se hvad hver kombination svarede</div>
  </div>
  <p class="stand" style="margin-bottom:26px">De {esc(meta['questions'])} spørgsmål er den
    svageste antagelse i hele arbejdet. Derfor ligger de her og ikke i et bilag: man skal
    kunne være konkret uenig i dem — og se de {esc(per_q)} svar, hvert af dem gav.</p>
  <div class="intents">{tiles}</div>
  <div class="tickkey">
    <span><i></i> ét felt pr. spørgsmål · ordlyd og alle {esc(per_q)} svar ligger i
      rapporten</span>
    <span><i class="err"></i> spørgsmål, hvor mindst ét svar anbefalede en kæde, der ikke
      findes ({esc(n_err)} af {esc(meta['questions'])})</span>
  </div>
  <div class="qsplit">
    <div>
      {lists}
      <p class="small" style="margin-top:18px">Der står ingen procenter pr. spørgsmål
        nogen steder i rapporten. Ét spørgsmål er {esc(n_runs)} svar pr. kombination, og en
        procent på {esc(n_runs)} svar er et decimaltal, der udgiver sig for at være en
        måling. Spørgsmålsniveauet opgøres i tællinger.</p>
    </div>
    <div>
      <div class="label">Entiteter der optrådte oftest i denne intention</div>
      {chips}
      <p class="small">Kvalitativ liste, med vilje uden tal. Butikker og mærker står i to
        lister og lægges aldrig sammen: et prisspørgsmål kan fremkalde en butikskæde, et
        smagsspørgsmål kan ikke.</p>
    </div>
  </div>
  {panels}
</section>
"""


def intent_tile(intent: str, items: list[dict], per_q: int) -> str:
    """One tile per intention. The tick row is one tick per question.

    In the prototype a green tick meant «the wording is reproduced in the report»
    and only three were green. All of them are green now, because every question
    carries its full wording and all twelve answers. The ticks that mark a
    factual error are the ones worth looking at, so those get the outline.
    """
    ticks = "".join(
        '<i class="doc'
        + (" err" if any(c.get("defunct_errors") for c in q["cells"].values()) else "")
        + '"></i>'
        for q in items
    )
    return (
        f'<button class="itile" type="button" data-int="{esc(intent)}" aria-pressed="false">'
        f'<div class="n">{esc(INTENT_LABEL.get(intent, intent))}</div>'
        f'<div class="q">{len(items)}</div>'
        f'<div class="u">spørgsmål · {len(items) * per_q} svar</div>'
        f'<div class="ticks">{ticks}</div></button>'
    )


def question_row(question: dict, per_q: int) -> str:
    errors = sum(c.get("defunct_errors", 0) for c in question["cells"].values())
    flag = (
        f'<span class="qflag">lukket kæde<br>{errors} af {per_q} svar</span>'
        if errors else '<span class="qflag"></span>'
    )
    return (
        f'<button class="qrow" type="button" data-q="{esc(question["id"])}" '
        f'aria-expanded="false">'
        f'<span class="id">{esc(question["id"])}</span>'
        f'<span class="tx">{esc(question["text"])}</span>{flag}</button>'
    )


def question_panel(question: dict, per_q: int, n_runs: int) -> str:
    cols = []
    for cell in CELL_ORDER:
        data = question["cells"].get(cell)
        model, condition = CELL_LABELS.get(cell, (cell, ""))
        if data is None:
            cols.append(
                f'<div class="qcell"><div class="qcell-head">{esc(model)}'
                f"<em>{esc(condition)}</em></div>"
                f'<p class="qnone">Kombinationen indgår i målingen, men payloaden er ikke '
                f"leveret for dette spørgsmål.</p></div>"
            )
            continue
        if data["entities"]:
            ents = "".join(
                f'<li><span class="en">{esc(e["display"])}</span>'
                f'<span class="et">{esc(TYPE_SINGULAR.get(e["type"], e["type"]))}</span>'
                f'<span class="ec">'
                + "".join(
                    f'<i class="{"on" if i < e["runs_present"] else ""}"></i>'
                    for i in range(e["runs_total"])
                )
                + f'{e["runs_present"]} af {e["runs_total"]}</span></li>'
                for e in data["entities"]
            )
            body = f'<ul class="qents">{ents}</ul>'
        else:
            body = (
                '<p class="qnone">Ingen mærker eller butikker registreret i denne '
                "kombination.</p>"
            )
        flag = (
            f'<p class="qerr">{data["defunct_errors"]} af {data["runs"]} kørsler '
            f"anbefalede en kæde, der ikke findes</p>"
            if data.get("defunct_errors") else ""
        )
        runs = "".join(
            f'<button type="button" class="qrun" data-q="{esc(question["id"])}" '
            f'data-cell="{esc(cell)}" data-pass="{i}">kørsel {i}</button>'
            for i in range(1, n_runs + 1)
        )
        cols.append(
            f'<div class="qcell"><div class="qcell-head">{esc(model)}'
            f"<em>{esc(condition)}</em></div>{body}{flag}"
            f'<div class="qmeta">median {data["median_length"]} tegn</div>'
            f'<div class="qruns noprint">{runs}</div></div>'
        )

    return f"""
<div class="detail qpanel" id="p-{esc(question['id'])}" hidden>
  <div class="label">Spørgsmål {esc(question['id'])} · intention
    «{esc(INTENT_LABEL.get(question['intent'], question['intent']))}» ·
    {esc(per_q)} svar</div>
  <p class="verbatim">{esc(question['text'])}</p>
  <div class="qcells">{''.join(cols)}</div>
  <div class="tslot"></div>
  <p class="small" style="max-width:36em;margin:14px 0 0">Tallene er tællinger, ikke
    procenter: «{esc(n_runs)} af {esc(n_runs)} kørsler» betyder, at entiteten optrådte i
    alle {esc(n_runs)} svar fra den kombination. Transkripterne er modellens ord og modellens
    påstande om navngivne virksomheder — ikke rapportens, og ikke efterprøvet mod en
    butikshylde.</p>
</div>
"""


# --- Section 3: the four cells -----------------------------------------------


def matrix_section(result: dict, brands: dict, shops: dict) -> str:
    tables = "".join(matrix_table(result, fam) for fam in (brands, shops))
    return f"""
<section class="window dark" id="kombinationer">
  <div class="wtop">
    <h2>Fire kombinationer, samme entiteter</h2>
    <div class="r">Alle fire kombinationer vises altid · ingen knap lægger dem sammen</div>
  </div>
  <div class="pills noprint" style="margin-bottom:26px">
    <button class="pill" type="button" data-fam="brands" aria-pressed="true">Mærker</button>
    <button class="pill" type="button" data-fam="shops" aria-pressed="false">Butikker</button>
  </div>
  {tables}
  <div class="keys">
    <div><span class="k v"></span> synlig, over 40&nbsp;%</div>
    <div><span class="k m"></span> marginal, 10–40&nbsp;%</div>
    <div><span class="k u"></span> usynlig, under 10&nbsp;%</div>
    <div><span class="k r"></span> 95&nbsp;%-Wilson-interval, n = {esc(result['meta']['questions'])} spørgsmål</div>
    <div><span class="k o"></span> optrådte oftest i den valgte intention</div>
    <div><span class="kd">{esc(config.BOUNDARY_MARKER)}</span> intervallet krydser en
      båndgrænse — båndet er ikke afgjort</div>
  </div>
  <p class="small" style="margin-top:22px">Farven bærer størrelsen: lilla er synlig,
    orange er marginal, lys er under 10&nbsp;%. Ingen entitet nedtones eller skjules —
    også et mærke, der blev nævnt én enkelt gang, står i fuld læsbarhed, for det er
    tallet, en marketingchef er kommet for at se. Rækkefølgen er ikke en rangorden: entiteterne er grupperet i
    bånd, og inden for et bånd er intervallerne så brede, at en placering ville være
    opdigtet præcision. Den lyse flade bag hver bjælke er 95&nbsp;%-intervallet. Mærker
    og butikker har hver sin akse og vises aldrig i samme graf.</p>
</section>
"""


def matrix_table(result: dict, fam: dict) -> str:
    axis = fam["axis"]
    cells = fam["cells"]
    intents = result["by_intent"]
    top_key = "top_brands" if fam["type"] == "maerke" else "top_stores"

    head = (
        f'<thead><tr><th>{esc(fam["label"])}<span>Omtale-rate pr. kombination</span></th>'
        + "".join(
            f'<th class="cellcol">{esc(CELL_LABELS[c][1])}<span>{esc(CELL_LABELS[c][0])}</span></th>'
            for c in cells
        )
        + "</tr></thead>"
    )

    body, current_band = [], None
    for data in fam["rows"]:
        if data["_band"] != current_band:
            current_band = data["_band"]
            count = sum(1 for d in fam["rows"] if d["_band"] == current_band)
            copy = {
                "synlig": "synlig i mindst én kombination · over 40&nbsp;%",
                "marginal": "marginal i sit bedste tilfælde · 10–40&nbsp;%",
                "usynlig": "under 10&nbsp;% i alle fire kombinationer",
            }[current_band]
            body.append(
                f'<tr class="grp"><td colspan="{len(cells) + 1}">'
                f'<span class="grp-dot {band_class(current_band)}"></span>'
                f"{copy} · {count} {esc(fam['label'].lower())}</td></tr>"
            )

        note = f'<i>{esc(data["note"])}</i>' if data["note"] else ""
        if data["defunct"]:
            chain = result["defunct"]["chains"].get(data["key"], {})
            note += f'<i class="gone">ophørte {esc(chain.get("ended", ""))}</i>'
        marks = "".join(
            f'<span class="mark" data-int="{esc(intent)}"><b></b>oftest i '
            f"«{esc(INTENT_LABEL.get(intent, intent))}»</span>"
            for intent, idata in intents.items()
            if data["key"] in idata[top_key]
        )

        tds = []
        for cell in cells:
            stat = data["cells"][cell]
            rate, low, high = stat["mention_rate"], stat["ci_low"], stat["ci_high"]
            klass = band_class(stat["band"])
            dagger = (
                f'<u>{esc(config.BOUNDARY_MARKER)}</u>' if stat["boundary_uncertain"] else ""
            )
            tds.append(
                f'<td class="cellcol">'
                f'<div class="track" title="{esc(stat["band"])}">'
                f'<div class="rng" style="left:{low / axis * 100:.1f}%;'
                f'width:{max(0.0, (min(axis, high) - low) / axis * 100):.1f}%"></div>'
                f'<div class="bar {klass}{" seen" if stat["mentions"] else ""}" '
                f'style="width:{rate / axis * 100:.1f}%"></div></div>'
                f'<div class="num {klass}">{pct(rate)}{dagger}'
                f'<s>{pct(low).replace("&nbsp;%", "")}–{pct(high)}</s></div>'
                f'<div class="band">{esc(stat["band"])}</div></td>'
            )

        body.append(
            f'<tr><td class="name">{esc(data["display"])}{note}{marks}</td>'
            + "".join(tds)
            + "</tr>"
        )

    never = ""
    if fam["never"]:
        never = (
            f'<p class="small" style="margin:16px 0 0">Aldrig nævnt i nogen af de '
            f'{esc(result["meta"]["answers"])} svar, men med i ordbogen: '
            f'{esc(", ".join(fam["never"]))}. En entitet med nul omtaler har ingen '
            f"bjælke — den har en linje her.</p>"
        )

    toplines = topline_strip(result, fam)

    return (
        f'<div class="famblock fam-{fam["fam"]}">'
        f'<h3 class="famhead">{esc(fam["label"])} · akse 0–{pct(axis)} · '
        f'{len(fam["rows"])} entiteter</h3>'
        f"{toplines}"
        f'<div class="mwrap"><table class="m">{head}<tbody>{"".join(body)}</tbody></table></div>'
        f"{never}</div>"
    )


def topline_strip(result: dict, fam: dict) -> str:
    """Per-combination coverage for one family. Four figures, never one.

    Where the two conditions of the same model land on the identical figure, the
    strip says so. Two neighbouring 75 % read as a copy-paste error otherwise,
    and the second line is what keeps the pair from being read as one finding.
    """
    share_key = "share_with_brand" if fam["type"] == "maerke" else "share_with_store"
    avg_key = "avg_brands_per_answer" if fam["type"] == "maerke" else "avg_stores_per_answer"
    word = "mærke" if fam["type"] == "maerke" else "butik"
    plural = "mærker" if fam["type"] == "maerke" else "butikker"

    blocks = "".join(
        f'<div class="tl"><div class="tl-c">{esc(CELL_LABELS[c][0])} '
        f'<em>{esc(CELL_LABELS[c][1])}</em></div>'
        f'<div class="tl-v">{pct(result["toplines"][c][share_key])}</div>'
        f'<div class="tl-s">af {result["toplines"][c]["answers"]} svar nævner mindst ét '
        f'{esc(word)} · {dec(result["toplines"][c][avg_key], 2)} {esc(plural)} pr. svar</div></div>'
        for c in fam["cells"]
    )

    ties = []
    for model_id in result["meta"]["models"]:
        pair = [c for c in fam["cells"] if c.startswith(f"{model_id}/")]
        if len(pair) != 2:
            continue
        first, second = (result["toplines"][c] for c in pair)
        if first[share_key] != second[share_key]:
            continue
        label = CELL_LABELS[pair[0]][0]
        # Inde i rækkens egen ramme, ikke under skillestregen: linjen hører til de
        # fire tal ovenover, ikke til tabellen nedenunder.
        ties.append(
            f'<p class="small" style="grid-column:1/-1;margin:2px 0 0">De to '
            f"{esc(label)}-kombinationer rammer samme tal for dækning. Antallet af "
            f"{esc(plural)} pr. svar gør ikke: "
            f'{dec(first[avg_key])} mod {dec(second[avg_key])}.</p>'
        )

    return f'<div class="tls">{blocks}{"".join(ties)}</div>'


# --- Section 4: defunct chains and disagreement ------------------------------


def quote_html(quote: str, chain: str) -> str:
    """An excerpt from a raw answer, set as the model's own words.

    Two things are preserved on purpose: the markdown emphasis the model wrote
    (so the quote reads as it was written), and the name of the chain that no
    longer exists (marked, because it is the finding — not a typo).
    """
    text = quote.strip()
    text = re.sub(r"^…\S*\s*", "… ", text)  # excerpts start mid-word; cut to a word
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    out = esc(text)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", out)
    if chain:
        out = re.sub(
            rf"\b({re.escape(esc(chain))})\b",
            r'<mark class="gone">\1</mark>',
            out,
        )
    return out


def defunct_section(result: dict) -> str:
    defunct = result["defunct"]
    chains = defunct["chains"]
    per_cell = defunct["per_cell"]
    total = sum(c["answers_with_error"] for c in per_cell.values())

    chain_list = "".join(
        f'<div class="gonerow"><div class="a">{esc(c["display"])}</div>'
        f'<div class="b">ophørt {esc(c["ended"])}</div>'
        f'<div class="c">{esc(c["detail"])}</div></div>'
        for c in chains.values()
    )

    rows = "".join(
        f"<tr><td>{esc(cell_name(cell))}</td>"
        f'<td>{stats["answers_with_error"]} af {stats["answers"]}</td>'
        f'<td>{pct(stats["error_rate"])}</td>'
        f'<td>{stats["answers_stating_closure_correctly"]}</td>'
        f'<td class="txt">'
        + (
            esc(" · ".join(f"{n} {v}" for n, v in stats["by_chain"].items()))
            if stats["by_chain"] else "—"
        )
        + "</td></tr>"
        for cell, stats in sorted(
            per_cell.items(),
            key=lambda kv: CELL_ORDER.index(kv[0]) if kv[0] in CELL_ORDER else 99,
        )
    )

    if total == 0:
        body = (
            "<p><strong>Ingen af modellerne anbefalede en udgået kæde i denne "
            "måling.</strong> Sektionen står alligevel, fordi tjekket er en del af "
            "metoden og ikke af resultatet.</p>"
        )
    else:
        quotes = "".join(
            f'<div class="quote"><p>«{quote_html(q["quote"], q.get("chain", ""))}»</p>'
            f'<div class="src">{esc(cell_name(q["cell"]))} · kørsel {esc(q["pass"])} · '
            f'spørgsmål {esc(q["prompt_id"])}: «{esc(q["question"])}» — modellens ord, '
            f"ikke rapportens</div></div>"
            for q in defunct["quotes"][:3]
        )
        body = (
            f'<table class="t">'
            f"<thead><tr><th>Kombination</th><th>Svar med fejl</th><th>Andel</th>"
            f'<th>Svar der beskriver lukningen korrekt</th>'
            f'<th class="txt">Hvilke kæder</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>"
            f'<p class="small" style="margin-top:14px">En omtale tælles kun som fejl, '
            f"hvis den står uden en lukningsmarkør i nærheden. «Aldi forlod Danmark i "
            f"2023» er modellen, der har ret, og tælles ikke med. "
            f'{len(defunct["quotes"])} passager blev fanget i alt; tre af dem står her, '
            f"ordret:</p>{quotes}"
        )

    dis_rows = "".join(
        f"<tr><td>{'Uden' if key == 'nosearch' else 'Med'} websøgning</td>"
        f'<td>{dec(data["jaccard"])}</td>'
        f'<td>{len(data["shared"])} navne</td>'
        f'<td class="txt">Kun {CELL_LABELS[data["cells"][0]][0]}: '
        f'{esc(", ".join(data["only_in_claude"]) or "ingen")}. '
        f'Kun {CELL_LABELS[data["cells"][1]][0]}: '
        f'{esc(", ".join(data["only_in_gpt"]) or "ingen")}.</td></tr>'
        for key, data in result["disagreement"].items()
    )

    return f"""
<section class="window plain" id="kaeder">
  <h2>Kæder, der ikke findes</h2>
  <p class="stand" style="margin-bottom:22px">Tre danske dagligvarekæder eksisterer ikke
    længere under det navn. Anbefales de stadig, uden at lukningen nævnes, er det ikke en
    smagssag, men faktuelt forkert købsråd leveret med samme sikkerhed som det rigtige.</p>
  <div class="gonelist">{chain_list}</div>
  {body}
  <h3>Enigheden halveres, når websøgning slås til</h3>
  <p>{dec(result['disagreement']['nosearch']['jaccard'])} mod
    {dec(result['disagreement']['search']['jaccard'])}. Overlappet er beregnet inden for
    hver betingelse. At sammenligne en søgende model med en ikke-søgende ville måle
    indstillingen, ikke modellerne.</p>
  <table class="t">
    <thead><tr><th>Betingelse</th><th>Jaccard-overlap</th><th>Fælles navne</th>
      <th class="txt">Hvem står alene</th></tr></thead>
    <tbody>{dis_rows}</tbody>
  </table>
  <p class="small" style="margin-top:14px">Et lavt overlap betyder, at hvilken model
    forbrugeren tilfældigvis bruger, afgør hvilke navne de præsenteres for.</p>
</section>
"""


# --- Section 5: limitations ---------------------------------------------------

LIMITATIONS = [
    (
        "Volumen",
        "Målingen siger intet om, hvor mange danskere der faktisk spørger en sprogmodel "
        "til råds, før de handler ind. Tallet kan være lille. Der findes ingen offentligt "
        "tilgængelig kilde, jeg kan reproducere, og betalte data er bevidst udeladt: et "
        "arbejde, hvis pointe er efterprøvelighed, kan ikke hvile på et tal, læseren ikke "
        "kan efterprøve.",
    ),
    (
        "Årsag",
        "Rapporten viser, hvad modellerne svarer — ikke hvorfor. Om en entitet nævnes "
        "ofte, fordi den er markedsledende, fordi den fylder i træningsdata, eller fordi "
        "den står i de kilder en søgning tilfældigvis rammer, kan metoden ikke afgøre.",
    ),
    (
        "Konvertering",
        "At blive nævnt er ikke at blive købt. Intet i materialet forbinder en omtale med "
        "et salg, et butiksbesøg eller et klik.",
    ),
    (
        "Udløb",
        "Det er et øjebliksbillede. Modeller opdateres uden varsel, søgeindekser ændrer "
        "sig dagligt, og udbydernes standardindstillinger skifter. Samme kørsel om tre "
        "måneder ville give andre tal — og man kunne ikke vide, om forskellen kom fra "
        "markedet eller fra modellen. Derfor står udløbsdatoen på forsiden.",
    ),
    (
        "Repræsentativitet",
        "Spørgsmålene er skrevet af én person. Ingen test kan afgøre, om de svarer til, "
        "hvordan danskere faktisk spørger. Derfor ligger de i afsnit 2 og ikke i et bilag, "
        "og derfor ligger hvert enkelt svar bag dem.",
    ),
    (
        "Hvad rapporten ikke gør",
        "Den giver ingen anbefalinger til navngivne virksomheder. Citaterne er modellens "
        "ord og modellens påstande om navngivne virksomheders priser — ikke rapportens, og "
        "ikke verificeret mod butikshylder. Rapporten viser en blind vinkel og stopper der.",
    ),
]


def limitations_section() -> str:
    half = (len(LIMITATIONS) + 1) // 2
    columns = []
    for start, chunk in ((0, LIMITATIONS[:half]), (half, LIMITATIONS[half:])):
        items = "".join(
            f'<div class="lim"><div class="n">5.{start + i + 1}</div>'
            f"<h4>{esc(title)}</h4><p>{esc(text)}</p></div>"
            for i, (title, text) in enumerate(chunk)
        )
        columns.append(f"<div>{items}</div>")
    return f"""
<section class="window purple" id="forbehold">
  <div class="wtop">
    <h2>Hvad målingen ikke kan sige</h2>
    <div class="r">Står i rapportens brødtekst, ikke i en fodnote</div>
  </div>
  <p class="stand" style="margin-bottom:8px">Rapportens form er stram. Det gør ikke
    datagrundlaget stærkere, end det er. Seks forbehold, som ingen præsentation kan
    fjerne.</p>
  <div class="lims">{''.join(columns)}</div>
</section>
"""


# --- Section 6: method --------------------------------------------------------


def method_section(result: dict) -> str:
    meta = result["meta"]
    intents = result["by_intent"]
    intent_text = ", ".join(
        f"{INTENT_LABEL.get(k, k)} ({v['questions']})" for k, v in intents.items()
    )
    models = ", ".join(meta["models"].values())
    spans = " · ".join(
        f"kørsel {s['pass']}: {s['first'][11:16]}–{s['last'][11:16]} UTC"
        for s in meta["pass_spans"]
    )
    spaced = len(meta["passes"]) > 1
    consistency_note = (
        "Kørslerne ligger timer fra hinanden, så konsistenstallet også afspejler "
        "variation over tid — ikke kun modellens tilfældighed i det enkelte kald."
        if spaced else
        "Kørslerne blev foretaget i træk, så konsistenstallet afspejler modellens "
        "tilfældighed i det enkelte kald, ikke variation over tid."
    )
    unknown = "".join(
        f'<span class="chip">{esc(u["name"])} <s>{u["count"]}</s></span>'
        for u in result["unknown_names"][:14]
    )
    n_cells = len(meta["cells"])
    n_runs = len(meta["passes"])
    per_cell = meta["cell_sizes"][CELL_ORDER[0]]

    truncated = (
        f"{meta['truncated_answers']} svar var afkortet af udbyderens tokengrænse og er "
        f"talt med som det, der nåede frem."
        if meta["truncated_answers"] else "Ingen svar blev afkortet."
    )

    return f"""
<section class="window plain" id="metode">
  <h2>Metode</h2>
  <h3>Spørgsmålene</h3>
  <p>{esc(meta['questions'])} spørgsmål på dansk fordelt på fem intentioner:
    {esc(intent_text)}. Ingen af dem indeholder et mærke- eller butiksnavn — et spørgsmål
    med «Arla» i ville måle genkendelse, ikke synlighed. Det håndhæves af en test i
    pipelinen, ikke af disciplin.</p>
  <h3>Design</h3>
  <p>{esc(n_cells)} kombinationer: to modeller × to betingelser (uden og med websøgning). Hver
    kombination kørt {esc(n_runs)} gange med timers mellemrum, så konsistens også afspejler
    variation over tid og ikke kun modellens tilfældighed i det enkelte kald.
    {esc(n_cells)} × {esc(meta['questions'])} × {esc(n_runs)} =
    {esc(meta['answers'])} svar, {esc(per_cell)} pr. kombination. Tidsrum: {esc(spans)}.
    {esc(truncated)}</p>
  <h3>Modeller og indstillinger</h3>
  <p>{esc(models)}. Ingen systemprompt, udbyderens øvrige standardindstillinger.
    Standardindstillinger er ikke det samme på tværs af udbydere — den ene model tænker
    som standard. Forskelle mellem modellerne er derfor delvis forskelle mellem
    udbydernes defaults, og det er en grænse for, hvad målingen kan tilskrive.</p>
  <h3>Ekstraktion</h3>
  <p>Omtaler findes med ordbog og regulære udtryk. Ingen sprogmodel deltager i tællingen.
    Ordbogen ligger i <span class="mono">entities.py</span> og kan gennemgås linje for
    linje. Danske faldgruber er håndteret med positionelle værn: «spar penge» er ikke
    butikskæden SPAR, «netto 400 gram» er ikke Netto, men «Netto har gode priser på 400
    gram ost» er. Kun første forekomst pr. entitet pr. svar tælles — ellers ville et
    langt, snakkesaligt svar veje tungere end et kort.</p>
  <h3>Ordbogens dækning</h3>
  <p>Efter ekstraktion udskrives kapitaliserede navne, som optrådte i svarene, men ikke
    stod i ordbogen. Hullerne findes systematisk frem for ved gætteri. De hyppigste
    ikke-katalogiserede navne i denne kørsel — hovedsagelig kategorier, myndigheder og
    stednavne, som med vilje ikke er entiteter:</p>
  <div class="chips">{unknown}</div>
  <h3>Optælling og usikkerhed</h3>
  <p>Omtale-rate er andelen af kombinationens {esc(per_cell)} svar, hvor entiteten optræder
    mindst én gang; fem omtaler i ét svar tæller som én. Bånd: synlig over 40&nbsp;%,
    marginal 10–40&nbsp;%, usynlig under 10&nbsp;%. Ingen placeringer, fordi intervallerne
    på n&nbsp;=&nbsp;{esc(meta['questions'])} er brede nok til, at en rangorden ville være
    opdigtet præcision. {esc(meta['ci_note'])} {esc(consistency_note)}</p>
  <h3>Forudregistrering og efterprøvning</h3>
  <p>Rapportens sektioner og båndgrænser blev låst i
    <span class="mono">report_plan.md</span> før den fulde kørsel; git-historikken viser
    hvornår. Spørgsmål, prompts, rå svar, optællingskode og de fire kombinationstabeller
    ligger samlet og tidsstemplet. Den, der vil modsige et tal her, skal kunne gøre det ved at
    køre målingen igen.</p>
</section>
"""


# --- Section 7: appendix ------------------------------------------------------


def appendix(result: dict, brands: dict, shops: dict) -> str:
    blocks = []
    for fam in (brands, shops):
        rows = []
        for data in fam["rows"]:
            first = True
            for cell in fam["cells"]:
                stat = data["cells"][cell]
                if not stat["mentions"]:
                    continue
                name = (
                    f'<td class="ent">{esc(data["display"])}</td>' if first
                    else '<td class="ent cont"></td>'
                )
                first = False
                dagger = config.BOUNDARY_MARKER if stat["boundary_uncertain"] else ""
                rows.append(
                    f"<tr>{name}<td>{esc(cell_name(cell))}</td>"
                    f'<td>{stat["mentions"]} af {stat["answers"]}</td>'
                    f'<td>{pct(stat["mention_rate"], 1)}{dagger}</td>'
                    f'<td>{pct(stat["ci_low"], 1).replace("&nbsp;%", "")}–'
                    f'{pct(stat["ci_high"], 1)}</td>'
                    f'<td>{pct(stat["share_of_voice"], 1)}</td>'
                    f'<td>{pct(stat["first_mentioned_rate"], 1)}</td>'
                    f'<td>{pct(stat["consistency"], 1)}</td>'
                    f'<td class="txt">{esc(stat["band"])}</td></tr>'
                )
        blocks.append(
            f'<div class="famblock fam-{fam["fam"]}">'
            f'<h3 class="famhead">{esc(fam["label"])}</h3>'
            f'<div class="mwrap"><table class="t app">'
            f"<thead><tr><th>Entitet</th><th>Kombination</th><th>Svar med omtale</th>"
            f"<th>Omtale-rate</th><th>95&nbsp;%-interval</th><th>Share of voice</th>"
            f'<th>Først nævnt</th><th>Konsistens</th><th class="txt">Bånd</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></div>'
        )

    return f"""
<section class="window plain" id="bilag">
  <div class="wtop">
    <h2>Bilag: alle tal</h2>
    <div class="r">Mærker og butikker aldrig i samme tabel · knappen deler tilstand med
      afsnit 3</div>
  </div>
  <div class="pills noprint" style="margin-bottom:22px">
    <button class="pill" type="button" data-fam="brands" aria-pressed="true">Mærker</button>
    <button class="pill" type="button" data-fam="shops" aria-pressed="false">Butikker</button>
  </div>
  <p>Samme fire kombinationer, alle mål. Share of voice er entitetens andel af alle omtaler i
    kombinationen. «Først nævnt» er andelen af de svar med omtale, hvor entiteten stod først.
    Konsistens er andelen af kørsler, hvor entiteten optrådte, blandt de spørgsmål hvor
    den optrådte mindst én gang — en entitet med lav konsistens er ikke synlig, den er
    heldig. Rækker uden omtaler i en kombination er udeladt af den kombination, ikke af tabellen.</p>
  {''.join(blocks)}
</section>
"""


# --- Page --------------------------------------------------------------------

CSS = """
:root{
  --white:#FEFBE6; --white100:#FFFEF6; --off60:#FAF6DD; --off40:#F3EFD5;
  --black:#0B0B26; --blue:#372BC5; --blue60:#5C44ED;
  --purple:#CFCEFF; --lpurple:#F7F6FF; --purple100:#9795FF;
  --pink:#FFD6B8; --lpink:#FFEBDD; --pink100:#FCB27C;
  --green:#55D440; --valid:#12862B; --alert:#E31F04;
  --line:rgba(11,11,38,.22); --line8:rgba(11,11,38,.08); --ink66:rgba(11,11,38,.66);
  --onl22:rgba(254,251,230,.22); --onl66:rgba(254,251,230,.66);
  --font:Arial,Helvetica,"Helvetica Neue",sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,"Courier New",monospace;
  --measure:724px;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;color-scheme:light}
body{margin:0;background:var(--white);color:var(--black);font:400 16px/1.6 var(--font);
  font-variant-numeric:tabular-nums;text-wrap:pretty;-webkit-font-smoothing:antialiased}
.wrap{max-width:1240px;margin:0 auto;padding:0 40px 88px}
button{font:inherit;cursor:pointer;background:transparent;color:inherit;border:0}
p{margin:0 0 14px;max-width:var(--measure)}
a{color:var(--blue)}a:hover{color:var(--blue60)}
.mono{font-family:var(--mono);font-size:.92em}
:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
.window.dark :focus-visible{outline-color:var(--green)}

h1{font:400 clamp(38px,6.4vw,76px)/1.04 var(--font);letter-spacing:-.028em;margin:0 0 28px;max-width:17em}
h1 em{font-style:normal;color:var(--blue)}
h2{font:400 clamp(26px,3.2vw,40px)/1.12 var(--font);letter-spacing:-.022em;margin:0 0 20px;max-width:24em}
h3{font:400 22px/1.28 var(--font);letter-spacing:-.012em;margin:30px 0 8px;max-width:22em}
.stand{font:400 clamp(19px,1.9vw,24px)/1.42 var(--font);letter-spacing:-.008em;max-width:var(--measure)}
.small{font-size:13px;line-height:1.6;color:var(--ink66);max-width:var(--measure)}
.label{font:400 13px/1.4 var(--font);color:var(--ink66)}

.top{display:flex;flex-wrap:wrap;gap:8px 32px;align-items:baseline;padding:20px 0 16px}
.top .r{margin-left:auto}
.top span{font:400 13px/1.4 var(--font);color:var(--ink66)}
.top b{font-weight:400;color:var(--black)}

.aurora{height:132px;border-radius:32px;margin:0 0 40px;
  background:linear-gradient(104deg,var(--green) 0%,#2FBF8C 22%,#2E7BE8 48%,var(--blue) 72%,#1A0E7A 100%)}

.hero{display:grid;grid-template-columns:1fr 300px;gap:56px;padding:0 0 44px}
.stampbox{border:1px solid var(--black);border-radius:24px;padding:22px 22px 20px}
.stampbox .a{font:400 13px/1.4 var(--font);color:var(--ink66)}
.stampbox .b{font:400 40px/1.05 var(--font);letter-spacing:-.03em;color:var(--alert);margin:8px 0}
.stampbox .c{font:400 14px/1.45 var(--font)}
.facts{margin-top:24px;border-top:1px solid var(--line);padding-top:16px}
.facts dl{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;margin:0;font-size:14px}
.facts dt{color:var(--ink66)}
.facts dd{margin:0}

.window{border-radius:32px;padding:32px 34px 34px;margin:0 0 24px}
.window.plain{background:var(--white100);border:1px solid var(--line8)}
.window.lpurple{background:var(--lpurple)}
.window.purple{background:var(--purple)}
.window.dark{background:var(--black);color:var(--white)}
.window.dark h2,.window.dark h3{color:var(--white)}
.window.dark p,.window.dark .small{color:var(--onl66)}
.wtop{display:flex;flex-wrap:wrap;gap:10px 28px;align-items:baseline;margin-bottom:22px}
.wtop h2{margin:0}
.wtop .r{margin-left:auto;font:400 13px/1.4 var(--font);color:var(--ink66);max-width:34em}
.window.dark .wtop .r{color:var(--onl66)}

/* 1 · kort fortalt */
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.card{background:var(--white100);border-radius:24px;padding:24px 24px 26px;min-width:0}
.card.accent{background:var(--purple)}
.cards>.intblock{min-width:0;display:contents}
.card .lb{font:400 13px/1.4 var(--font);color:var(--ink66)}
.card .fig{font:400 clamp(34px,4.4vw,54px)/1.02 var(--font);letter-spacing:-.032em;margin:14px 0 4px}
.card .fig.alert{color:var(--alert)}
.card .fig small{font-size:.36em;letter-spacing:-.01em;color:var(--ink66);margin-left:8px}
.card .who{font:400 20px/1.25 var(--font);letter-spacing:-.014em;margin:0 0 10px}
.card .sen{font:400 15px/1.55 var(--font);margin:0;max-width:28em}
.card .sen em{font-style:normal;border-bottom:1px solid var(--line)}
.card .ref{font:400 12.5px/1.5 var(--font);color:var(--ink66);margin-top:14px;padding-top:12px;
  border-top:1px solid var(--line8)}

/* pills */
.pills{display:flex;flex-wrap:wrap;gap:10px}
.pill{border:1px solid var(--black);border-radius:999px;padding:9px 18px;font:400 15px/1.3 var(--font);
  color:var(--black);transition:background .12s,color .12s}
.pill:hover{background:rgba(11,11,38,.06)}
.pill[aria-pressed="true"]{background:var(--black);color:var(--white)}
.window.dark .pill{border-color:var(--onl22);color:var(--white)}
.window.dark .pill:hover{background:rgba(254,251,230,.1)}
.window.dark .pill[aria-pressed="true"]{background:var(--white);color:var(--black);border-color:var(--white)}

/* 2 · intentioner og spørgsmål */
.intents{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:26px}
.itile{background:var(--white100);border:1px solid var(--line8);border-radius:24px;
  padding:18px 18px 20px;text-align:left}
.itile:hover{border-color:var(--line)}
.itile[aria-pressed="true"]{background:var(--black);border-color:var(--black);color:var(--white)}
.itile .n{font:400 17px/1.25 var(--font)}
.itile .q{font:400 38px/1 var(--font);letter-spacing:-.03em;margin:10px 0 2px}
.itile .u{font:400 13px/1.4 var(--font);color:var(--ink66)}
.itile[aria-pressed="true"] .u{color:var(--onl66)}
.itile .ticks{display:flex;gap:3px;margin-top:14px;flex-wrap:wrap}
.itile .ticks i{width:8px;height:14px;border-radius:2px;background:rgba(11,11,38,.16);display:block}
.itile .ticks i.doc{background:var(--green)}
.itile .ticks i.err{box-shadow:inset 0 0 0 2px var(--black)}
.itile[aria-pressed="true"] .ticks i{background:var(--onl22)}
.itile[aria-pressed="true"] .ticks i.doc{background:var(--green)}
.itile[aria-pressed="true"] .ticks i.err{box-shadow:inset 0 0 0 2px var(--white)}
.tickkey{display:flex;flex-wrap:wrap;gap:8px 22px;margin:-14px 0 26px;font-size:13px;color:var(--ink66)}
.tickkey span{display:flex;align-items:center;gap:8px}
.tickkey i{width:8px;height:14px;border-radius:2px;background:var(--green);display:block}
.tickkey i.err{box-shadow:inset 0 0 0 2px var(--black)}

.qsplit{display:grid;grid-template-columns:1.1fr 1fr;gap:40px}
.qrow{display:grid;grid-template-columns:56px 1fr 92px;gap:0 12px;width:100%;text-align:left;
  align-items:baseline;padding:12px 0;border-top:1px solid var(--line8)}
.qrow .id{font:400 13px/1.55 var(--font);color:var(--ink66)}
.qrow .tx{font:400 16.5px/1.5 var(--font)}
.qrow:hover .tx{color:var(--blue)}
.qrow[aria-expanded="true"] .tx{color:var(--blue)}
.qflag{font:400 12.5px/1.4 var(--font);color:var(--alert);text-align:right}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 22px;max-width:var(--measure)}
.chip{border:1px solid var(--line);border-radius:999px;padding:6px 14px;font:400 14.5px/1.3 var(--font)}
.chip s{text-decoration:none;color:var(--ink66);font-size:12.5px;margin-left:4px}

.detail{margin-top:26px;background:var(--lpink);border-radius:24px;padding:26px 28px 24px}
.verbatim{font:400 clamp(20px,2.1vw,26px)/1.34 var(--font);letter-spacing:-.014em;
  margin:10px 0 20px;max-width:26em}
.qcells{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}
.qcell{min-width:0}
.qcell-head{font:400 15px/1.3 var(--font);padding-bottom:8px;border-bottom:1px solid var(--line)}
.qcell-head em{display:block;font-style:normal;font-size:13px;color:var(--ink66);margin-top:2px}
.qents{list-style:none;margin:10px 0 0;padding:0}
.qents li{display:grid;grid-template-columns:1fr auto;gap:0 10px;padding:5px 0;
  border-bottom:1px solid rgba(11,11,38,.06);font-size:14.5px;line-height:1.35}
.qents .en{grid-column:1;grid-row:1;min-width:0;overflow-wrap:anywhere}
.qents .et{grid-column:1;grid-row:2;font-size:12px;color:var(--ink66)}
.qents .ec{grid-column:2;grid-row:1 / span 2;align-self:center;display:flex;align-items:center;
  gap:5px;font-size:12.5px;color:var(--ink66);white-space:nowrap}
.qents .ec i{width:6px;height:11px;border-radius:2px;background:rgba(11,11,38,.14);display:block}
.qents .ec i.on{background:var(--black)}
.qnone{font-size:14px;color:var(--ink66);margin:10px 0 0}
.qerr{font:400 13.5px/1.45 var(--font);color:var(--alert);margin:10px 0 0}
.qmeta{font-size:12.5px;color:var(--ink66);margin-top:10px}
.qruns{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.qrun{border:1px solid var(--line);border-radius:999px;padding:4px 12px;font:400 13px/1.4 var(--font)}
.qrun:hover{border-color:var(--black)}
.qrun[aria-pressed="true"]{background:var(--black);color:var(--white);border-color:var(--black)}
.quote{border-left:2px solid var(--blue);padding:2px 0 2px 20px;margin:18px 0;max-width:44em}
.quote p{font:400 19px/1.5 var(--font);margin:0 0 8px}
.quote p b{font-weight:400;border-bottom:1px solid var(--line)}
.quote p i{font-style:italic}
.quote .src{font:400 13px/1.5 var(--font);color:var(--ink66)}
mark.gone{background:transparent;color:var(--alert)}
.tr{margin-top:22px;border-top:1px solid var(--line);padding-top:16px}
.tr-head{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline;font:400 13px/1.4 var(--font);
  color:var(--ink66);margin-bottom:12px}
.tr-close{margin-left:auto;border:1px solid var(--line);border-radius:999px;padding:3px 12px;font-size:13px}
.tr-text{border-left:2px solid var(--blue);padding-left:20px;white-space:pre-wrap;
  font:400 15.5px/1.6 var(--font);max-width:46em;overflow-wrap:anywhere}
.tr-text strong{font-weight:700}
.tr-text em{font-style:italic}
.tr-text b.th{display:block;font-weight:400;font-size:17px;letter-spacing:-.012em;
  margin:22px 0 6px;color:var(--black)}
.tr-text b.th:first-child{margin-top:0}

/* 3 · matrix */
.famhead{font:400 17px/1.3 var(--font);color:var(--ink66);margin:0 0 16px;letter-spacing:0}
.window.dark .famhead{color:var(--onl66)}
.tls{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:0 0 26px;
  padding-bottom:22px;border-bottom:1px solid var(--onl22)}
.tl{min-width:0}
.tl-c{font:400 13px/1.4 var(--font);color:var(--onl66)}
.tl-c em{font-style:normal;display:block}
.tl-v{font:400 30px/1.1 var(--font);letter-spacing:-.03em;margin:6px 0 4px}
.tl-s{font:400 12.5px/1.45 var(--font);color:var(--onl66)}
.mwrap{overflow-x:auto}
table.m{width:100%;border-collapse:collapse}
.m th{font:400 13px/1.4 var(--font);color:var(--onl66);text-align:left;vertical-align:bottom;
  padding:0 14px 12px 0;border-bottom:1px solid var(--onl22)}
.m th span{display:block;color:var(--white);font-size:17px;letter-spacing:-.012em;margin-top:2px}
.m td{padding:14px 14px 14px 0;border-bottom:1px solid rgba(254,251,230,.12);vertical-align:middle}
.m td.name{min-width:200px;font:400 17px/1.3 var(--font);letter-spacing:-.01em}
.m td.name i{display:block;font-style:normal;font-size:13px;color:var(--onl66);margin-top:2px}
.m td.name i.gone{color:var(--pink100)}
.m td.name .mark{display:none;align-items:center;gap:6px;margin-top:6px;width:fit-content;
  font:400 12.5px/1.4 var(--font);color:var(--green)}
.m td.name .mark b{width:8px;height:8px;border-radius:2px;background:var(--green);display:block}
.m tr.grp td{padding:26px 0 8px;border-bottom:0;font:400 13px/1.4 var(--font);color:var(--onl66)}
.m tr.grp .grp-dot{display:inline-block;width:26px;height:12px;border-radius:6px;margin-right:10px;
  vertical-align:-1px}
.grp-dot.vis{background:var(--purple100)}
.grp-dot.mar{background:var(--pink100)}
.grp-dot.usy{background:var(--white);opacity:.5}
.cellcol{min-width:140px}
.track{position:relative;height:14px;border-radius:7px;background:rgba(254,251,230,.09)}
.rng{position:absolute;top:0;bottom:0;border-radius:7px;background:rgba(254,251,230,.2)}
.bar{position:absolute;left:0;top:0;bottom:0;border-radius:7px;background:var(--purple100)}
.bar.seen{min-width:3px}
.bar.mar{background:var(--pink100)}
.bar.usy{background:var(--white);opacity:.5}
.num{font:400 17px/1.3 var(--font);letter-spacing:-.014em;margin-top:8px;color:var(--purple100)}
.num.mar{color:var(--pink100)}
.num.usy{color:var(--onl66)}
.num s{text-decoration:none;font-size:12.5px;color:var(--onl66);margin-left:6px;white-space:nowrap}
.num u{text-decoration:none;font-size:13px;color:var(--onl66)}
.band{font:400 12.5px/1.4 var(--font);color:var(--onl66);margin-top:2px}
.keys{display:flex;flex-wrap:wrap;gap:12px 26px;margin-top:24px;font-size:13.5px;color:var(--onl66)}
.keys div{display:flex;gap:9px;align-items:center}
.k{width:26px;height:12px;border-radius:6px;flex:none}
.k.v{background:var(--purple100)}.k.m{background:var(--pink100)}
.k.u{background:var(--white);opacity:.5}.k.r{background:rgba(254,251,230,.2)}
.k.o{background:var(--green);width:12px}
.kd{color:var(--white);font-size:15px}

/* lyse tabeller */
table.t{width:100%;border-collapse:collapse;font-size:16px;margin-top:8px}
.t th{font:400 13px/1.4 var(--font);color:var(--ink66);text-align:right;padding:0 0 12px 14px;
  border-bottom:1px solid var(--black);vertical-align:bottom}
.t th:first-child{text-align:left;padding-left:0}
.t td{padding:14px 0 14px 14px;border-bottom:1px solid var(--line8);text-align:right}
.t td:first-child{text-align:left;padding-left:0}
.t td.txt,.t th.txt{text-align:left;color:var(--ink66);font-size:15px}
.t.app{font-size:15px;min-width:860px}
.t.app td{padding:9px 0 9px 14px}
.t.app td:first-child,.t.app th:first-child{padding-left:0}
.t.app tr:first-child td{padding-top:14px}
.t.app td.ent{font-size:16px}
.t.app td.ent.cont{color:transparent}

/* 4 · lukkede kæder */
.gonelist{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:0 0 30px}
.gonerow{border-top:1px solid var(--black);padding-top:14px;min-width:0}
.gonerow .a{font:400 21px/1.25 var(--font);letter-spacing:-.014em}
.gonerow .b{font:400 13px/1.4 var(--font);color:var(--alert);margin:2px 0 8px}
.gonerow .c{font:400 14.5px/1.5 var(--font);color:var(--ink66);max-width:30em}

/* 5 · forbehold */
.lims{display:grid;grid-template-columns:1fr 1fr;gap:0 48px}
.lim{padding:20px 0;border-top:1px solid rgba(11,11,38,.18)}
.lim .n{font:400 13px/1.4 var(--font);color:var(--ink66)}
.lim h4{font:400 21px/1.3 var(--font);letter-spacing:-.014em;margin:6px 0 8px}
.lim p{font:400 15px/1.58 var(--font);margin:0;max-width:30em}

.foot{margin-top:12px;border-top:1px solid var(--line);padding-top:18px;display:flex;flex-wrap:wrap;
  gap:8px 32px;font-size:13px;color:var(--ink66)}

/* tilstand: familie og intention styres af to attributter, ikke af genrendering */
#report[data-fam="brands"] .fam-shops{display:none}
#report[data-fam="shops"] .fam-brands{display:none}
#report[data-intent="pris"] .intblock:not(.int-pris),
#report[data-intent="smag"] .intblock:not(.int-smag),
#report[data-intent="anvendelse"] .intblock:not(.int-anvendelse),
#report[data-intent="vaerdier"] .intblock:not(.int-vaerdier),
#report[data-intent="sammenligning"] .intblock:not(.int-sammenligning){display:none}
#report[data-intent="pris"] .mark[data-int="pris"],
#report[data-intent="smag"] .mark[data-int="smag"],
#report[data-intent="anvendelse"] .mark[data-int="anvendelse"],
#report[data-intent="vaerdier"] .mark[data-int="vaerdier"],
#report[data-intent="sammenligning"] .mark[data-int="sammenligning"]{display:flex}

@media (max-width:1040px){
  .wrap{padding:0 24px 64px}
  /* Invariant: udløbsdatoen skal kunne ses uden at scrolle — også ved 380px.
     Derfor flytter stemplet op over rubrikken, når forsiden bliver én kolonne. */
  .hero{display:flex;flex-direction:column;gap:32px}
  .heroside{display:contents}
  .stampbox{order:-1}
  .facts{order:1;margin-top:0;border-top:0;padding-top:0}
  .cards{grid-template-columns:1fr 1fr}
  .intents{grid-template-columns:1fr 1fr 1fr}
  .qsplit,.lims{grid-template-columns:1fr;gap:28px}
  .qcells,.tls,.gonelist{grid-template-columns:1fr 1fr}
}
@media (max-width:560px){
  .wrap{padding:0 16px 56px}
  .window{padding:24px 20px 26px;border-radius:24px}
  .cards{grid-template-columns:1fr}
  .intents{grid-template-columns:1fr 1fr}
  .aurora{height:96px;border-radius:24px;margin-bottom:28px}
  .qrow{grid-template-columns:1fr}
  .qrow .id{margin-bottom:2px}
  .qflag{text-align:left;margin-top:4px}
  .qflag br{display:none}
  .qcells,.tls,.gonelist{grid-template-columns:1fr}
  .detail{padding:22px 18px}
  .cellcol{min-width:118px}
  .m td.name{min-width:140px}
}
@media print{
  body{background:#fff;font-size:10.5pt}
  .aurora,.noprint,.tr{display:none !important}
  .pills,.itile .ticks{display:none}
  .window{border-radius:0;padding:0;margin:0 0 22pt;background:#fff !important;color:#000 !important;border:0}
  .window.dark{border:1pt solid #000;padding:12pt}
  .window.dark h2,.window.dark h3,.window.dark p,.window.dark .small{color:#000}
  .m th,.m td,.m th span,.num,.band,.tl-v,.tl-s,.tl-c,.famhead{color:#000 !important}
  .m td,.m th{border-color:#999}
  .tls{border-bottom:1pt solid #000}
  .qpanel[hidden]{display:block !important}
  .detail{background:#fff;border:1pt solid #000}
  #report .intblock,#report .famblock,#report .mark{display:block !important}
  .window,tr,.lim,.card,.qpanel{break-inside:avoid}
}
"""

JS = r"""
(function () {
  var report = document.getElementById('report');
  if (!report) return;
  var blob = document.getElementById('qdata');
  var DATA = blob ? JSON.parse(blob.textContent) : {answers: {}, cellLabels: {}};

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c];
    });
  }

  // Transcripts are shown as transcripts: whitespace preserved, and only the
  // markdown the models actually wrote is interpreted — headings, bold, italic,
  // bullets. Everything is escaped first; nothing else is touched. A
  // half-working renderer would quietly misrepresent the evidence.
  function transcript(text) {
    return esc(text)
      .replace(/\n*^#{1,6}[ \t]*(.+)$\n*/gm, '<b class="th">$1</b>')
      .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s.,;:)]|$)/g, '$1<em>$2</em>')
      .replace(/^[ \t]*[-–][ \t]+/gm, '– ');
  }

  function setFamily(fam) {
    report.dataset.fam = fam;
    report.querySelectorAll('[data-fam]').forEach(function (b) {
      if (b.tagName === 'BUTTON') b.setAttribute('aria-pressed', String(b.dataset.fam === fam));
    });
  }

  function setIntent(intent) {
    report.dataset.intent = intent;
    report.querySelectorAll('.itile').forEach(function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.int === intent));
    });
    closePanels();
  }

  function closePanels() {
    report.querySelectorAll('.qpanel').forEach(function (p) { p.hidden = true; });
    report.querySelectorAll('.qrow').forEach(function (r) {
      r.setAttribute('aria-expanded', 'false');
    });
  }

  function togglePanel(row) {
    var open = row.getAttribute('aria-expanded') === 'true';
    closePanels();
    if (open) return;
    var panel = document.getElementById('p-' + row.dataset.q);
    if (!panel) return;
    row.setAttribute('aria-expanded', 'true');
    panel.hidden = false;
    panel.scrollIntoView({block: 'nearest'});
  }

  function showRun(button) {
    var panel = button.closest('.qpanel');
    if (!panel) return;
    var slot = panel.querySelector('.tslot');
    var qid = button.dataset.q, cell = button.dataset.cell, pass = button.dataset.pass;
    var pressed = button.getAttribute('aria-pressed') === 'true';
    panel.querySelectorAll('.qrun').forEach(function (b) {
      b.setAttribute('aria-pressed', 'false');
    });
    if (pressed) { slot.innerHTML = ''; return; }
    var list = DATA.answers[qid] || [];
    var hit = null;
    for (var i = 0; i < list.length; i++) {
      if (list[i].cell === cell && String(list[i].pass) === String(pass)) hit = list[i];
    }
    if (!hit) { slot.innerHTML = ''; return; }
    button.setAttribute('aria-pressed', 'true');
    var label = DATA.cellLabels[cell] || [cell, ''];
    slot.innerHTML =
      '<div class="tr"><div class="tr-head"><span>Transkript · ' + esc(label[0]) + ' ' +
      esc(label[1]) + ' · kørsel ' + esc(pass) + ' · uredigeret</span>' +
      '<span>modellens ord, ikke rapportens</span>' +
      '<button type="button" class="tr-close">luk</button></div>' +
      '<div class="tr-text">' + transcript(hit.text) + '</div></div>';
  }

  report.addEventListener('click', function (ev) {
    var pill = ev.target.closest('.pill[data-fam]');
    if (pill) { setFamily(pill.dataset.fam); return; }
    var tile = ev.target.closest('.itile');
    if (tile) { setIntent(tile.dataset.int); return; }
    var row = ev.target.closest('.qrow');
    if (row) { togglePanel(row); return; }
    var run = ev.target.closest('.qrun');
    if (run) { showRun(run); return; }
    var close = ev.target.closest('.tr-close');
    if (close) {
      var panel = close.closest('.qpanel');
      panel.querySelector('.tslot').innerHTML = '';
      panel.querySelectorAll('.qrun').forEach(function (b) {
        b.setAttribute('aria-pressed', 'false');
      });
    }
  });

  setFamily(report.dataset.fam || 'brands');
  setIntent(report.dataset.intent);
})();
"""


def build(result: dict, answers: list[dict]) -> str:
    meta = result["meta"]
    measured = (meta["last_answer"] or datetime.now(timezone.utc).isoformat())[:10]
    expires = (
        datetime.fromisoformat(measured) + timedelta(days=config.SHELF_LIFE_DAYS)
    ).strftime("%d.%m.%Y")

    brands = family(result, "maerke")
    shops = family(result, "butik")
    first_intent = next(iter(result["by_intent"]))

    grouped: dict[str, list[dict]] = {}
    for answer in answers:
        grouped.setdefault(answer["prompt_id"], []).append(answer)
    payload = {
        "cellLabels": {k: list(v) for k, v in CELL_LABELS.items()},
        "answers": {
            qid: [
                {
                    "cell": f"{a['model_key']}/{a['condition']}",
                    "pass": int(a["pass"]),
                    "text": a["text"],
                }
                for a in sorted(
                    items,
                    key=lambda a: (
                        CELL_ORDER.index(f"{a['model_key']}/{a['condition']}"),
                        int(a["pass"]),
                    ),
                )
            ]
            for qid, items in grouped.items()
        },
    }
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    # What a shared link says about itself. Derived, like everything else, so a
    # rerun with other numbers cannot leave a stale claim in the preview card.
    share_text = (
        f"{meta['questions']} danske spørgsmål om mejeri, stillet i "
        f"{len(meta['cells'])} kombinationer × {len(meta['passes'])} kørsler = "
        f"{meta['answers']} svar. Hvilke mærker og dagligvarekæder nævner "
        f"sprogmodellerne — og hvem findes slet ikke i svaret? Målt "
        f"{dk_date(measured)}, mindst holdbar til {expires}."
    )

    body = f"""
{cover(result, measured, expires)}
{summary_cards(result, brands, shops)}
{questions_section(result, answers)}
{matrix_section(result, brands, shops)}
{defunct_section(result)}
{limitations_section()}
{method_section(result)}
{appendix(result, brands, shops)}
<div class="foot">
  <span>Måling {esc(dk_date(measured))}</span>
  <span>Mindst holdbar til {esc(expires)}</span>
  <span>{esc(meta['questions'])} spørgsmål · {esc(len(meta['cells']))} kombinationer ·
    {esc(meta['answers'])} svar</span>
  <span>Ingen anbefalinger til navngivne virksomheder</span>
</div>
"""

    return f"""<!doctype html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive">
<title>Synlighed i sprogmodeller · dansk mejeri · måling {esc(dk_date(measured))}</title>
<meta name="description" content="{esc(share_text)}">
<meta property="og:type" content="article">
<meta property="og:locale" content="da_DK">
<meta property="og:title" content="Synlighed i sprogmodeller · dansk mejeri">
<meta property="og:description" content="{esc(share_text)}">
<meta name="twitter:card" content="summary">
<style>{CSS}</style>
</head>
<body>
<div class="wrap" id="report" data-fam="brands" data-intent="{esc(first_intent)}">
{body}
</div>
<noscript><p style="padding:0 40px 40px;color:#E31F04;max-width:724px">Uden JavaScript
står siden på første intention og på mærketabellen, og spørgsmålspanelerne kan ikke
åbnes. Alt indhold er stadig i dokumentet — udskriv siden (eller gem den som PDF), så
foldes alle intentioner, begge entitetstabeller og alle {esc(meta['questions'])}
spørgsmålspaneler ud.</p></noscript>
<script type="application/json" id="qdata">{blob}</script>
<script>{JS}</script>
</body>
</html>
"""


def main() -> int:
    result = load()
    answers = load_answers()
    config.REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.REPORT_PATH.write_text(build(result, answers), encoding="utf-8")
    size_kb = config.REPORT_PATH.stat().st_size / 1024
    print(f"Skrev {config.REPORT_PATH} ({size_kb:.0f} kB)")
    print("Åbn den lokalt for at kontrollere, at den renderer uden netværk:")
    print(f"  open {config.REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
