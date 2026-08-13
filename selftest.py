"""Selftest. Runs without a single API call.

Two jobs:

  1. Prove that the Danish false-positive guards behave, including the case
     that must MATCH ("Netto har gode priser paa 400 gram ost").
  2. Fail loudly if any question in prompts.py contains a brand or store name.
     A question containing "Arla" measures recognition, not visibility, so
     this is enforced here rather than left to discipline.

Run:  python3 selftest.py
"""

from __future__ import annotations

import re
import sys

import entities
import prompts
from entities import EntityType

FAILURES: list[str] = []
CHECKS = 0


def check(condition: bool, description: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(description)


def keys_in(text: str) -> set[str]:
    return {mention.entity_key for mention in entities.find_mentions(text)}


def expect_match(text: str, key: str) -> None:
    check(key in keys_in(text), f"{key!r} SKULLE matche i: {text!r}")


def expect_no_match(text: str, key: str) -> None:
    check(key not in keys_in(text), f"{key!r} måtte IKKE matche i: {text!r}")


# --- 1. The false-positive cases from the brief ------------------------------


def test_danish_guards() -> None:
    # SPAR the chain vs. "spar" the verb.
    expect_no_match("Du kan spar penge ved at handle ind om aftenen.", "spar")
    expect_no_match("Spar penge på dine indkøb af mejeriprodukter.", "spar")
    expect_no_match("Spar op til 30 % på ost i denne uge.", "spar")
    expect_no_match("Spar på mælken ved at købe større kartoner.", "spar")
    expect_match("Du kan finde den i SPAR i Hillerød.", "spar")
    expect_match("Spar har et mindre udvalg end de store kæder.", "spar")

    # Netto the chain vs. "netto" the adverb. The third case is the one the
    # brief singles out: the guard must see past an intervening number.
    expect_no_match("Osten vejer netto 400 gram.", "netto")
    expect_no_match("Prisen er netto 30 kr. per liter.", "netto")
    expect_no_match("Netto vægt er 400 gram.", "netto")
    expect_match("Netto har gode priser på 400 gram ost.", "netto")
    expect_match("Netto er billigst på mælk.", "netto")
    expect_match("Jeg handler som regel i Netto.", "netto")

    # Jersey the cattle breed / product line vs. jersey the fabric.
    expect_no_match("Hun havde en jersey-trøje på.", "jersey")
    expect_no_match("Jersey-trøjen var blå.", "jersey")
    expect_match("Jersey-mælk har et højere fedtindhold.", "jersey")

    # Fakta the chain vs. "fakta" the ordinary noun. Same failure class.
    expect_no_match("Her er nogle fakta om dansk mejeriproduktion.", "fakta")
    expect_no_match("Fakta om mælk: den indeholder calcium.", "fakta")
    expect_no_match("Fakta er, at priserne er steget.", "fakta")
    expect_match("Fakta blev omdannet til 365discount.", "fakta")

    # Place names and homographs.
    expect_no_match("Høng Kommune ligger på Vestsjælland.", "hoeng")
    expect_match("Høng er en klassisk dansk ost.", "hoeng")
    expect_no_match("Mammen-stilen er en vikingetidig ornamentik.", "mammen")
    expect_match("Mammen laver en god lagret ost.", "mammen")


def test_inflection_and_compounds() -> None:
    """Danish genitive and hyphenated compounds must still resolve."""
    expect_match("Arlas økologiske mælk er udbredt.", "arla")
    expect_match("Prøv Arla-mælk fra køledisken.", "arla")
    expect_match("Nettos egne mærker er billigere.", "netto")
    expect_match("Thises yoghurt er økologisk.", "thise")
    expect_match("thise laver god yoghurt.", "thise")  # lowercase allowed for Arla/Thise
    expect_match("Rema 1000's udvalg af ost er stort.", "rema1000")

    # But a name glued into a longer word must not match.
    expect_no_match("Arlaskyrprodukterne er nye.", "arla")


def test_first_occurrence_and_overlap() -> None:
    text = "Arla og Arla og Arla laver mælk. Min Købmand fører den."
    mentions = entities.find_mentions(text)
    arla = [m for m in mentions if m.entity_key == "arla"]
    check(len(arla) == 3, "find_mentions skal returnere alle forekomster (analyse tæller første)")
    check("minkoebmand" in keys_in(text), "Min Købmand skal matche som ét flerords-alias")


def test_generic_words_are_not_entities() -> None:
    """The skyr lesson: product categories must not be in the dictionary."""
    # "Danbo" was surfaced by the pilot's unknown-name dump. It is a protected
    # cheese type, not a brand — same trap as skyr, so it stays out on purpose.
    for generic in ("skyr", "ymer", "hytteost", "kærnemælk", "danablu", "danbo", "havarti"):
        check(
            generic.lower() not in {a.lower() for a in entities.all_entity_surface_forms()},
            f"{generic!r} er en produktkategori og må ikke stå i ordbogen",
        )


# --- 2. Defunct-chain classification -----------------------------------------


def test_defunct_classification() -> None:
    """A model that correctly says a chain closed must NOT be scored as wrong."""
    wrong = "Du finder billig mælk i Netto, Aldi og Lidl."
    hits = {h.entity_key: h for h in entities.check_defunct(wrong)}
    check("aldi" in hits and hits["aldi"].is_error, "Aldi anbefalet som levende = fejl")

    right = "Aldi forlod det danske marked i 2023, så den mulighed findes ikke længere."
    hits = {h.entity_key: h for h in entities.check_defunct(right)}
    check("aldi" in hits and not hits["aldi"].is_error, "Aldi korrekt beskrevet som lukket = ikke fejl")

    right2 = "Irma lukkede sine sidste butikker, og Fakta blev omdannet til 365discount."
    hits = {h.entity_key: h for h in entities.check_defunct(right2)}
    check("irma" in hits and not hits["irma"].is_error, "Irma korrekt beskrevet som lukket = ikke fejl")
    check("fakta" in hits and not hits["fakta"].is_error, "Fakta korrekt beskrevet som omdannet = ikke fejl")

    wrong2 = "Prøv Irma, hvis du vil have økologisk kvalitet."
    hits = {h.entity_key: h for h in entities.check_defunct(wrong2)}
    check("irma" in hits and hits["irma"].is_error, "Irma anbefalet som levende = fejl")

    # Every defunct key must exist in the dictionary, or the alarm never fires.
    keys = {entity.key for entity in entities.ENTITIES}
    for key in entities.DEFUNCT:
        check(key in keys, f"DEFUNCT-nøgle {key!r} findes ikke i ordbogen")


# --- 3. No brand or store names in the questions -----------------------------


def test_no_entity_names_in_prompts() -> None:
    """The load-bearing test. Case-insensitive, word-bounded, guards ignored.

    Guards are deliberately NOT applied here: the rule is 'no brand names in
    questions', so a guarded near-miss should still fail the build.
    """
    patterns = [
        (surface, re.compile(rf"(?<!{entities.LETTER}){re.escape(surface)}(?!{entities.LETTER})", re.IGNORECASE))
        for surface in entities.all_entity_surface_forms()
    ]
    for prompt in prompts.PROMPTS:
        for surface, pattern in patterns:
            if pattern.search(prompt.text):
                FAILURES.append(
                    f"SPØRGSMÅL {prompt.id} indeholder entitetsnavnet {surface!r}: {prompt.text!r}"
                )
        global CHECKS
        CHECKS += 1


def test_prompt_set_integrity() -> None:
    ids = [prompt.id for prompt in prompts.PROMPTS]
    check(len(ids) == len(set(ids)), "spørgsmåls-id skal være unikke")
    check(len(prompts.PROMPTS) >= 30, "spørgsmålssættet skal have mindst 30 spørgsmål")
    texts = [prompt.text.strip().lower() for prompt in prompts.PROMPTS]
    check(len(texts) == len(set(texts)), "spørgsmål må ikke gentages ordret")
    for prompt in prompts.PROMPTS:
        check(prompt.intent in prompts.INTENTS, f"{prompt.id}: ukendt intention {prompt.intent!r}")
        check(prompt.text.endswith("?"), f"{prompt.id}: spørgsmål skal slutte med '?'")


# --- 4. Unknown-name discovery -----------------------------------------------


def test_unknown_names() -> None:
    text = "Jeg vil anbefale Arla, Lassebo Mejeri og Ørbæk Andelsmejeri."
    unknown = entities.unknown_capitalised_names(text)
    joined = " ".join(unknown)
    check("Lassebo" in joined, "ukendte kapitaliserede navne skal opdages")
    check("Arla" not in joined, "kendte navne må ikke rapporteres som ukendte")


# --- Runner ------------------------------------------------------------------


def main() -> int:
    tests = [
        test_danish_guards,
        test_inflection_and_compounds,
        test_first_occurrence_and_overlap,
        test_generic_words_are_not_entities,
        test_defunct_classification,
        test_no_entity_names_in_prompts,
        test_prompt_set_integrity,
        test_unknown_names,
    ]
    for test in tests:
        test()

    print(f"Kørte {CHECKS} kontroller uden et eneste API-kald.")
    if FAILURES:
        print(f"\n{len(FAILURES)} FEJLEDE:\n")
        for failure in FAILURES:
            print(f"  ✗ {failure}")
        print("\nRet ordbogen eller spørgsmålene, før der bruges kredit.")
        return 1
    print("Alt bestået. Ordbogens værn og spørgsmålssættet er i orden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
