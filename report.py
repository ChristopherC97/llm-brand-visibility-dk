"""Builds the report: one self-contained HTML file, no build step, no CDN.

Usage:
    python3 analyze.py && python3 report.py

Writes docs/index.html — a single file with inlined CSS, no external fonts,
no scripts, no chart library. It must still open in three years, and it must
render with the network cable pulled out.

Visual direction is Danish milk-carton print: raw board, printed ink blue, a
red date stamp, monospaced figures on anything measured. The signature element
is the "Mindst holdbar til" stamp, because the most honest thing about an
LLM measurement is that it expires.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone

import config

CELL_LABELS = {
    "claude/nosearch": ("Claude", "uden søgning"),
    "claude/search": ("Claude", "med søgning"),
    "gpt/nosearch": ("GPT", "uden søgning"),
    "gpt/search": ("GPT", "med søgning"),
}
CELL_ORDER = ["claude/nosearch", "claude/search", "gpt/nosearch", "gpt/search"]


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def load() -> dict:
    if not config.METRICS_PATH.exists():
        raise SystemExit(
            f"Mangler {config.METRICS_PATH}.\nKør først:  python3 analyze.py"
        )
    return json.loads(config.METRICS_PATH.read_text(encoding="utf-8"))


def load_answers() -> list[dict]:
    """All 420 answers, published in full alongside the report.

    The artifact's central claim is that anyone can re-run it and get the same
    numbers. Keeping the evidence behind the numbers hidden would weaken
    exactly that claim, so the transcripts ship with the page.
    """
    path = config.DATA_DIR / "answers.json"
    if not path.exists():
        raise SystemExit(f"Mangler {path}.\nKør først:  python3 analyze.py")
    return json.loads(path.read_text(encoding="utf-8"))


# --- Components --------------------------------------------------------------


def bar_group(data: dict, cells: list[str]) -> str:
    """Four thin bars per entity — one per cell. Never a pooled figure."""
    rows = []
    for cell in cells:
        stats = data["cells"].get(cell)
        if not stats:
            continue
        model, condition = CELL_LABELS.get(cell, (cell, ""))
        rate = stats["mention_rate"]
        dagger = config.BOUNDARY_MARKER if stats["boundary_uncertain"] else ""
        rows.append(
            f'<div class="bar-row">'
            f'<span class="bar-label">{esc(model)} <em>{esc(condition)}</em></span>'
            f'<span class="bar-track"><span class="bar-fill" style="width:{rate * 100:.1f}%"></span></span>'
            f'<span class="bar-value">{pct(rate)}{dagger}</span>'
            f"</div>"
        )
    if not rows:
        return ""
    note = f' <span class="note">{esc(data["note"])}</span>' if data.get("note") else ""
    return (
        f'<div class="entity">'
        f'<div class="entity-name">{esc(data["display"])}{note}</div>'
        f'{"".join(rows)}'
        f"</div>"
    )


def chart(result: dict, entity_type: str, heading: str, blurb: str) -> str:
    cells = [cell for cell in CELL_ORDER if cell in result["meta"]["cells"]]
    ranked = [
        data for data in result["entities"].values()
        if data["type"] == entity_type
        and any(stat["mentions"] for stat in data["cells"].values())
    ]
    ranked.sort(
        key=lambda d: -max((s["mention_rate"] for s in d["cells"].values()), default=0)
    )
    ranked = ranked[: config.TOP_N_CHART]
    if not ranked:
        return f"<h2>{esc(heading)}</h2><p>Ingen {esc(entity_type)}er blev nævnt i målingen.</p>"

    groups = "".join(bar_group(data, cells) for data in ranked)
    return (
        f"<h2>{esc(heading)}</h2>"
        f"<p>{blurb}</p>"
        f'<div class="chart">{groups}</div>'
        f'<p class="footnote">Hver entitet vises i alle fire celler hver for sig. '
        f"Der findes ikke ét samlet tal i denne rapport — en model med søgning og "
        f"en uden er ikke den samme population. "
        f"{config.BOUNDARY_MARKER} betyder, at konfidensintervallet krydser en båndgrænse, "
        f"så entitetens bånd ikke er afgjort.</p>"
    )


def key_figures(result: dict) -> str:
    meta = result["meta"]
    bands = {"synlig": 0, "marginal": 0, "usynlig": 0}
    for data in result["entities"].values():
        best = max(
            (stat for stat in data["cells"].values()),
            key=lambda s: s["mention_rate"],
            default=None,
        )
        if best and best["mentions"]:
            bands[best["band"]] = bands.get(best["band"], 0) + 1

    tiles = [
        ("Svar indsamlet", f'{meta["answers"]}', f'{meta["questions"]} spørgsmål × {len(meta["cells"])} celler'),
        ("Synlige entiteter", f'{bands["synlig"]}', "nævnt i over 40 % af svarene"),
        ("Marginale", f'{bands["marginal"]}', "10–40 % — til stede, men ikke pålideligt"),
        ("Usynlige", f'{bands["usynlig"]}', "under 10 % — nævnt, men næsten aldrig"),
    ]
    cards = "".join(
        f'<div class="tile"><div class="tile-label">{esc(label)}</div>'
        f'<div class="tile-value">{esc(value)}</div>'
        f'<div class="tile-sub">{esc(sub)}</div></div>'
        for label, value, sub in tiles
    )

    rows = "".join(
        f"<tr><td>{esc(CELL_LABELS.get(cell, (cell, ''))[0])} "
        f"<em>{esc(CELL_LABELS.get(cell, ('', cell))[1])}</em></td>"
        f'<td class="num">{pct(t["share_with_brand"])}</td>'
        f'<td class="num">{pct(t["share_with_store"])}</td>'
        f'<td class="num">{t["avg_brands_per_answer"]}</td>'
        f'<td class="num">{t["avg_stores_per_answer"]}</td></tr>'
        for cell, t in sorted(result["toplines"].items(), key=lambda kv: CELL_ORDER.index(kv[0]) if kv[0] in CELL_ORDER else 99)
    )

    return (
        f"<h2>Nøgletal</h2>"
        f'<div class="tiles">{cards}</div>'
        f'<div class="scroll"><table>'
        f"<thead><tr><th>Celle</th><th>Svar med mærke</th><th>Svar med butik</th>"
        f"<th>Mærker pr. svar</th><th>Butikker pr. svar</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        f'<p class="jump noprint"><a href="#register">Gå til spørgsmålsregisteret — alle 35 spørgsmål og alle 420 svar i fuld længde →</a></p>'
        f'<p class="footnote">Butiks- og mærketal må ikke sammenlignes indbyrdes. '
        f"De deler nævner, men ikke mulighedsrum: et prisspørgsmål kan fremkalde en "
        f"butik, et smagsspørgsmål kan ikke.</p>"
    )


def defunct_section(result: dict) -> str:
    defunct = result["defunct"]
    total_errors = sum(c["answers_with_error"] for c in defunct["per_cell"].values())

    chains = "".join(
        f"<li><strong>{esc(c['display'])}</strong> — ophørte {esc(c['ended'])}. {esc(c['detail'])}</li>"
        for c in defunct["chains"].values()
    )

    if total_errors == 0:
        body = (
            "<p><strong>Ingen af modellerne anbefalede en udgået kæde i denne måling.</strong> "
            "Sektionen står alligevel, fordi tjekket er en del af metoden og ikke af resultatet.</p>"
        )
    else:
        rows = "".join(
            f"<tr><td>{esc(CELL_LABELS.get(cell, (cell, ''))[0])} "
            f"<em>{esc(CELL_LABELS.get(cell, ('', cell))[1])}</em></td>"
            f'<td class="num">{stats["answers_with_error"]}/{stats["answers"]}</td>'
            f'<td class="num">{pct(stats["error_rate"])}</td>'
            f'<td class="num">{stats["answers_stating_closure_correctly"]}</td></tr>'
            for cell, stats in sorted(
                defunct["per_cell"].items(),
                key=lambda kv: CELL_ORDER.index(kv[0]) if kv[0] in CELL_ORDER else 99,
            )
        )
        quotes = "".join(
            f"<blockquote>{esc(q['quote'])}"
            f"<cite>{esc(CELL_LABELS.get(q['cell'], (q['cell'], ''))[0])} "
            f"{esc(CELL_LABELS.get(q['cell'], ('', q['cell']))[1])} — "
            f"spørgsmål: {esc(q['question'])}</cite></blockquote>"
            for q in defunct["quotes"][:3]
        )
        body = (
            f'<div class="scroll"><table>'
            f"<thead><tr><th>Celle</th><th>Svar med fejl</th><th>Andel</th>"
            f"<th>Svar der beskriver lukningen korrekt</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
            f"<p>Ordret, fra de rå svar:</p>{quotes}"
        )

    return (
        f'<h2 class="alarm-heading">Udgåede kæder</h2>'
        f"<p>Tre danske dagligvarekæder findes ikke længere:</p>"
        f"<ul>{chains}</ul>"
        f"<p>Anbefales de stadig, er det ikke en smagssag. Det er faktuelt forkert "
        f"købsråd, leveret med samme sikkerhed som det rigtige, og en forbruger kan "
        f"ikke se forskel.</p>"
        f"{body}"
        f'<p class="footnote">En omtale tælles kun som fejl, hvis den står uden en '
        f"lukningsmarkør i nærheden. Et svar som «Aldi forlod Danmark i 2023» er "
        f"modellen der har ret, og tælles ikke som fejl.</p>"
    )


def full_table(result: dict) -> str:
    cells = [cell for cell in CELL_ORDER if cell in result["meta"]["cells"]]
    rows = []
    entries = [
        data for data in result["entities"].values()
        if any(stat["mentions"] for stat in data["cells"].values())
    ]
    entries.sort(key=lambda d: (d["type"], -max(s["mention_rate"] for s in d["cells"].values())))

    for data in entries:
        for cell in cells:
            stats = data["cells"].get(cell)
            if not stats or not stats["mentions"]:
                continue
            model, condition = CELL_LABELS.get(cell, (cell, ""))
            dagger = config.BOUNDARY_MARKER if stats["boundary_uncertain"] else ""
            rows.append(
                f"<tr><td>{esc(data['display'])}</td><td>{esc(data['type'])}</td>"
                f"<td>{esc(model)} <em>{esc(condition)}</em></td>"
                f'<td class="num">{pct(stats["mention_rate"])}{dagger}</td>'
                f'<td class="num">{pct(stats["ci_low"])}–{pct(stats["ci_high"])}</td>'
                f'<td class="num">{pct(stats["share_of_voice"])}</td>'
                f'<td class="num">{pct(stats["first_mentioned_rate"])}</td>'
                f'<td class="num">{pct(stats["consistency"])}</td>'
                f'<td class="num">{esc(stats["band"])}</td></tr>'
            )
    return (
        f"<h2>Fuld tabel</h2>"
        f'<div class="scroll"><table><thead><tr>'
        f"<th>Entitet</th><th>Type</th><th>Celle</th><th>Omtale-rate</th>"
        f"<th>95 % interval</th><th>Share of voice</th><th>Først nævnt</th>"
        f"<th>Konsistens</th><th>Bånd</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
        f'<p class="footnote">{esc(result["meta"]["ci_note"])} '
        f"Konsistens er andelen af kørsler, hvor entiteten optrådte, blandt de "
        f"spørgsmål hvor den optrådte mindst én gang. En entitet med lav konsistens "
        f"er ikke synlig — den er heldig.</p>"
    )


def disagreement_section(result: dict) -> str:
    blocks = []
    for condition, data in result["disagreement"].items():
        label = "uden websøgning" if condition == "nosearch" else "med websøgning"
        only = {k: v for k, v in data.items() if k.startswith("only_in_")}
        lists = "".join(
            f"<p><strong>Kun {esc(key.replace('only_in_', ''))}:</strong> "
            f"{esc(', '.join(values)) if values else 'ingen'}</p>"
            for key, values in only.items()
        )
        blocks.append(
            f"<h3>{esc(label)}</h3>"
            f'<p>Jaccard-overlap mellem modellernes top-10: <span class="mono">{data["jaccard"]:.2f}</span></p>'
            f"<p><strong>Nævnt af begge:</strong> {esc(', '.join(data['shared'])) or 'ingen'}</p>"
            f"{lists}"
        )
    return (
        f"<h2>Modeluenighed</h2>"
        f"<p>Overlappet er beregnet inden for hver betingelse. At sammenligne en "
        f"søgende model med en ikke-søgende ville måle indstillingen, ikke modellerne.</p>"
        f"{''.join(blocks)}"
        f'<p class="footnote">Et lavt overlap betyder, at hvilken model forbrugeren '
        f"tilfældigvis bruger, afgør hvilke mærker de præsenteres for.</p>"
    )


def intent_section(result: dict) -> str:
    rows = "".join(
        f"<tr><td>{esc(intent)}</td>"
        f'<td class="num">{data["questions"]}</td>'
        f'<td>{esc(", ".join(data["top_stores"])) or "—"}</td>'
        f'<td>{esc(", ".join(data["top_brands"])) or "—"}</td></tr>'
        for intent, data in result["by_intent"].items()
    )
    return (
        f"<h2>Opdeling på spørgsmålstype</h2>"
        f"<p>Denne sektion er bevidst kvalitativ. Med 35 spørgsmål fordelt på fem "
        f"intentioner ville en procent per intention hvile på syv spørgsmål — det er "
        f"anekdote med decimaler på. Retningen er derimod tydelig nok til at nævne.</p>"
        f'<div class="scroll"><table><thead><tr><th>Intention</th><th>Spørgsmål</th>'
        f"<th>Hyppigste butikker</th><th>Hyppigste mærker</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def limitations() -> str:
    return """
