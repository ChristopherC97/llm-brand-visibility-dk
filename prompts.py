"""The question set.

Hard requirement: no brand or store name may appear in any question. A question
containing "Arla" measures recognition, not visibility. This is enforced by
selftest.py against the full alias list in entities.py, not by discipline.

How the set was written (this belongs in the report's method section, and the
file is in the repository so a reader can disagree with it concretely):
questions were written to mirror how a Danish consumer phrases a purchase
question out loud — short, unqualified, and without naming a product line.
Intent tags exist so the report can describe qualitatively which kinds of
question elicit store names versus brand names. No per-intent percentages are
reported: with 35 questions, a per-intent rate would be an anecdote with
decimals on it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    id: str
    intent: str
    text: str


INTENTS = ("pris", "smag", "anvendelse", "vaerdier", "sammenligning")


PROMPTS: tuple[Prompt, ...] = (
    # --- pris ---------------------------------------------------------------
    Prompt("q01", "pris", "Hvor kan jeg købe billig mælk i Danmark?"),
    Prompt("q02", "pris", "Hvad koster en liter økologisk mælk typisk i Danmark?"),
    Prompt("q03", "pris", "Hvor i Danmark får jeg mest ost for pengene?"),
    Prompt("q04", "pris", "Hvordan sparer jeg penge på mejeriprodukter i en dansk husholdning?"),
    Prompt("q05", "pris", "Er det billigere at købe smør eller margarine i danske supermarkeder?"),
    Prompt("q06", "pris", "Hvilken dagligvarebutik i Danmark har de bedste tilbud på yoghurt?"),
    Prompt("q07", "pris", "Hvor finder jeg de billigste æg og mælk samme sted i Danmark?"),
    # --- smag / kvalitet ----------------------------------------------------
    Prompt("q08", "smag", "Hvilken græsk yoghurt smager bedst?"),
    Prompt("q09", "smag", "Hvad er den bedste danske ost?"),
    Prompt("q10", "smag", "Hvilken mælk smager bedst i kaffe?"),
    Prompt("q11", "smag", "Hvilket smør vil du anbefale til smørrebrød?"),
    Prompt("q12", "smag", "Hvad er den bedste yoghurt naturel, man kan købe i Danmark?"),
    Prompt("q13", "smag", "Hvilken skyr smager bedst?"),
    Prompt("q14", "smag", "Hvad er en god dansk blåskimmelost?"),
    # --- anvendelse ---------------------------------------------------------
    Prompt("q15", "anvendelse", "Hvilken fløde skal jeg bruge til en flødesauce?"),
    Prompt("q16", "anvendelse", "Hvad er bedst til bagning: smør eller et blandingsprodukt?"),
    Prompt("q17", "anvendelse", "Hvilken mælk er bedst til småbørn i Danmark?"),
    Prompt("q18", "anvendelse", "Hvad kan jeg bruge i stedet for creme fraiche?"),
    Prompt("q19", "anvendelse", "Hvilken ost egner sig bedst til en gratin?"),
    Prompt("q20", "anvendelse", "Hvilken yoghurt er god til morgenmad med müsli?"),
    Prompt("q21", "anvendelse", "Hvad skal jeg vælge, hvis jeg er laktoseintolerant og bor i Danmark?"),
    Prompt("q22", "anvendelse", "Hvilken mælk skummer bedst til cappuccino?"),
    # --- vaerdier -----------------------------------------------------------
    Prompt("q23", "vaerdier", "Hvilke danske mejeriprodukter er mest bæredygtige?"),
    Prompt("q24", "vaerdier", "Hvor køber jeg økologisk mælk med god dyrevelfærd i Danmark?"),
    Prompt("q25", "vaerdier", "Findes der danske mejerier, som ikke er en del af en stor koncern?"),
    Prompt("q26", "vaerdier", "Hvilken mælk i Danmark har det mindste klimaaftryk?"),
    Prompt("q27", "vaerdier", "Hvordan finder jeg lokalt produceret ost i Danmark?"),
    Prompt("q28", "vaerdier", "Hvilke danske mejeriprodukter er dyrevelfærdsmærkede?"),
    # --- sammenligning ------------------------------------------------------
    Prompt("q29", "sammenligning", "Er økologisk mælk bedre end konventionel mælk i Danmark?"),
    Prompt("q30", "sammenligning", "Hvad er forskellen på danske og udenlandske yoghurter i supermarkedet?"),
    Prompt("q31", "sammenligning", "Skal jeg vælge dansk eller importeret ost?"),
    Prompt("q32", "sammenligning", "Er havredrik et godt alternativ til komælk i Danmark?"),
    Prompt("q33", "sammenligning", "Hvilke mejeriprodukter bør jeg vælge, hvis jeg vil handle dansk?"),
    Prompt("q34", "sammenligning", "Hvad er de mest populære mejeriprodukter i danske husholdninger?"),
    Prompt("q35", "sammenligning", "Hvilke mejerimærker findes der i Danmark?"),
)


def by_id() -> dict[str, Prompt]:
    return {prompt.id: prompt for prompt in PROMPTS}
