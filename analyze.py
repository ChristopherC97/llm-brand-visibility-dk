"""Turns raw answers into metrics. Deterministic — no API calls.

Usage:
    python3 analyze.py

Reads  data/raw.jsonl
Writes data/metrics.json, data/metrics.csv, data/unknown_names.txt

Counting rule: first occurrence per entity per answer. Otherwise a long,
chatty answer would outweigh a short one and we would be measuring wordiness.

Everything is computed per cell — (model, condition) — and never pooled. A
model with search and the same model without it are not the same population,
so a combined figure would divide by a denominator half of which could not
have produced the observation.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict

import config
import entities
import prompts
from entities import EntityType


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval. Stdlib only, and well-behaved at small n."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def band(rate: float) -> str:
    for name, low, high in config.VISIBILITY_BANDS:
        if low <= rate < high:
            return name
    return config.VISIBILITY_BANDS[-1][0]


def crosses_boundary(low: float, high: float) -> bool:
    """True if the interval spans a band edge — the entity's band is not settled."""
    edges = sorted({edge for _, edge, _ in config.VISIBILITY_BANDS if 0 < edge < 1})
    return any(low < edge < high for edge in edges)


def load_rows() -> list[dict]:
    if not config.RAW_PATH.exists():
        raise SystemExit(
            f"Ingen data i {config.RAW_PATH}.\n"
            "Kør først:  python3 run.py --pass 1"
        )
    with config.RAW_PATH.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def annotate(rows: list[dict]) -> None:
    """Attach extraction results to each row, in place."""
    for row in rows:
        mentions = entities.find_mentions(row["text"])
        row["_mentions"] = mentions
        # First occurrence per entity, in order of appearance.
        seen: dict[str, int] = {}
        for mention in mentions:
            seen.setdefault(mention.entity_key, mention.start)
        row["_first"] = seen
        row["_types"] = {m.entity_key: m.type for m in mentions}
        row["_defunct"] = entities.check_defunct(row["text"], mentions)
        row["_length"] = max(1, len(row["text"]))


def cell_key(row: dict) -> str:
    return f"{row['model_key']}/{row['condition']}"


def corpus_unknown_names(rows: list[dict]) -> list[tuple[str, int]]:
    """Candidate names for the dictionary, with the sentence-opener noise removed.

    The per-answer detector cannot tell "Coop" (a name) from "Tjek" (a verb at
    the start of a sentence). At corpus level it can: a word that also appears
    in lowercase somewhere in the corpus is an ordinary Danish word, not a name.
    """
    joined = "\n".join(row["text"] for row in rows)
    lowercase_words = set(re.findall(rf"(?<![{entities.LETTER[1:-1]}])([a-zæøå]{{3,}})", joined))

    counts: Counter[str] = Counter()
    mid_sentence: Counter[str] = Counter()
    for row in rows:
        for candidate, _, sentence_initial in entities.unknown_capitalised_spans(row["text"]):
            parts = candidate.split()
            if all(part.lower() in lowercase_words for part in parts):
                continue
            counts[candidate] += 1
            if not sentence_initial:
                mid_sentence[candidate] += 1

    # A candidate that never appears mid-sentence is capitalised by grammar,
    # not because it is a name. This is what removes "Kig", "Tjek", "Skær".
    return [(name, count) for name, count in counts.most_common() if mid_sentence[name]]


