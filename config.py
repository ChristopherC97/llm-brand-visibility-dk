"""Configuration for the Danish dairy AI-visibility measurement.

All user-facing output is Danish; code and comments are English.
Model IDs verified against provider documentation on 2026-08-13.
"""

from __future__ import annotations

from pathlib import Path

# --- Paths -------------------------------------------------------------------

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
RAW_PATH = DATA_DIR / "raw.jsonl"
METRICS_PATH = DATA_DIR / "metrics.json"
CSV_PATH = DATA_DIR / "metrics.csv"
UNKNOWN_NAMES_PATH = DATA_DIR / "unknown_names.txt"
REPORT_PATH = ROOT / "docs" / "index.html"

# --- Models ------------------------------------------------------------------
# Each model is measured in two conditions: with and without web search.
# Search is a measured variable, not a hidden assumption.

MODELS = [
    {
        "key": "claude",
        "provider": "anthropic",
        "model": "claude-opus-5",
        "label": "Claude Opus 5",
    },
    {
        "key": "gpt",
        "provider": "openai",
        "model": "gpt-5.6-terra",
        "label": "GPT-5.6 Terra",
    },
]

CONDITIONS = [
    {"key": "nosearch", "search": False, "label": "uden websøgning"},
    {"key": "search", "search": True, "label": "med websøgning"},
]

# --- Run design --------------------------------------------------------------
# Three passes, run manually a few hours apart (`run.py --pass N`).
# Spacing matters: back-to-back repeats measure only decoding randomness,
# whereas spaced repeats also capture routing and index variation. The report
# records the actual timestamps and states which of the two it measured.

RUN_PASSES = 3
RECOMMENDED_PASS_GAP_HOURS = 2

MAX_CONCURRENCY = 4
MAX_RETRIES = 5
REQUEST_TIMEOUT_S = 180
# claude-opus-5 thinks by default, and max_tokens caps thinking + visible text
# together. A tight budget would truncate answers mid-sentence, which silently
# undercounts mentions. Generous budget, and every answer records its stop
# reason so analyze.py can flag any that were cut off anyway.
MAX_OUTPUT_TOKENS = 4000

# No system prompt. Provider defaults otherwise. Note in the report that
# provider defaults are not identical across providers (claude-opus-5 thinks
# by default), so cross-model differences are partly differences in defaults.
SYSTEM_PROMPT = None

# --- Reporting thresholds ----------------------------------------------------
# Pre-registered in report_plan.md before the full run. Do not tune after
# seeing the data — the whole point of committing them is that they are fixed.

VISIBILITY_BANDS = [
    ("synlig", 0.40, 1.01),
    ("marginal", 0.10, 0.40),
    ("usynlig", 0.00, 0.10),
]

# Entities whose 95% Wilson interval crosses a band boundary get a dagger.
BOUNDARY_MARKER = "†"

# Number of top entities per type shown in the bar charts.
TOP_N_CHART = 12

# --- Report metadata ---------------------------------------------------------

REPORT_TITLE = "Hvad anbefaler sprogmodellerne, når danskere spørger om mejeri?"
SHELF_LIFE_DAYS = 90  # "Mindst holdbar til" = measurement date + this


def cells() -> list[tuple[dict, dict]]:
    """Every (model, condition) pair. Four cells in the current design."""
    return [(m, c) for m in MODELS for c in CONDITIONS]
