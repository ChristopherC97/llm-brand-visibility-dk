"""Proposes dictionary entries from the unknown-name dump. Manual step.

Usage:
    python3 analyze.py          # writes data/unknown_names.txt
    python3 candidates.py       # writes candidates.md
    # then YOU read candidates.md and edit entities.py by hand

This is deliberately outside the measurement pipeline. A language model may
*suggest* which unknown names look like dairy brands or grocery chains; it
never touches a number. The dictionary that does the counting is a
version-controlled file, so anyone who clones the repository gets the same
figures regardless of what any model suggested here.

Nothing in this file is imported by run.py, analyze.py or report.py.
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

import config
import entities

load_dotenv()

OUTPUT = config.ROOT / "candidates.md"

INSTRUCTION = """Herunder er navne, der optrådte i danske svar om mejeriprodukter,
men som ikke står i vores ordbog over mejerimærker og dagligvarekæder.

Klassificér hvert navn som præcis én af:
  MAERKE  - et mejerimærke eller produktmærke (inkl. supermarkeders egne mærker)
  BUTIK   - en dagligvarekæde eller butik hvor man kan købe mejeri
  NEJ     - alt andet: stednavne, produktkategorier, myndigheder, almindelige ord

Vær særligt streng ved produktkategorier. "Skyr", "Danbo" og "Havarti" er
ostetyper og kategorier, ikke mærker, og skal klassificeres som NEJ.

Svar som en markdown-tabel med kolonnerne: Navn | Klassifikation | Begrundelse.
Én linje per navn. Ingen indledning, ingen opsummering.
"""


def read_candidates() -> list[str]:
    if not config.UNKNOWN_NAMES_PATH.exists():
        raise SystemExit(
            f"Mangler {config.UNKNOWN_NAMES_PATH}.\nKør først:  python3 analyze.py"
        )
    names = []
    for line in config.UNKNOWN_NAMES_PATH.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            names.append(f"{parts[1]}  (optrådte {parts[0]} gange)")
    return names


def main() -> int:
    names = read_candidates()
    if not names:
        print("Ingen ukendte navne at gennemgå.")
        return 0

    known = ", ".join(sorted({e.display for e in entities.ENTITIES}))
    prompt = (
        f"{INSTRUCTION}\nOrdbogen indeholder allerede:\n{known}\n\n"
        f"Navne til klassificering:\n" + "\n".join(f"- {name}" for name in names)
    )

    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=config.MODELS[0]["model"],
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    suggestion = "\n".join(b.text for b in response.content if b.type == "text")

    OUTPUT.write_text(
        "# Forslag til ordbogen\n\n"
        "Genereret af en sprogmodel. **Forslag, ikke facit.**\n\n"
        "Gennemgå tabellen, og redigér `entities.py` i hånden. Ingen af de her\n"
        "forslag påvirker et eneste tal, før du selv har committet dem.\n\n"
        "Husk: produktkategorier hører ikke i ordbogen. `skyr` ville have ligget\n"
        "nummer ét i rapporten uden at betyde noget.\n\n"
        f"{suggestion}\n",
        encoding="utf-8",
    )
    print(f"Skrev {OUTPUT.name} med forslag til {len(names)} navne.")
    print("Læs den igennem, og redigér entities.py i hånden. Kør derefter:")
    print("  python3 selftest.py && python3 analyze.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