<h2>Hvad målingen ikke kan sige</h2>
<p>Denne sektion er ikke en formalitet. Den er forskellen på en analyse og en pitch.</p>
<h3>Volumen</h3>
<p>Målingen siger intet om, hvor mange danskere der faktisk spørger en sprogmodel til
råds, før de handler ind. Tallet kan være lille. Der er ingen offentligt tilgængelig
kilde, jeg kan reproducere, og jeg har bevidst undladt at bruge betalte data, fordi
en rapport hvis pointe er efterprøvelighed ikke kan hvile på et tal, læseren ikke
kan efterprøve.</p>
<h3>Årsag</h3>
<p>Målingen viser, hvad modellerne svarer — ikke hvorfor. Om et mærke nævnes ofte,
fordi det er markedsledende, fordi det fylder meget i træningsdata, eller fordi det
optræder i de kilder en søgning rammer, kan denne metode ikke afgøre. Kortlægning af
kilderne bag svarene er et selvstændigt stykke arbejde.</p>
<h3>Konvertering</h3>
<p>At blive nævnt er ikke at blive købt. Der er intet i denne måling, der forbinder en
omtale med et salg, en butiksbesøg eller så meget som et klik.</p>
<h3>Udløb</h3>
<p>Det her er et øjebliksbillede. Modeller opdateres uden varsel, søgeindekser ændrer
sig dagligt, og udbydernes standardindstillinger skifter. Kørte man det samme igen om
tre måneder, ville tallene være anderledes — og man ville ikke kunne vide, om det
skyldtes markedet eller modellen. Derfor står der en udløbsdato øverst.</p>
<h3>Repræsentativitet</h3>
<p>De 35 spørgsmål er skrevet af én person. Ingen test kan afgøre, om de repræsenterer,
hvordan danskere faktisk spørger. Spørgsmålene ligger i repoet, så man kan være
konkret uenig i dem.</p>
"""


def method_section(result: dict) -> str:
    meta = result["meta"]
    spans = "".join(
        f"<li>Kørsel {esc(s['pass'])}: {esc(s['first'][:16].replace('T', ' '))} – "
        f"{esc(s['last'][:16].replace('T', ' '))} UTC</li>"
        for s in meta["pass_spans"]
    )
    models = "".join(
        f"<li><span class=\"mono\">{esc(model_id)}</span></li>"
        for model_id in meta["models"].values()
    )
    return f"""