def analyse(rows: list[dict]) -> dict:
    annotate(rows)

    cells = sorted({cell_key(row) for row in rows})
    rows_by_cell: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        rows_by_cell[cell_key(row)].append(row)

    display = {entity.key: entity.display for entity in entities.ENTITIES}
    etype = {entity.key: entity.type for entity in entities.ENTITIES}
    notes = {entity.key: entity.note for entity in entities.ENTITIES}

    per_entity: dict[str, dict] = {}
    for key in display:
        per_entity[key] = {
            "key": key,
            "display": display[key],
            "type": etype[key].value,
            "note": notes[key],
            "defunct": key in entities.DEFUNCT,
            "cells": {},
        }

    for cell in cells:
        cell_rows = rows_by_cell[cell]
        n_answers = len(cell_rows)
        n_questions = len({row["prompt_id"] for row in cell_rows})

        # Total first-occurrence mentions per entity type, for share of voice.
        type_totals: Counter[str] = Counter()
        for row in cell_rows:
            for key in row["_first"]:
                type_totals[etype[key].value] += 1

        # Per question: in how many passes did the entity appear? -> consistency.
        appearances: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        passes_per_question: dict[str, int] = Counter()
        for row in cell_rows:
            passes_per_question[row["prompt_id"]] += 1
            for key in row["_first"]:
                appearances[key][row["prompt_id"]] += 1

        for key in display:
            hits = [row for row in cell_rows if key in row["_first"]]
            n_hits = len(hits)

            # First-mentioned: before any other entity of the same type.
            first_count = 0
            for row in hits:
                same_type = [
                    start for other, start in row["_first"].items()
                    if etype[other] == etype[key]
                ]
                if same_type and row["_first"][key] == min(same_type):
                    first_count += 1

            positions = [row["_first"][key] / row["_length"] for row in hits]

            # Consistency: over questions where the entity appeared at least
            # once, the mean share of that question's passes it appeared in.
            shares = [
                count / passes_per_question[prompt_id]
                for prompt_id, count in appearances[key].items()
            ]

            rate = n_hits / n_answers if n_answers else 0.0
            # Wilson on the number of QUESTIONS, not answers: the three passes
            # of one question are clustered, so n=105 would understate the
            # uncertainty. Conservative on purpose.
            successes = round(rate * n_questions)
            low, high = wilson(successes, n_questions)

            per_entity[key]["cells"][cell] = {
                "answers": n_answers,
                "questions": n_questions,
                "mentions": n_hits,
                "mention_rate": round(rate, 4),
                "ci_low": round(low, 4),
                "ci_high": round(high, 4),
                "band": band(rate),
                "boundary_uncertain": crosses_boundary(low, high),
                "share_of_voice": round(
                    n_hits / type_totals[etype[key].value], 4
                ) if type_totals[etype[key].value] else 0.0,
                "first_mentioned_rate": round(first_count / n_hits, 4) if n_hits else 0.0,
                "avg_position": round(sum(positions) / len(positions), 4) if positions else None,
                "consistency": round(sum(shares) / len(shares), 4) if shares else 0.0,
            }

    return {
        "meta": build_meta(rows, cells, rows_by_cell),
        "toplines": build_toplines(rows_by_cell, etype),
        "entities": per_entity,
        "defunct": build_defunct(rows_by_cell),
        "disagreement": build_disagreement(rows_by_cell, per_entity, cells),
        "by_intent": build_intent(rows, etype),
        "questions": build_questions(rows, display, etype),
        "unknown_names": [
            {"name": name, "count": count} for name, count in corpus_unknown_names(rows)[:60]
        ],
    }


def build_meta(rows, cells, rows_by_cell) -> dict:
    timestamps = sorted(row["ts"] for row in rows)
    passes = sorted({row["pass"] for row in rows})
    truncated = [row for row in rows if row["stop_reason"] in {"max_tokens", "incomplete"}]

    # Were the repeats spaced, or run back-to-back? The report says which,
    # because it changes what "consistency" means.
    spans = []
    for pass_no in passes:
        pass_ts = sorted(row["ts"] for row in rows if row["pass"] == pass_no)
        if pass_ts:
            spans.append((pass_no, pass_ts[0], pass_ts[-1]))

    return {
        "generated_from": str(config.RAW_PATH.name),
        "answers": len(rows),
        "questions": len(prompts.PROMPTS),
        "cells": cells,
        "cell_sizes": {cell: len(items) for cell, items in rows_by_cell.items()},
        "passes": passes,
        "pass_spans": [{"pass": p, "first": a, "last": b} for p, a, b in spans],
        "first_answer": timestamps[0] if timestamps else None,
        "last_answer": timestamps[-1] if timestamps else None,
        "truncated_answers": len(truncated),
        "models": {m["key"]: m["model"] for m in config.MODELS},
        "bands": [
            {"name": name, "low": low, "high": min(high, 1.0)}
            for name, low, high in config.VISIBILITY_BANDS
        ],
        "ci_note": (
            "Konfidensintervaller er Wilson-intervaller beregnet på antal spørgsmål, "
            "ikke antal svar. De tre kørsler af samme spørgsmål er ikke uafhængige."
        ),
    }


def build_toplines(rows_by_cell, etype) -> dict:
    out = {}
    for cell, cell_rows in rows_by_cell.items():
        n = len(cell_rows)
        with_store = sum(
            1 for row in cell_rows
            if any(etype[k] == EntityType.STORE for k in row["_first"])
        )
        with_brand = sum(
            1 for row in cell_rows
            if any(etype[k] == EntityType.BRAND for k in row["_first"])
        )
        out[cell] = {
            "answers": n,
            "share_with_store": round(with_store / n, 4) if n else 0.0,
            "share_with_brand": round(with_brand / n, 4) if n else 0.0,
            "avg_stores_per_answer": round(
                sum(
                    sum(1 for k in row["_first"] if etype[k] == EntityType.STORE)
                    for row in cell_rows
                ) / n, 2) if n else 0.0,
            "avg_brands_per_answer": round(
                sum(
                    sum(1 for k in row["_first"] if etype[k] == EntityType.BRAND)
                    for row in cell_rows
                ) / n, 2) if n else 0.0,
        }
    return out


