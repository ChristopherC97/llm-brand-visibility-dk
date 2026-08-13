"""Deterministic entity extraction for Danish dairy text.

Dictionary + regex only. No language model participates in counting — the
whole credibility of the artifact rests on someone else being able to run
this and get the same numbers.

Danish is full of traps for naive string search:

    "spar penge"                        -> SPAR the chain?      No.
    "netto 400 gram"                    -> Netto the chain?     No.
    "Netto har gode priser paa 400 g"   -> Netto the chain?     Yes.
    "prisen er netto 30 kr"             -> Netto the chain?     No.
    "jersey-troeje"                     -> Jersey the breed?    No.

The guards below are therefore *positional*: a forbidden pattern is checked
against the text immediately adjacent to the match, not anywhere in the
sentence. That is what lets "Netto har gode priser paa 400 gram ost" match
while "netto 400 gram" does not.

Deliberate exclusions (generic category words, not brands):
    skyr, ymer, hytteost, danablu, kaernemaelk, A38-style product types.
    Including any of them would put a product category at the top of the
    report without it meaning anything.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum

# A "letter" for boundary purposes: unicode letters incl. æøåÆØÅ, excl. digits.
LETTER = r"[^\W\d_]"


class EntityType(str, Enum):
    BRAND = "maerke"
    STORE = "butik"


@dataclass(frozen=True)
class Alias:
    """One surface form of an entity, with its Danish false-positive guards."""

    text: str
    # Require the matched text to start with a capital letter. Kills adverbial
    # "netto"/"spar" and lowercase "jersey" in one move.
    require_capital: bool = True
    # Regex checked against the text immediately AFTER the match (a short
    # window). Positional, so an intervening number later in the sentence
    # does not kill a legitimate match.
    forbidden_next: str | None = None
    # Regex checked against the text immediately BEFORE the match, anchored
    # at the end of the preceding window.
    forbidden_prev: str | None = None


@dataclass(frozen=True)
class Entity:
    key: str
    display: str
    type: EntityType
    aliases: tuple[Alias, ...]
    note: str = ""


@dataclass(frozen=True)
class Defunct:
    """A chain that no longer operates, for the automatic alarm check."""

    key: str
    display: str
    ended: str  # Danish, shown verbatim in the report
    detail: str


# --- Guard fragments ---------------------------------------------------------

def _inflected(*stems: str) -> str:
    """Alternation over Danish stems, tolerant of inflectional endings.

    Danish nouns inflect for definiteness and number ("trøje", "trøjen",
    "trøjerne"), so a guard anchored with \\b on the bare stem silently fails
    on the definite form — which is how "Jersey-trøjen" slipped through the
    first version of this file.
    """
    return r"(?:" + "|".join(re.escape(stem) for stem in stems) + r")[a-zæøåéA-ZÆØÅ]*\b"


# A quantity or price immediately following the word — the adverbial reading
# of "netto" ("netto 400 gram", "netto 30 kr", "netto 12 %").
_QUANTITY_NEXT = r"\s*\d+([.,]\d+)?\s*(g|gram|kg|kilo|ml|l|liter|kr|kroner|%|procent)\b"

# "netto" as an accounting adverb. Deliberately narrow: an earlier version
# included a bare "er", which would have killed "Netto er billigst" — the most
# likely legitimate sentence there is.
_ACCOUNTING_NEXT = r"\s+" + _inflected(
    "udgør", "udgoer", "beløb", "beloeb", "vægt", "vaegt", "fortjeneste", "omsætning", "omsaetning", "indtjening"
)

# "spar" as the imperative verb: "Spar penge", "Spar på mælken", "Spar 30 %".
# Known limitation, stated in the report: "SPAR på Vesterbro" (the chain
# followed by a place) is undercounted. SPAR is a small chain in Denmark and
# undercounting it is preferable to counting every "spar på" as a store.
_SPAR_VERB_NEXT = r"\s+(penge|pengene|op\s+til|paa|på|nu|stort|masser|mange)\b|" + _QUANTITY_NEXT

# "jersey" as fabric: "jersey-trøje", "jersey-trøjen", "jersey stof".
_JERSEY_FABRIC_NEXT = r"\s*-?\s*" + _inflected(
    "trøje", "troeje", "bluse", "kjole", "stof", "bukser", "tøj", "toej", "leggings", "materiale"
)


# --- Stores ------------------------------------------------------------------

STORES: tuple[Entity, ...] = (
    Entity(
        "netto",
        "Netto",
        EntityType.STORE,
        (
            Alias(
                "Netto",
                require_capital=True,
                forbidden_next=_QUANTITY_NEXT + "|" + _ACCOUNTING_NEXT,
            ),
        ),
    ),
    Entity(
        "rema1000",
        "REMA 1000",
        EntityType.STORE,
        (
            Alias("Rema 1000", require_capital=True),
            Alias("Rema1000", require_capital=True),
        ),
    ),
    Entity("lidl", "Lidl", EntityType.STORE, (Alias("Lidl"),)),
    Entity("foetex", "føtex", EntityType.STORE, (Alias("føtex", require_capital=False),)),
    Entity("bilka", "Bilka", EntityType.STORE, (Alias("Bilka"),)),
    Entity("kvickly", "Kvickly", EntityType.STORE, (Alias("Kvickly"),)),
    Entity(
        "superbrugsen",
        "SuperBrugsen",
        EntityType.STORE,
        (Alias("SuperBrugsen"), Alias("Super Brugsen")),
    ),
    Entity(
        "daglibrugsen",
        "Dagli'Brugsen",
        EntityType.STORE,
        (Alias("Dagli'Brugsen"), Alias("DagliBrugsen"), Alias("Dagli Brugsen")),
    ),
    Entity(
        "discount365",
        "365discount",
        EntityType.STORE,
        (
            Alias("365discount", require_capital=False),
            Alias("365 discount", require_capital=False),
            # Longest-match wins the overlap, so this must exist or "Coop 365"
            # would register as a plain Coop mention.
            Alias("Coop 365"),
        ),
    ),
    Entity("meny", "MENY", EntityType.STORE, (Alias("MENY"), Alias("Meny"))),
    Entity(
        "spar",
        "SPAR",
        EntityType.STORE,
        (
            Alias("SPAR", require_capital=True, forbidden_next=_SPAR_VERB_NEXT),
            Alias("Spar", require_capital=True, forbidden_next=_SPAR_VERB_NEXT),
        ),
    ),
    Entity(
        "minkoebmand",
        "Min Købmand",
        EntityType.STORE,
        (Alias("Min Købmand"), Alias("Min Koebmand")),
    ),
    Entity("loevbjerg", "Løvbjerg", EntityType.STORE, (Alias("Løvbjerg"),)),
    Entity("nemlig", "nemlig.com", EntityType.STORE, (Alias("nemlig.com", require_capital=False),)),
    Entity("abclavpris", "ABC Lavpris", EntityType.STORE, (Alias("ABC Lavpris"),)),
    Entity("salling", "Salling", EntityType.STORE, (Alias("Salling"),)),
    # Added after the pilot: Coop appeared in 11 of 20 pilot answers and was
    # missing entirely. This is exactly what the unknown-name dump is for.
    Entity("coop", "Coop", EntityType.STORE, (Alias("Coop"),)),
    # Border-shop chains. They show up on price questions and are real answers
    # to "where is dairy cheapest in Denmark".
    Entity("fleggaard", "Fleggaard", EntityType.STORE, (Alias("Fleggaard"),)),
    Entity("calle", "Calle", EntityType.STORE, (Alias("Calle"), Alias("Poetzsch Calle"))),
    Entity("ottoduborg", "Otto Duborg", EntityType.STORE, (Alias("Otto Duborg"),)),
    # Defunct chains — still matched, then flagged separately.
    Entity("aldi", "Aldi", EntityType.STORE, (Alias("Aldi"), Alias("ALDI"))),
    Entity("irma", "Irma", EntityType.STORE, (Alias("Irma"),)),
    # "fakta" is an ordinary Danish noun ("facts"). Capital required, and never
    # in front of "om"/"er"/"viser" — same failure class as "spar penge".
    Entity(
        "fakta",
        "Fakta",
        EntityType.STORE,
        (
            Alias(
                "Fakta",
                require_capital=True,
                forbidden_next=r"\s+(om|er|viser|tyder|taler|og\s+tal)\b",
            ),
        ),
    ),
)


# --- Brands ------------------------------------------------------------------

BRANDS: tuple[Entity, ...] = (
    Entity("arla", "Arla", EntityType.BRAND, (Alias("Arla", require_capital=False),)),
    Entity("thise", "Thise", EntityType.BRAND, (Alias("Thise", require_capital=False),)),
    Entity(
        "naturmaelk",
        "Naturmælk",
        EntityType.BRAND,
        (Alias("Naturmælk", require_capital=False), Alias("Naturmaelk", require_capital=False)),
    ),
    Entity(
        "oellingegaard",
        "Øllingegaard",
        EntityType.BRAND,
        (Alias("Øllingegaard"), Alias("Øllingegård"), Alias("Oellingegaard")),
    ),
    Entity("themmejeri", "Them Mejeri", EntityType.BRAND, (Alias("Them Mejeri"),)),
    Entity(
        "bornholms",
        "Bornholms Andelsmejeri",
        EntityType.BRAND,
        (Alias("Bornholms Andelsmejeri"), Alias("Bornholms Mejeri")),
    ),
    Entity("gundestrup", "Gundestrup Mejeri", EntityType.BRAND, (Alias("Gundestrup"),)),
    Entity("noerup", "Nørup Mejeri", EntityType.BRAND, (Alias("Nørup Mejeri"), Alias("Noerup Mejeri"))),
    # Mammen is also a village and a Viking-age art style; Høng is also a town.
    Entity(
        "mammen",
        "Mammen",
        EntityType.BRAND,
        (Alias("Mammen", forbidden_next=r"\s*-?\s*" + _inflected("stil", "fund", "grav", "kirke", "økse", "oekse")),),
    ),
    Entity("grambogaard", "Grambogård", EntityType.BRAND, (Alias("Grambogård"), Alias("Grambogaard"))),
    Entity("loegismose", "Løgismose", EntityType.BRAND, (Alias("Løgismose"), Alias("Loegismose"))),
    # Arla-owned product brands. They are brands, and consumers name them.
    Entity("lurpak", "Lurpak", EntityType.BRAND, (Alias("Lurpak", require_capital=False),)),
    Entity("kaergaarden", "Kærgården", EntityType.BRAND, (Alias("Kærgården"), Alias("Kaergaarden"))),
    Entity("cheasy", "Cheasy", EntityType.BRAND, (Alias("Cheasy", require_capital=False),)),
    Entity(
        "karolines",
        "Karolines Køkken",
        EntityType.BRAND,
        (Alias("Karolines Køkken"), Alias("Karolines Koekken")),
    ),
    Entity("castello", "Castello", EntityType.BRAND, (Alias("Castello"),)),
    Entity("buko", "Buko", EntityType.BRAND, (Alias("Buko"),)),
    Entity("riberhus", "Riberhus", EntityType.BRAND, (Alias("Riberhus"),)),
    Entity("klovborg", "Klovborg", EntityType.BRAND, (Alias("Klovborg"),)),
    Entity(
        "hoeng",
        "Høng",
        EntityType.BRAND,
        (Alias("Høng", forbidden_next=r"\s+" + _inflected("Kommune", "by", "station", "gymnasium", "skole")),),
    ),
    Entity("apetina", "Apetina", EntityType.BRAND, (Alias("Apetina"),)),
    Entity("puck", "Puck", EntityType.BRAND, (Alias("Puck"),)),
    Entity(
        "jersey",
        "Jersey",
        EntityType.BRAND,
        (Alias("Jersey", require_capital=True, forbidden_next=_JERSEY_FABRIC_NEXT),),
        note="Kvægrace og produktserie. Kun med stort begyndelsesbogstav, og aldrig foran tøjord.",
    ),
    # Plant-based competitors. Not dairy, but they show up in the same answers,
    # and leaving them out would hide half of what the models actually say.
    Entity("oatly", "Oatly", EntityType.BRAND, (Alias("Oatly", require_capital=False),), note="Plantebaseret"),
    Entity("alpro", "Alpro", EntityType.BRAND, (Alias("Alpro", require_capital=False),), note="Plantebaseret"),
    Entity("naturli", "Naturli'", EntityType.BRAND, (Alias("Naturli'"), Alias("Naturli")), note="Plantebaseret"),
    # Private labels. Surfaced by the pilot's unknown-name dump, not guessed —
    # a visibility study that misses supermarket own-brands misses a large part
    # of what actually gets recommended.
    Entity("milbona", "Milbona", EntityType.BRAND, (Alias("Milbona"),), note="Lidls eget mærke"),
    Entity("levevis", "Levevis", EntityType.BRAND, (Alias("Levevis"),), note="Coops eget mærke"),
    Entity("danone", "Danone", EntityType.BRAND, (Alias("Danone"),)),
    Entity("activia", "Activia", EntityType.BRAND, (Alias("Activia"),)),
)


ENTITIES: tuple[Entity, ...] = STORES + BRANDS


# --- Defunct chains ----------------------------------------------------------
# Verified 2026-08-13. Getting a date wrong here would be far worse than not
# making the claim at all, so each entry carries its own wording.

DEFUNCT: dict[str, Defunct] = {
    "aldi": Defunct(
        "aldi",
        "Aldi",
        "2023",
        "Forlod det danske marked i 2023. REMA 1000 overtog hovedparten af butikkerne; "
        "de sidste Aldi-butikker lukkede i efteråret 2023.",
    ),
    "irma": Defunct(
        "irma",
        "Irma",
        "maj 2024",
        "Lukningen blev annonceret i januar 2023, men de sidste syv butikker lukkede først i maj 2024.",
    ),
    "fakta": Defunct(
        "fakta",
        "Fakta",
        "2023–2024",
        "Kæden ophørte som selvstændigt navn og blev omdannet til 365discount.",
    ),
}

# Past-tense / closure markers. If one of these appears near a defunct-chain
# mention, the model is stating the closure correctly, not recommending the
# chain — that must NOT count as an error.
PAST_MARKERS = (
    r"lukke(de|t|r)?",
    r"ophør(te|t|er)?",
    r"ophoer(te|t|er)?",
    r"forlod",
    r"forladt",
    r"findes\s+ikke\s+(længere|laengere)",
    r"eksisterer\s+ikke",
    r"er\s+ikke\s+(længere|laengere)",
    r"tidligere",
    r"nedlagt",
    r"udgået",
    r"udgaaet",
    r"overtaget",
    r"omdannet",
    r"blev\s+til",
    r"trak\s+sig",
    r"solgt\s+til",
    r"frem\s+til\s+20\d\d",
    r"indtil\s+20\d\d",
)
PAST_MARKER_RE = re.compile("|".join(PAST_MARKERS), re.IGNORECASE)

# How far around a defunct mention to look for a past marker.
DEFUNCT_CONTEXT_CHARS = 160

# Windows the positional guards look at.
_NEXT_WINDOW = 40
_PREV_WINDOW = 40


def _fold(text: str) -> str:
    """Normalise unicode so 'ø' and 'o̸' compare equal."""
    return unicodedata.normalize("NFC", text)


def _alias_regex(alias: Alias) -> re.Pattern[str]:
    """Word-bounded pattern with optional Danish genitive (-s / -'s).

    Trailing hyphen is allowed so compounds match: "Arla-mælk" hits "Arla".
    A trailing letter does not: "Arlaskyr" must not hit "Arla".
    """
    core = re.escape(_fold(alias.text)).replace(r"\ ", r"\s+")
    return re.compile(
        rf"(?<!{LETTER})(?:{core})(?:'?s)?(?!{LETTER})",
        re.IGNORECASE,
    )


_COMPILED: dict[str, list[tuple[Entity, Alias, re.Pattern[str]]]] = {}


def _compiled() -> list[tuple[Entity, Alias, re.Pattern[str]]]:
    if "all" not in _COMPILED:
        _COMPILED["all"] = [
            (entity, alias, _alias_regex(alias))
            for entity in ENTITIES
            for alias in entity.aliases
        ]
    return _COMPILED["all"]


@dataclass
class Mention:
    entity_key: str
    display: str
    type: EntityType
    start: int
    end: int
    matched: str


def find_mentions(text: str) -> list[Mention]:
    """All guarded entity mentions in `text`, in order of appearance.

    Every occurrence is returned; the counting rule (first occurrence per
    entity per answer) is applied in analyze.py, not here, so that this
    function stays inspectable on its own.
    """
    text = _fold(text)
    found: list[Mention] = []

    for entity, alias, pattern in _compiled():
        for match in pattern.finditer(text):
            matched = match.group(0)

            if alias.require_capital and not _starts_capital(matched):
                continue

            after = text[match.end() : match.end() + _NEXT_WINDOW]
            if alias.forbidden_next and re.match(alias.forbidden_next, after, re.IGNORECASE):
                continue

            before = text[max(0, match.start() - _PREV_WINDOW) : match.start()]
            if alias.forbidden_prev and re.search(
                alias.forbidden_prev + r"\s*$", before, re.IGNORECASE
            ):
                continue

            found.append(
                Mention(
                    entity_key=entity.key,
                    display=entity.display,
                    type=entity.type,
                    start=match.start(),
                    end=match.end(),
                    matched=matched,
                )
            )

    found.sort(key=lambda m: (m.start, -(m.end - m.start)))
    return _drop_overlaps(found)


def _starts_capital(matched: str) -> bool:
    for char in matched:
        if char.isalpha():
            return char.isupper()
    return False


def _drop_overlaps(mentions: list[Mention]) -> list[Mention]:
    """Keep the longest match when two aliases overlap.

    Without this, "Min Købmand" would also register a bare "Købmand" alias if
    one were ever added, and "Rema 1000" would double-count.
    """
    kept: list[Mention] = []
    occupied: list[tuple[int, int]] = []
    for mention in mentions:
        if any(mention.start < end and start < mention.end for start, end in occupied):
            continue
        kept.append(mention)
        occupied.append((mention.start, mention.end))
    return kept


@dataclass
class DefunctHit:
    entity_key: str
    display: str
    is_error: bool  # True = recommended as if live; False = correctly described as closed
    quote: str


def check_defunct(text: str, mentions: list[Mention] | None = None) -> list[DefunctHit]:
    """Classify each defunct-chain mention as an error or a correct statement.

    "Aldi lukkede i 2023" is the model being right, and scoring it as an error
    would be the same class of mistake as matching "spar penge".
    """
    text = _fold(text)
    if mentions is None:
        mentions = find_mentions(text)

    hits: list[DefunctHit] = []
    seen: set[str] = set()
    for mention in mentions:
        if mention.entity_key not in DEFUNCT or mention.entity_key in seen:
            continue
        seen.add(mention.entity_key)

        lo = max(0, mention.start - DEFUNCT_CONTEXT_CHARS)
        hi = min(len(text), mention.end + DEFUNCT_CONTEXT_CHARS)
        context = text[lo:hi]
        stated_closed = bool(PAST_MARKER_RE.search(context))

        hits.append(
            DefunctHit(
                entity_key=mention.entity_key,
                display=mention.display,
                is_error=not stated_closed,
                quote=_quote(text, mention.start, mention.end),
            )
        )
    return hits


def _quote(text: str, start: int, end: int, radius: int = 110) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    snippet = " ".join(text[lo:hi].split())
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


# --- Unknown-name discovery --------------------------------------------------
# Dictionary coverage is the largest remaining threat to validity. This finds
# capitalised names that appear in answers but are not in the dictionary, so
# the gaps are found systematically rather than guessed at.

_CAPITALISED = re.compile(rf"(?<!{LETTER})([A-ZÆØÅ][{LETTER[1:-1]}]{{2,}}(?:\s+[A-ZÆØÅ][{LETTER[1:-1]}]{{2,}})?)")

# Common Danish sentence-initial and generic words that are not entities.
_STOPWORDS = {
    "det", "den", "der", "dette", "disse", "danmark", "danske", "dansk", "danskere",
    "hvis", "hvor", "hvad", "hvilken", "hvilke", "for", "men", "med", "har", "kan",
    "man", "jeg", "vil", "skal", "her", "som", "til", "fra", "eller", "ost", "ostene",
    "yoghurt", "mælk", "maelk", "smør", "smoer", "fløde", "floede", "skyr", "ymer",
    "hytteost", "creme", "fraiche", "økologisk", "oekologisk", "mejeri", "mejeriet",
    "supermarked", "supermarkeder", "butik", "butikker", "priser", "pris", "kvalitet",
    "produkter", "produkt", "eksempel", "generelt", "typisk", "både", "baade",
    "desuden", "derfor", "dog", "også", "ogsaa", "samt", "ved", "under", "over",
    "kort", "sagt", "bemærk", "bemaerk", "obs", "note", "tip", "tips", "husk",
    # Sentence openers. The stronger filter is corpus-level (a candidate that
    # also appears lowercase somewhere is not a name) and lives in analyze.py;
    # this list just keeps the per-answer output readable.
    "blandt", "prøv", "proev", "nogle", "mange", "andre", "flere", "hvis",
    "derudover", "endelig", "samlet", "overordnet", "personligt", "afhængigt",
    "afhaengigt", "alternativt", "vælg", "vaelg", "køb", "koeb", "prisen",
    "kvaliteten", "smagen", "udvalget", "generelt", "ofte", "typisk", "især",
    "isaer", "især", "dernæst", "dernaest", "først", "foerst", "sidst",
    "europa", "eu", "norge", "sverige", "tyskland", "grækenland", "graekenland",
    "græsk", "graesk", "januar", "februar", "marts", "april", "maj", "juni", "juli",
    "august", "september", "oktober", "november", "december",
}


_SENTENCE_START = re.compile(r"(?:^|[.!?:;•*\-–—\n]|\d+\.)\s*$")


def unknown_capitalised_spans(text: str) -> list[tuple[str, int, bool]]:
    """(name, offset, is_sentence_initial) for candidates not in the dictionary.

    The sentence-initial flag is what lets analyze.py drop Danish imperatives
    ("Kig", "Tjek", "Skær") without a hand-maintained stopword list: a word
    that only ever appears at the start of a sentence is capitalised by
    grammar, not because it is a name.
    """
    text = _fold(text)
    known_spans = [(m.start, m.end) for m in find_mentions(text)]
    out: list[tuple[str, int, bool]] = []
    for match in _CAPITALISED.finditer(text):
        if any(match.start() < end and start < match.end() for start, end in known_spans):
            continue
        candidate = match.group(1).strip()
        if candidate.lower() in _STOPWORDS:
            continue
        if all(part.lower() in _STOPWORDS for part in candidate.split()):
            continue
        preceding = text[max(0, match.start() - 12) : match.start()]
        out.append((candidate, match.start(), bool(_SENTENCE_START.search(preceding))))
    return out


def unknown_capitalised_names(text: str) -> list[str]:
    """Capitalised candidate names in `text` not covered by the dictionary."""
    return [name for name, _, _ in unknown_capitalised_spans(text)]


def all_entity_surface_forms() -> list[str]:
    """Every alias string. Used by selftest to keep brands out of the prompts."""
    return [alias.text for entity in ENTITIES for alias in entity.aliases]