<h2>Metode</h2>
<p>Spørgsmålene indeholder ingen mærke- eller butiksnavne. Et spørgsmål med «Arla» i
ville måle genkendelse, ikke synlighed. Det håndhæves af en test, ikke af disciplin.</p>
<h3>Modeller</h3>
<ul>{models}</ul>
<p>Ingen systemprompt. Udbyderens øvrige standardindstillinger. Bemærk, at
standardindstillinger ikke er det samme på tværs af udbydere — <span class="mono">claude-opus-5</span>
tænker som standard. Forskelle mellem modellerne er derfor delvis forskelle mellem
udbydernes defaults, ikke kun mellem modellerne.</p>
<h3>Design</h3>
<p>Hvert spørgsmål blev stillet i fire celler: to modeller × to betingelser (uden og
med websøgning). Hver celle blev kørt {esc(len(meta['passes']))} gange.
{esc(meta['answers'])} svar i alt. {esc(meta['truncated_answers'])} svar var afkortede.</p>
<ul>{spans}</ul>
<h3>Ekstraktion</h3>
<p>Omtaler findes med ordbog og regulære udtryk. Ingen sprogmodel deltager i tællingen.
Ordbogen ligger i <span class="mono">entities.py</span> og kan gennemgås linje for linje.
Danske faldgruber er håndteret med positionelle værn: «spar penge» er ikke butikskæden
SPAR, «netto 400 gram» er ikke Netto, men «Netto har gode priser på 400 gram ost» er.
Værnene er dækket af tests, der kører uden et eneste API-kald.</p>
<p>Kun første forekomst per entitet per svar tælles. Ellers ville et langt, snakkesaligt
svar veje tungere end et kort, og så målte vi ordrigdom.</p>
<h3>Ordbogens dækning</h3>
<p>Efter ekstraktion udskrives kapitaliserede navne, som optrådte i svarene men ikke stod
i ordbogen, så hullerne findes systematisk frem for ved gætteri. Det var sådan
Coop, Milbona og Levevis kom med.</p>
<h3>Usikkerhed</h3>
<p>{esc(meta['ci_note'])}</p>
<h3>Forudregistrering</h3>
<p>Rapportens sektioner og synlighedsbåndenes grænser blev låst i
<span class="mono">report_plan.md</span> før den fulde kørsel. Git-historikken viser hvornår.</p>
<h3>Reproduktion</h3>
<p>Koden er offentlig. <span class="mono">README.md</span> beskriver, hvordan man kører
målingen igen med sine egne nøgler.</p>
"""


# --- Section 12: question register -------------------------------------------


def question_register(result: dict) -> str:
    """Static list of all 35 questions, grouped by intent.

    Rendered server-side so it survives printing and works without JavaScript.
    The interactive case file below it is progressive enhancement, not a
    prerequisite for reading the page.
    """
    by_intent: dict[str, list[dict]] = {}
    for question in result["questions"]:
        by_intent.setdefault(question["intent"], []).append(question)

    blocks = []
    for intent, items in by_intent.items():
        rows = "".join(
            f'<li><button class="q-item" data-q="{esc(q["id"])}" type="button">'
            f'<span class="q-id">{esc(q["id"])}</span>'
            f'<span class="q-text">{esc(q["text"])}</span></button></li>'
            for q in items
        )
        blocks.append(
            f'<div class="q-group"><h3 class="q-group-head">{esc(intent)}'
            f'<span class="q-count">{len(items)} spørgsmål</span></h3>'
            f"<ul class=\"q-list\">{rows}</ul></div>"
        )
    return "".join(blocks)


def question_explorer(result: dict, answers: list[dict]) -> str:
    grouped: dict[str, list[dict]] = {}
    for answer in answers:
        grouped.setdefault(answer["prompt_id"], []).append(answer)
    for items in grouped.values():
        items.sort(key=lambda a: (CELL_ORDER.index(f"{a['model_key']}/{a['condition']}"), a["pass"]))

    payload = {
        "cellOrder": CELL_ORDER,
        "cellLabels": {k: list(v) for k, v in CELL_LABELS.items()},
        "questions": {q["id"]: q for q in result["questions"]},
        "answers": {
            qid: [
                {
                    "cell": f"{a['model_key']}/{a['condition']}",
                    "pass": a["pass"],
                    "text": a["text"],
                    "entities": a["entities"],
                }
                for a in items
            ]
            for qid, items in grouped.items()
        },
    }
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    return f"""
<h2 id="register">Spørgsmålsregister</h2>
<p>Alle {esc(len(result["questions"]))} spørgsmål og alle {esc(len(answers))} svar i fuld
længde. Vælg et spørgsmål for at se, hvad hver celle svarede, hvilke entiteter der
optrådte i hvilke kørsler, og den uredigerede tekst bag tallene.</p>
<p class="footnote"><strong>Ét spørgsmål er tre svar per celle.</strong> Derfor står der
tællinger — «2 af 3 kørsler» — og aldrig procenter på dette niveau. En procent på tre
observationer er et decimaltal, der udgiver sig for at være en måling.</p>