def build_defunct(rows_by_cell) -> dict:
    per_cell = {}
    quotes = []
    for cell, cell_rows in rows_by_cell.items():
        n = len(cell_rows)
        error_answers = 0
        correct_answers = 0
        by_chain: Counter[str] = Counter()
        for row in cell_rows:
            errors = [hit for hit in row["_defunct"] if hit.is_error]
            corrects = [hit for hit in row["_defunct"] if not hit.is_error]
            if errors:
                error_answers += 1
                for hit in errors:
                    by_chain[hit.display] += 1
                    quotes.append({
                        "cell": cell,
                        "prompt_id": row["prompt_id"],
                        "question": row["question"],
                        "pass": row["pass"],
                        "chain": hit.display,
                        "quote": hit.quote,
                    })
            if corrects:
                correct_answers += 1
        per_cell[cell] = {
            "answers": n,
            "answers_with_error": error_answers,
            "error_rate": round(error_answers / n, 4) if n else 0.0,
            "answers_stating_closure_correctly": correct_answers,
            "by_chain": dict(by_chain),
        }
    return {
        "per_cell": per_cell,
        "chains": {
            key: {"display": d.display, "ended": d.ended, "detail": d.detail}
            for key, d in entities.DEFUNCT.items()
        },
        "quotes": quotes,
    }


def build_disagreement(rows_by_cell, per_entity, cells) -> dict:
    """Jaccard overlap between models, computed WITHIN each condition.

    Comparing a searching model against a non-searching one would measure the
    search setting, not the models.
    """
    def top_set(cell: str, n: int = 10) -> set[str]:
        scored = [
            (key, data["cells"].get(cell, {}).get("mention_rate", 0.0))
            for key, data in per_entity.items()
        ]
        scored = [(k, r) for k, r in scored if r > 0]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return {key for key, _ in scored[:n]}

    out = {}
    for condition in config.CONDITIONS:
        cond = condition["key"]
        model_cells = [f"{m['key']}/{cond}" for m in config.MODELS if f"{m['key']}/{cond}" in cells]
        if len(model_cells) < 2:
            continue
        a, b = model_cells[0], model_cells[1]
        set_a, set_b = top_set(a), top_set(b)
        union = set_a | set_b
        out[cond] = {
            "cells": [a, b],
            "jaccard": round(len(set_a & set_b) / len(union), 4) if union else 0.0,
            "shared": sorted(per_entity[k]["display"] for k in set_a & set_b),
            "only_in_" + a.split("/")[0]: sorted(per_entity[k]["display"] for k in set_a - set_b),
            "only_in_" + b.split("/")[0]: sorted(per_entity[k]["display"] for k in set_b - set_a),
        }
    return out


