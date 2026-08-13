# Forudregistrering

Denne fil blev committet **før** den fulde kørsel. Formålet er, at ingen skal
kunne spørge, om rapportens fortælling blev valgt, efter tallene var kendt.
`git log --follow report_plan.md` viser, hvornår den lå fast.

Piloten (5 spørgsmål, 20 svar) blev kørt før denne fil, men udelukkende til at
validere pipelinen og finde huller i ordbogen. Tærskler og sektionsstruktur
nedenfor var besluttet, før piloten kørte, og er ikke justeret efter den.

## Måledesign, låst

- 35 spørgsmål, ingen mærke- eller butiksnavne (håndhævet af `selftest.py`).
- 2 modeller: `claude-opus-5`, `gpt-5.6-terra`.
- 2 betingelser: uden websøgning, med websøgning.
- 3 kørsler per celle, kørt med mindst 2 timers mellemrum.
- I alt 4 celler à 105 svar = 420 svar.
- Ingen systemprompt. Udbyderens øvrige standardindstillinger.
- Tælleregel: første forekomst per entitet per svar.

## Tærskler, låst før data

Synlighedsbånd på omtale-rate:

| Bånd | Interval |
|---|---|
| synlig | > 40 % |
| marginal | 10–40 % |
| usynlig | < 10 % |

Entiteter hvis 95 %-konfidensinterval krydser en båndgrænse markeres med †.

Konfidensintervallet beregnes med Wilson-metoden på **antal spørgsmål (35)**,
ikke antal svar (105). De tre kørsler af samme spørgsmål er ikke uafhængige
observationer, og at bruge n=105 ville gøre intervallet kunstigt smalt. Det er
et bevidst konservativt valg.

## Rapportens sektioner, låst

Sektionerne udgives i denne rækkefølge uanset hvad tallene viser. Hvis en
sektion ikke har noget at vise, står der, at den ikke har noget at vise.

1. **Overskrift, metode i ét afsnit, holdbarhedsstempel.**
2. **Indledning.** Beskriver den blinde vinkel i almindeligt forretningssprog.
   Ingen diskussion af kanalens volumen her — den hører i sektion 10.
3. **Nøgletal.** Antal svar, andel svar der nævner mindst ét mærke, andel der
   nævner mindst én butik, antal entiteter i hvert bånd.
4. **Alarm om udgåede kæder.** Udfyldes af `defunct_error_rate`.
   *Hvis den er 0:* der står "Ingen af modellerne anbefalede en udgået kæde i
   denne måling." Sektionen fjernes ikke.
5. **Butikker**, vandrette bjælker, to rækker per entitet (uden/med søgning).
6. **Mærker**, samme form.
7. **Fuld tabel:** omtale-rate, share of voice, først nævnt, konsistens,
   fordeling per celle, konfidensinterval, bånd.
8. **Modeluenighed.** Jaccard-overlap mellem top-10-sæt, beregnet **inden for
   hver betingelse**, aldrig på tværs. Plus de navne hver model er alene om.
9. **Opdeling på spørgsmålstype.** Rent kvalitativ. Ingen procenter per
   intention — 35 spørgsmål bærer ikke den opdeling.
10. **Hvad målingen ikke kan sige.** Volumen, årsag, konvertering, udløb.
    Må ikke blødes op eller forkortes.
11. **Metode**, detaljeret nok til at gentage målingen.

## Regler for præsentation, låst

- **Intet poolet tal.** Hver entitet vises altid i begge betingelser hver for
  sig. Der findes ikke ét samlet synlighedstal nogen steder i rapporten.
- **Ingen rangordning 1-15.** Entiteter grupperes i bånd. Bjælkerne sorteres,
  men pladsnumre skrives ikke.
- **Butiks- og mærketal blandes aldrig i samme graf.** De deler nævner, men
  ikke mulighedsrum.
- **Ingen anbefalinger til navngivne brands.** Rapporten viser en blind
  vinkel; den rådgiver ikke.
- Udgåede kæder tælles kun som fejl, hvis omtalen står uden en
  lukningsmarkør i nærheden. Rapporten citerer 2-3 faktiske fejl ordret.

## Hvad der ville få mig til at ændre planen

Kun to ting, og begge skal skrives ind i denne fil med dato og begrundelse:

1. En teknisk fejl i pipelinen, der gør en celle ubrugelig.
2. Et hul i ordbogen så stort, at tallene er meningsløse — i så fald udvides
   ordbogen, og **hele kørslen genanalyseres**, ikke kun den del der passer.

At tallene er kedelige, er ikke en grund til at ændre planen.