<div class="explorer" id="explorer">
  <div class="q-register">{question_register(result)}</div>
  <div class="q-detail" id="q-detail" aria-live="polite"></div>
</div>
<p class="footnote noprint">Transkripterne er modellernes ord, ikke mine. De indeholder
modellernes egne påstande om navngivne virksomheders priser og kvalitet, gengivet
uredigeret, fordi det er grundlaget for tallene ovenfor.</p>

<script type="application/json" id="qdata">{blob}</script>
<script>
(function () {{
  var el = document.getElementById('qdata');
  if (!el) return;
  var D = JSON.parse(el.textContent);
  var detail = document.getElementById('q-detail');

  function esc(s) {{
    return String(s).replace(/[&<>"]/g, function (c) {{
      return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c];
    }});
  }}

  // Transcripts are shown as transcripts: whitespace preserved, **bold**
  // honoured, nothing else interpreted. A half-working markdown renderer
  // would quietly misrepresent the evidence.
  function transcript(text) {{
    return esc(text).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  }}

  function dots(present, total) {{
    var out = '';
    for (var i = 0; i < total; i++) {{
      out += '<span class="dot' + (i < present ? ' on' : '') + '"></span>';
    }}
    return '<span class="dots">' + out + '</span>';
  }}

  function render(qid) {{
    var q = D.questions[qid];
    if (!q) return;
    var answers = D.answers[qid] || [];

    var cols = D.cellOrder.map(function (cell) {{
      var c = q.cells[cell];
      var label = D.cellLabels[cell] || [cell, ''];
      if (!c) return '';
      var body;
      if (!c.entities.length) {{
        body = '<p class="q-none">Ingen mærker eller butikker registreret i denne celle.</p>';
      }} else {{
        body = '<ul class="q-ents">' + c.entities.map(function (e) {{
          return '<li><span class="q-ent-name">' + esc(e.display) + '</span>' +
                 '<span class="q-ent-type">' + esc(e.type) + '</span>' +
                 dots(e.runs_present, e.runs_total) + '</li>';
        }}).join('') + '</ul>';
      }}
      var flag = c.defunct_errors
        ? '<p class="q-flag">' + c.defunct_errors + ' af ' + c.runs +
          ' kørsler anbefalede en udgået kæde</p>'
        : '';
      var runs = answers.filter(function (a) {{ return a.cell === cell; }})
        .map(function (a) {{
          return '<button type="button" class="q-run" data-q="' + esc(qid) +
                 '" data-cell="' + esc(cell) + '" data-pass="' + a.pass + '">kørsel ' + a.pass + '</button>';
        }}).join('');
      return '<div class="q-cell"><div class="q-cell-head">' + esc(label[0]) +
             '<em>' + esc(label[1]) + '</em></div>' + body + flag +
             '<div class="q-runs">' + runs + '</div></div>';
    }}).join('');

    detail.innerHTML =
      '<div class="q-detail-head"><span class="q-id">' + esc(qid) + '</span>' +
      '<span class="q-intent">' + esc(q.intent) + '</span></div>' +
      '<p class="q-question">' + esc(q.text) + '</p>' +
      '<p class="q-meta">4 celler × 3 kørsler = 12 svar · tællinger, ikke procenter</p>' +
      '<div class="q-cells">' + cols + '</div>' +
      '<div id="q-transcript"></div>';

    document.querySelectorAll('.q-item').forEach(function (b) {{
      b.classList.toggle('active', b.dataset.q === qid);
    }});
  }}

  function showTranscript(qid, cell, pass) {{
    var a = (D.answers[qid] || []).filter(function (x) {{
      return x.cell === cell && x.pass === Number(pass);
    }})[0];
    var box = document.getElementById('q-transcript');
    if (!a || !box) return;
    var label = D.cellLabels[cell] || [cell, ''];
    box.innerHTML =
      '<div class="tr"><div class="tr-head">Transkript · ' + esc(label[0]) + ' ' +
      esc(label[1]) + ' · kørsel ' + esc(pass) + ' · uredigeret' +
      '<button type="button" class="tr-close">luk</button></div>' +
      '<div class="tr-body"><span class="tr-attr">Modellens ord, ikke mine</span>' +
      '<div class="tr-text">' + transcript(a.text) + '</div></div></div>';
    box.scrollIntoView({{behavior: 'smooth', block: 'nearest'}});
  }}

  document.addEventListener('click', function (ev) {{
    var item = ev.target.closest('.q-item');
    if (item) {{ render(item.dataset.q); return; }}
    var run = ev.target.closest('.q-run');
    if (run) {{ showTranscript(run.dataset.q, run.dataset.cell, run.dataset.pass); return; }}
    if (ev.target.closest('.tr-close')) {{
      document.getElementById('q-transcript').innerHTML = '';
    }}
  }});

  var first = document.querySelector('.q-item');
  if (first) render(first.dataset.q);
}})();
</script>
"""


# --- Page --------------------------------------------------------------------

CSS = """
:root{
  --carton:#F2EFE7; --carton-edge:#E4DFD1; --ink:#16305C; --ink-soft:#4A5F86;
  --stamp:#C0392B; --rule:#CFC8B6; --bar:#16305C; --bar-track:#DFD9C8;
}
*{box-sizing:border-box}
html{color-scheme:light}
body{
  margin:0; padding:0; background:var(--carton); color:var(--ink);
  font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;
  font-size:16px; line-height:1.55;
  -webkit-font-smoothing:antialiased;
}
.sheet{max-width:52rem; margin:0 auto; padding:2rem 1.25rem 5rem}
.mono,.num,.bar-value,.tile-value{
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"Courier New",monospace;
  font-variant-numeric:tabular-nums;
}
header{border-bottom:3px solid var(--ink); padding-bottom:1.25rem; margin-bottom:2rem}
.eyebrow{
  font-size:.7rem; letter-spacing:.22em; text-transform:uppercase;
  color:var(--ink-soft); margin:0 0 .75rem;
}
h1{font-size:1.9rem; line-height:1.2; margin:0 0 1rem; letter-spacing:-.01em}
h2{
  font-size:1.15rem; letter-spacing:.04em; text-transform:uppercase;
  margin:3rem 0 .75rem; padding-top:1rem; border-top:1px solid var(--rule);
}
h3{font-size:1rem; margin:1.5rem 0 .4rem}
p{margin:0 0 .9rem}
ul{margin:0 0 .9rem; padding-left:1.2rem}
li{margin-bottom:.3rem}
.lede{font-size:1.05rem}
.footnote{font-size:.82rem; color:var(--ink-soft); margin-top:.9rem}
.note{font-size:.75rem; color:var(--ink-soft); font-style:italic}