def build_questions(rows, display, etype) -> list[dict]:
    """Per-question breakdown, for drilling into a single question.

    Deliberately carries counts ("appeared in 2 of 3 runs"), never percentages.
    One question is three answers per cell; a percentage on three observations
    is a decimal point pretending to be a measurement.

    No answer text lives here — raw answers go to a separate, gitignored file
    so publishing them stays an explicit decision rather than a side effect.
    """
    by_question: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_question[row["prompt_id"]].append(row)

    out = []
    for prompt in prompts.PROMPTS:
        question_rows = by_question.get(prompt.id, [])
        if not question_rows:
            continue
        cells: dict[str, dict] = {}
        for cell in sorted({cell_key(row) for row in question_rows}):
            cell_rows = [row for row in question_rows if cell_key(row) == cell]
            hits: Counter[str] = Counter()
            order: dict[str, int] = {}
            for row in cell_rows:
                for key, start in row["_first"].items():
                    hits[key] += 1
                    order.setdefault(key, start)
            entities_here = [
                {
                    "key": key,
                    "display": display[key],
                    "type": etype[key].value,
                    "runs_present": count,
                    "runs_total": len(cell_rows),
                }
                for key, count in sorted(hits.items(), key=lambda kv: (-kv[1], order[kv[0]]))
            ]
            cells[cell] = {
                "runs": len(cell_rows),
                "entities": entities_here,
                "defunct_errors": sum(
                    1 for row in cell_rows if any(h.is_error for h in row["_defunct"])
                ),
                "median_length": sorted(row["_length"] for row in cell_rows)[len(cell_rows) // 2],
            }
        out.append({
            "id": prompt.id,
            "intent": prompt.intent,
            "text": prompt.text,
            "cells": cells,
        })
    return out


def write_answers(rows) -> None:
    """Full answer texts, in their own file. Gitignored by default.

    Publishing 420 model-written texts about named companies is a decision,
    not a by-product of running the analysis. Keeping them out of metrics.json
    means the report cannot inline them by accident.
    """
    payload = [
        {
            "prompt_id": row["prompt_id"],
            "question": row["question"],
            "intent": row["intent"],
            "model_key": row["model_key"],
            "condition": row["condition"],
            "pass": row["pass"],
            "text": row["text"],
            "entities": sorted(row["_first"]),
        }
        for row in rows
    ]
    (config.DATA_DIR / "answers.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def build_intent(rows, etype) -> dict:
    """Qualitative only. Counts are directional; no per-intent rates are published."""
    out: dict[str, dict] = {}
    for intent in prompts.INTENTS:
        subset = [row for row in rows if row["intent"] == intent]
        if not subset:
            continue
        stores: Counter[str] = Counter()
        brands: Counter[str] = Counter()
        for row in subset:
            for key in row["_first"]:
                (stores if etype[key] == EntityType.STORE else brands)[key] += 1
        out[intent] = {
            "answers": len(subset),
            "questions": len({row["prompt_id"] for row in subset}),
            "store_mentions": sum(stores.values()),
            "brand_mentions": sum(brands.values()),
            "top_stores": [k for k, _ in stores.most_common(3)],
            "top_brands": [k for k, _ in brands.most_common(3)],
        }
    return out


def write_csv(result: dict) -> None:
    with config.CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "entitet", "type", "celle", "svar", "omtaler", "omtale_rate",
            "ci_lav", "ci_hoej", "baand", "graense_usikker", "share_of_voice",
            "foerst_naevnt_rate", "gns_position", "konsistens",
        ])
        for data in result["entities"].values():
            for cell, stats in sorted(data["cells"].items()):
                if stats["mentions"] == 0:
                    continue
                writer.writerow([
                    data["display"], data["type"], cell, stats["answers"],
                    stats["mentions"], stats["mention_rate"], stats["ci_low"],
                    stats["ci_high"], stats["band"],
                    "ja" if stats["boundary_uncertain"] else "nej",
                    stats["share_of_voice"], stats["first_mentioned_rate"],
                    stats["avg_position"], stats["consistency"],
                ])


def write_unknown(result: dict) -> None:
    lines = [
        "Kapitaliserede navne der optrådte i svarene, men ikke står i entities.py.",
        "Sætningsindledere er filtreret fra: et ord der også optræder med små",
        "bogstaver i korpuset er et almindeligt dansk ord, ikke et navn.",
        "",
        "Gennemgå listen og udvid ordbogen. Kør derefter analyze.py igen.",
        "",
    ]
    for item in result["unknown_names"]:
        lines.append(f"{item['count']:4}  {item['name']}")
    config.UNKNOWN_NAMES_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    rows = load_rows()
    result = analyse(rows)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.METRICS_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_csv(result)
    write_unknown(result)
    write_answers(rows)

    meta = result["meta"]
    print(f"Analyserede {meta['answers']} svar fordelt på {len(meta['cells'])} celler.")
    for cell, size in sorted(meta["cell_sizes"].items()):
        print(f"  {cell:20} {size} svar")
    if meta["truncated_answers"]:
        print(f"  ADVARSEL: {meta['truncated_answers']} svar var afkortede.")

    print("\nToplinjer:")
    for cell, topline in sorted(result["toplines"].items()):
        print(
            f"  {cell:20} mærke i {topline['share_with_brand']:.0%} af svar, "
            f"butik i {topline['share_with_store']:.0%}"
        )

    print("\nUdgåede kæder:")
    for cell, stats in sorted(result["defunct"]["per_cell"].items()):
        print(
            f"  {cell:20} fejl i {stats['answers_with_error']}/{stats['answers']} svar "
            f"({stats['error_rate']:.0%}), korrekt beskrevet i {stats['answers_stating_closure_correctly']}"
        )

    print(f"\nSkrev {config.METRICS_PATH.name}, {config.CSV_PATH.name}, {config.UNKNOWN_NAMES_PATH.name}")
    if result["unknown_names"]:
        print(f"  {len(result['unknown_names'])} ukendte navne til gennemgang — se {config.UNKNOWN_NAMES_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
