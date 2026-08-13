# AI-synlighed i dansk mejeri

En dateret, reproducerbar måling af, hvilke mejerimærker og hvilke
dagligvarekæder sprogmodeller faktisk anbefaler, når danske forbrugere spørger
til råds.

**[Læs rapporten](https://christopherc97.github.io/llm-brand-visibility-dk/)** — måling
13.08.2026, mindst holdbar til 11.11.2026. Én HTML-fil med alle 420 svar indeni.

Udgivelse: rapporten ligger i `docs/` og serveres af GitHub Pages fra `main`.
Kør `python3 report.py && python3 report_selftest.py`, commit `docs/index.html`,
og push — Pages bygger selv om på et halvt minut.

---

## Hvorfor

FMCG-virksomheder måler synlighed på hylden, på Google og i medierne. Ingen
måler, hvad en sprogmodel svarer, når en forbruger spørger *"hvilken græsk
yoghurt smager bedst"* eller *"hvor er mælk billigst i Danmark"*. Der er ingen
baseline, ingen KPI og ingen intern ejer — ikke fordi nogen har fejlet, men
fordi kanalen opstod hurtigere, end nogen nåede at bygge måling til den.

Det her er målingen, gjort én gang, så den kan diskuteres konkret.

## Hvad der måles

- **35 spørgsmål** med købsintention. Ingen af dem nævner et mærke- eller
  butiksnavn. Et spørgsmål med "Arla" i ville måle genkendelse, ikke synlighed.
- **2 modeller** × **2 betingelser** (uden og med websøgning) = fire celler.
- **3 kørsler** per celle, med timers mellemrum.
- **420 svar** i alt.

Metrikker per celle: omtale-rate, share of voice, først-nævnt-rate,
gennemsnitlig placering i svaret, konsistens hen over kørsler, og
Jaccard-overlap mellem modellernes top-10.

## Reproduktion

Du behøver kun dine egne API-nøgler. Ingen betalte datakilder, ingen database,
intet build-trin.

```bash
git clone <dette repo>
cd <mappen>

python3 -m venv .venv && source .venv/bin/activate
pip install openai anthropic python-dotenv

cp .env.example .env      # og udfyld dine to nøgler
```

### 1. Kør testene først

```bash
python3 selftest.py
```

157 kontroller, **nul API-kald**. De verificerer de danske falsk-positiv-værn
og fejler højlydt, hvis et spørgsmål indeholder et mærke- eller butiksnavn.
Kør altid denne, før du bruger kredit.

### 2. Pilot

```bash
python3 run.py --pass 1 --pilot     # 5 spørgsmål, 20 kald
python3 analyze.py
```

Piloten validerer pipelinen og finder huller i ordbogen. Den bruges **ikke**
til at vælge rapportens vinkel — den beslutning ligger låst i
[`report_plan.md`](report_plan.md), committet før den fulde kørsel.

Gennemgå `data/unknown_names.txt`. Eventuelt:

```bash
python3 candidates.py    # en model FORESLÅR ordbogsposter
```

Forslagene er forslag. Du redigerer `entities.py` i hånden og committer.
Sprogmodellen rører aldrig et tal.

### 3. Fuld kørsel

```bash
python3 run.py --pass 1
# vent mindst 2 timer
python3 run.py --pass 2
# vent mindst 2 timer
python3 run.py --pass 3
```

Kørslen kan afbrydes når som helst. Genoptagelsen er nøglet på
`(spørgsmål, model, betingelse, kørsel)`, og kun gennemførte kald skrives, så
intet kald betales for to gange.

Mellemrummet mellem kørslerne er ikke pynt: tre kald i træk måler kun
modellens tilfældighed i det enkelte svar. Med timers mellemrum måler
konsistenstallet også variation over tid. Rapporten skriver selv, hvilken af
de to den fik.

### 4. Analyse og rapport

```bash
python3 analyze.py           # -> data/metrics.json, data/metrics.csv
python3 report.py            # -> docs/index.html
python3 report_selftest.py   # 500+ kontroller på den færdige side
open docs/index.html
```

Rapporten er én HTML-fil uden eksterne afhængigheder: ingen webfonte, intet
diagrambibliotek, ingen netværkskald. Alle 420 svar ligger inde i filen, så
hvert tal kan følges tilbage til den tekst, det kommer fra.

`report_selftest.py` tester den færdige side mod de metodiske invarianter — at
de fire celler aldrig lægges sammen, at der ikke uddeles pladsnumre, at butiks-
og mærketal aldrig står i samme graf, at spørgsmålsniveauet opgøres i tællinger
og ikke procenter, at forbeholdene er en fuld sektion der ikke kan foldes væk,
at udløbsstemplet står over folden, og at ingen entitet er udeladt eller
nedtonet. Bryder en ændring én af dem, er rapporten forkert, uanset hvor godt
den ser ud.

## Filer

| Fil | Ansvar |
|---|---|
| `prompts.py` | Spørgsmålssættet, mærket med intention |
| `entities.py` | Ordbog med aliaser og danske værn, plus DEFUNCT-mapping |
| `config.py` | Modeller, celler, tærskler, stier |
| `run.py` | Kalder udbyderne, genoptagelig, skriver JSONL |
| `analyze.py` | Ekstraktion og metrikker |
| `report.py` | Bygger den selvstændige HTML-fil |
| `selftest.py` | Værn-tests, ingen API-kald |
| `report_selftest.py` | Invariant-tests på den færdige HTML |
| `candidates.py` | Manuelt trin uden for pipelinen |
| `report_plan.md` | Forudregistrering, committet før kørslen |

## Metodiske valg, kort

**Ekstraktion er ordbog og regex, ikke en sprogmodel.** Hele artefaktets
troværdighed hviler på, at en anden kan køre det igen og få de samme tal.
Ordbogen er en versionsstyret fil, man kan være uenig i linje for linje.

**Dansk er fyldt med fælder.** `spar penge` er ikke butikskæden SPAR.
`netto 400 gram` er ikke Netto — men `Netto har gode priser på 400 gram ost`
er. `jersey-trøjen` er ikke kvægracen. Værnene er positionelle og dækket af
tests.

**Produktkategorier står ikke i ordbogen.** `skyr` ville have ligget nummer ét
i rapporten uden at betyde noget. Det samme gælder `danbo` og `havarti`.

**Kun første forekomst per entitet per svar tælles.** Ellers ville et langt,
snakkesaligt svar veje tungere end et kort.

**Intet poolet tal.** Hver entitet vises i alle fire celler hver for sig. En
model med søgning og en uden er ikke den samme population.

**Udgåede kæder tælles kun som fejl i kontekst.** *"Aldi lukkede i 2023"* er
modellen der har ret. Kun en omtale uden lukningsmarkør i nærheden tæller.

## Hvad målingen ikke kan sige

Volumen, årsag, konvertering. Og den udløber. Rapportens sektion 10 går i
detaljer — den er ikke en formalitet, den er forskellen på en analyse og en
pitch.

## Hvad der ikke er her

Rå svar (`data/`) og API-nøgler (`.env`) er gitignored og har aldrig været i
repoet. Der er ingen data fra nogen arbejdsgiver, ingen betalte kilder, og
ingen anbefalinger til navngivne virksomheder.

## Licens

MIT for koden. Rapporten er et øjebliksbillede og bør citeres med dato.