/* Mindst holdbar til — the signature element */
.stamp{
  display:inline-block; border:2px solid var(--stamp); color:var(--stamp);
  padding:.5rem .8rem; transform:rotate(-2deg); margin:1rem 0;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
}
.stamp-label{font-size:.62rem; letter-spacing:.18em; text-transform:uppercase; display:block}
.stamp-date{font-size:1.25rem; font-weight:700; letter-spacing:.06em; display:block}

.tiles{display:grid; grid-template-columns:repeat(auto-fit,minmax(9.5rem,1fr)); gap:.75rem; margin:1rem 0 1.5rem}
.tile{border:1px solid var(--rule); background:rgba(255,255,255,.45); padding:.75rem}
.tile-label{font-size:.68rem; letter-spacing:.12em; text-transform:uppercase; color:var(--ink-soft)}
.tile-value{font-size:1.7rem; line-height:1.1; margin:.2rem 0}
.tile-sub{font-size:.74rem; color:var(--ink-soft)}

.chart{margin:1.25rem 0}
.entity{margin-bottom:1.1rem; page-break-inside:avoid}
.entity-name{font-weight:700; font-size:.95rem; margin-bottom:.3rem}
.bar-row{display:grid; grid-template-columns:8.5rem 1fr 3.2rem; align-items:center; gap:.5rem; margin-bottom:2px}
.bar-label{font-size:.72rem; color:var(--ink-soft); white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
.bar-label em{font-style:normal; opacity:.75}
.bar-track{background:var(--bar-track); height:11px; display:block; position:relative}
.bar-fill{background:var(--bar); height:11px; display:block; min-width:1px}
.bar-value{font-size:.76rem; text-align:right}

.scroll{overflow-x:auto; -webkit-overflow-scrolling:touch; margin:1rem 0}
table{border-collapse:collapse; width:100%; font-size:.82rem; min-width:34rem}
th,td{text-align:left; padding:.4rem .55rem; border-bottom:1px solid var(--rule); vertical-align:top}
th{font-size:.68rem; letter-spacing:.09em; text-transform:uppercase; color:var(--ink-soft); font-weight:600}
td.num,th.num{text-align:right; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-variant-numeric:tabular-nums}
td em{font-style:normal; color:var(--ink-soft)}

.alarm-heading{color:var(--stamp); border-top-color:var(--stamp)}
blockquote{
  margin:.75rem 0; padding:.7rem .9rem; border-left:3px solid var(--stamp);
  background:rgba(255,255,255,.5); font-size:.9rem;
}
blockquote cite{display:block; margin-top:.5rem; font-style:normal; font-size:.74rem; color:var(--ink-soft)}

footer{margin-top:3.5rem; padding-top:1rem; border-top:1px solid var(--rule); font-size:.78rem; color:var(--ink-soft)}

/* --- Section 12: question register --- */
.explorer{display:grid; grid-template-columns:16rem 1fr; gap:1.25rem; margin:1.25rem 0; align-items:start}
.q-register{border:1px solid var(--rule); background:rgba(255,255,255,.4); max-height:34rem; overflow-y:auto}
.q-group-head{
  display:flex; justify-content:space-between; align-items:baseline; gap:.5rem;
  margin:0; padding:.5rem .7rem; font-size:.66rem; letter-spacing:.14em;
  text-transform:uppercase; color:var(--ink-soft);
  border-bottom:1px solid var(--rule); background:rgba(255,255,255,.5); position:sticky; top:0;
}
.q-count{font-size:.62rem; opacity:.8}
.q-list{list-style:none; margin:0; padding:0}
.q-item{
  display:flex; gap:.5rem; width:100%; text-align:left; background:none; cursor:pointer;
  border:0; border-bottom:1px solid var(--rule); padding:.5rem .7rem;
  font:inherit; font-size:.8rem; line-height:1.35; color:var(--ink);
}
.q-item:hover{background:rgba(255,255,255,.75)}
.q-item.active{background:var(--ink); color:var(--carton)}
.q-item.active .q-id{color:var(--carton); opacity:.7}
.q-id{
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.68rem;
  color:var(--ink-soft); flex:0 0 auto; padding-top:.1rem;
}
.q-detail{border:1px solid var(--rule); background:rgba(255,255,255,.4); padding:1rem}
.q-detail-head{display:flex; gap:.6rem; align-items:center; font-size:.66rem;
  letter-spacing:.14em; text-transform:uppercase; color:var(--ink-soft); margin-bottom:.4rem}
.q-question{font-size:1.15rem; font-weight:700; line-height:1.3; margin:0 0 .35rem}
.q-meta{font-size:.7rem; letter-spacing:.06em; text-transform:uppercase;
  color:var(--ink-soft); margin:0 0 1rem}
.q-cells{display:grid; grid-template-columns:repeat(auto-fit,minmax(11rem,1fr)); gap:.6rem}
.q-cell{border:1px solid var(--rule); padding:.6rem; background:rgba(255,255,255,.55)}
.q-cell-head{font-size:.72rem; font-weight:700; margin-bottom:.5rem}
.q-cell-head em{font-style:normal; font-weight:400; color:var(--ink-soft); display:block; font-size:.68rem}
.q-ents{list-style:none; margin:0 0 .5rem; padding:0}
.q-ents li{display:flex; align-items:center; gap:.35rem; margin-bottom:.25rem; font-size:.76rem}
.q-ent-name{flex:1 1 auto; overflow:hidden; text-overflow:ellipsis; white-space:nowrap}
.q-ent-type{font-size:.56rem; letter-spacing:.1em; text-transform:uppercase; color:var(--ink-soft)}
.dots{display:inline-flex; gap:2px; flex:0 0 auto}
.dot{width:7px; height:11px; background:var(--bar-track); display:block}
.dot.on{background:var(--bar)}
.q-none{font-size:.76rem; color:var(--ink-soft); font-style:italic; margin:0 0 .5rem}
.q-flag{font-size:.72rem; color:var(--stamp); border-left:2px solid var(--stamp);
  padding-left:.4rem; margin:.4rem 0}
.q-runs{display:flex; flex-wrap:wrap; gap:.25rem; margin-top:.5rem}
.q-run{
  font:inherit; font-size:.66rem; letter-spacing:.06em; text-transform:uppercase;
  background:none; border:1px solid var(--ink-soft); color:var(--ink);
  padding:.2rem .4rem; cursor:pointer;
}
.q-run:hover{background:var(--ink); color:var(--carton); border-color:var(--ink)}
.tr{border:1px solid var(--ink); margin-top:1rem; background:rgba(255,255,255,.7)}
.tr-head{
  display:flex; justify-content:space-between; align-items:center; gap:.5rem;
  background:var(--ink); color:var(--carton); padding:.4rem .6rem;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:.64rem; letter-spacing:.1em; text-transform:uppercase;
}
.tr-close{font:inherit; background:none; border:1px solid var(--carton);
  color:var(--carton); padding:.1rem .4rem; cursor:pointer}
.tr-body{display:grid; grid-template-columns:5.5rem 1fr; gap:.8rem; padding:.8rem}
.tr-attr{font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:.6rem;
  letter-spacing:.08em; text-transform:uppercase; color:var(--stamp); line-height:1.5}
.tr-text{white-space:pre-wrap; font-size:.84rem; line-height:1.5; overflow-x:auto}
.jump{display:inline-block; margin:.5rem 0; font-size:.8rem}

@media (max-width:720px){
  .explorer{grid-template-columns:1fr}
  .q-register{max-height:16rem}
  .tr-body{grid-template-columns:1fr; gap:.4rem}
}
@media print{
  .q-detail,.noprint,.q-runs{display:none}
  .q-register{max-height:none; overflow:visible; border:0; background:none}
  .explorer{display:block}
  .q-item{border-bottom:1px solid #ddd}
}

@media (max-width:420px){
  .sheet{padding:1.25rem .85rem 3rem}
  h1{font-size:1.45rem}
  .bar-row{grid-template-columns:6.6rem 1fr 2.9rem}
  .bar-label{font-size:.66rem}
}
@media print{
  body{background:#fff}
  .sheet{max-width:none; padding:0}
  h2{page-break-after:avoid}
  .scroll{overflow:visible}
  table{min-width:0; font-size:.7rem}
}
"""


def build(result: dict, answers: list[dict]) -> str:
    meta = result["meta"]
    measured = (meta["last_answer"] or datetime.now(timezone.utc).isoformat())[:10]
    expires = (
        datetime.fromisoformat(measured) + timedelta(days=config.SHELF_LIFE_DAYS)
    ).strftime("%d.%m.%Y")

    spaced = len(meta["passes"]) > 1
    consistency_note = (
        "Kørslerne blev foretaget med timers mellemrum, så konsistenstallet også "
        "afspejler variation over tid — ikke kun modellens tilfældighed i det enkelte kald."
        if spaced else
        "Kørslerne blev foretaget i træk, så konsistenstallet afspejler modellens "
        "tilfældighed i det enkelte kald, ikke variation over tid."
    )

    cells = [cell for cell in CELL_ORDER if cell in meta["cells"]]

    body = f"""
<header>
  <p class="eyebrow">Måling · dansk mejeri · {esc(measured)}</p>
  <h1>{esc(config.REPORT_TITLE)}</h1>
  <p class="lede">FMCG-virksomheder måler synlighed på hylden, på Google og i medierne.
  Ingen måler, hvad en sprogmodel svarer, når en forbruger spørger, hvilken yoghurt der
  smager bedst, eller hvor mælk er billigst. Det her er en dateret, reproducerbar måling
  af netop det: {esc(meta['answers'])} svar fra to sprogmodeller, hver kørt både med og
  uden websøgning, på {esc(meta['questions'])} spørgsmål der ikke nævner ét eneste
  mærke- eller butiksnavn.</p>
  <div class="stamp">
    <span class="stamp-label">Mindst holdbar til</span>
    <span class="stamp-date">{esc(expires)}</span>
  </div>
  <p class="footnote">Ikke fordi tallene bliver forkerte den dag, men fordi de holder op
  med at betyde noget. Modeller opdateres uden varsel. {esc(consistency_note)}</p>
</header>

<h2>Den blinde vinkel</h2>
<p>En dansk forbruger, der overvejer hvilken yoghurt hun skal købe, har fået en ny
rådgiver. Den har ingen hylde, ingen annoncepris og ingen mediekontakt. Den nævner nogle
mærker og ikke andre, og den gør det med samme rolige sikkerhed uanset om den har ret.</p>
<p>For en producent er det en kanal uden baseline, uden KPI og uden intern ejer. Ikke
fordi nogen har fejlet, men fordi kanalen opstod hurtigere, end nogen nåede at bygge
måling til den. Denne rapport bygger målingen — én gang, på ét marked — så det kan
diskuteres konkret frem for principielt.</p>

{key_figures(result)}

{defunct_section(result)}

{chart(result, "butik", "Butikker", "Hvilke dagligvarekæder bringer modellerne selv på banen, når spørgsmålet ikke nævner nogen?")}

{chart(result, "maerke", "Mærker", "Samme spørgsmål, samme svar — her talt op på mærkeniveau.")}

{full_table(result)}

{disagreement_section(result)}

{intent_section(result)}

{limitations()}

{method_section(result)}

{question_explorer(result, answers)}

<footer>
  <p>Målt {esc(measured)}. Rapporten er et selvstændigt HTML-dokument uden eksterne
  afhængigheder. Rå svar og API-nøgler er ikke en del af repoet.</p>
  <p>Rapporten rangordner ikke navngivne virksomheder og indeholder ingen anbefalinger
  til dem. Den viser en blind vinkel.</p>
</footer>
"""

    return f"""<!doctype html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow, noarchive">
<title>{esc(config.REPORT_TITLE)}</title>
<style>{CSS}</style>
</head>
<body>
<main class="sheet">{body}</main>
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
