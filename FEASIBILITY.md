# Courtfall – data feasibility (checked 24 Oct 2026, by running the data)

## Files produced
- `parse_cache.py` – pulls the raw rows out of the MoJ xlsx pivot cache (no Excel needed).
- `trials_raw.parquet` (448,216 rows), `open_raw.parquet` (3,304,148 rows).
- `build_panel.py` -> `court_quarter.parquet`: 2,878 rows = Crown court x quarter, 2016Q1–2026Q2. Columns: effective, cracked, ineffective, vacated, listed_on_day (=eff+crk+inef), ineffective_rate, cracked_rate, inef_<lever> counts.
- `baseline.py` -> `baseline_results.txt`.
- `geocode_courts.py` -> `court_locations.csv` (lat/lon from HMCTS Find a Court or Tribunal pages).

## 1. Heatmap – SUPPORTED
- Trials data: 70 named Crown court centres (+"Unknown"). 68 report every quarter 2024–26. Blackfriars (last 2019) and Dorchester (last 2016) are closed – drop them.
- Locations: `court_locations.csv` has lat/lon for all 68 active courts. 67 from HMCTS Find a Court pages (https://www.find-court-tribunal.service.gov.uk/courts/<slug>, Google Maps link with exact lat,long); Truro from postcodes.io TR1 2PB – verify. Names mapped cleanly; 4 needed manual slugs (Northampton, Taunton, Isle of Wight, Mold – done).
- Caveat: Crown data in trials_tool effectively starts 2016 (2010–15 rows are magistrates).

## 2. Prediction – NOW SUPPORTED (see Gap-filling update below: per-court open caseload found in cc_rdos_tool)
- Next-quarter ineffective / cracked rate per court + top causes: yes, all in the panel.
- Backlog 4–8 quarters ahead: **open caseload (cc_open_tool) is NOT per court.** It is by LCJB area (~42 areas + regions + national), 2016–2026, with age bands and trial/custody splits. Every court in trials_tool carries its lcjb_area (44 areas), so: simulate backlog per LCJB area and show it when a court is clicked ("Snaresbrook sits in North East London LCJB: backlog X"). Splitting an area backlog across its courts by trial share is an assumption – label it as such.
- Disposals/receipts per area: cc_rdos_tool (same release, not downloaded yet) – needed for the backlog flow model. Download it next.

## 3. Levers – reason-code mapping (Crown, ineffective trials 2023–26Q2, n=26,983)
| Lever | Reason codes (ineffective) | Count | Share of ineffective |
|---|---|---|---|
| Overlisting | 24 Overlisting | 6,430 | 23.8% |
| Prosecution/witness not ready | 1,2,3 prosecution not ready/disclosure; 4,5,6 prosecution witness absent; 15,16 prosecution advocate | 7,218 | 26.8% |
| No defence advocate | 19 defence advocate in other trial, 20 failed to attend, 21 defendant dismissed advocate | 1,948 | 7.2% |
| Prisoner not produced | 14 not produced by prisoner escort | 636 | 2.4% |
| (bonus) Judge availability | 23 | 471 | 1.7% |
| Everything else | defendant absent/ill, defence not ready, jurors, interpreter, over-runs, etc. | 10,280 | 38.1% |
Also cracked codes 07/08 (prosecution ends case: insufficient evidence / witness absent) are tagged for the prosecution lever.
- National ineffective rate: 16.2% (2019) → 36.3% (2022 strike) → 26.9% (2023) → 24.5% (2026 H1). Matches NAO "16% in 2019 to 27% in 2023" – good sanity check.
- Court spread 2024–26: Swansea 9.3%, Preston 11.0% vs Stafford 36.9%, Harrow 40.1%, Isle of Wight 40.7%.
- **Sitting days: NATIONAL ONLY.** 2024/25 sat 107,771 days (PQ 100312, answered 6 Jan 2026); 2025/26 allocation 111,250 (GOV.UK 1 Oct 2025); 2026/27 uncapped, ~113,500 expected for 2027/28 and 117,000 for 2028/29 (WMS HCWS1362, 25 Feb 2026). No public per-court sitting days found – split national days to courts by share of trials (assumption, label it) or make the slider national/area-level.
- Caveat: data counts trials, not days. A failed trial does not always waste a whole day (floaters/backers fill slots; overlisting exists precisely for that). Treat "1 ineffective trial ≈ 1 lost trial-slot day" as an explicit, adjustable assumption.

## 4. Costs – PARTLY SUPPORTED
- Crown Court sitting day: £3,036 average (2022-23), HMCTS costs only, excl. legal aid/CPS (PQ 4727, answered 5 Dec 2023; also 2018-19 £2,719 … 2021-22 £3,027). Use as cost per added day AND value of a recovered day.
- Defence advocates: up to £34m/yr criminal legal aid advocate uplift (PQ 100312) – national, not per-court effect. NAO: trials cancelled for counsel unavailability 71 (2019) → 1,441 (2023).
- Prisoner escort / video links, CPS readiness: **no public per-court cost found.** Make these user-entered cost inputs with a clear "assumed" label.
- Decision = (backlog cases cleared or days recovered) / £ per lever per court, with cost inputs editable.

## Baseline (test 2024Q1–2026Q2, 68 courts, 680 court-quarters, quarters with ≥10 trials)
| Model | MAE | trial-weighted MAE |
|---|---|---|
| Naive last quarter | 5.89pp | 5.15pp |
| Mean of last 4 quarters | 5.20pp | 4.49pp |
| LightGBM (lags, cracked rate, volume, lever shares, court, region, season) | 5.79pp | 5.29pp |
| LightGBM on residual vs 4q mean, trained without 2020–22 | 5.38pp | 4.86pp |
| 50/50 blend of 4q mean + residual model | 5.09pp | 4.45pp |
Honest reading: rolling-4 mean is a very strong baseline; ML only matches it (blend ~1–2% better). Court-quarter noise dominates. Pitch it as "we beat last-quarter-repeats by ~14%, and we tested honestly" – don't claim ML magic. Improve with open-caseload features per LCJB and cc_rdos receipts.

## Gaps (don't fake these)
1. ~~No per-court backlog~~ SOLVED: cc_rdos_tool has per-court open/receipts/disposals (see update).
2. No per-court sitting days → national figures, allocated by assumption.
3. No per-trial data (needs HMCTS / MoJ Data First via ADR UK).
4. Lever effect sizes (e.g. "video links cut not-produced by 50%") are assumptions → sliders, not predictions.
5. Costs other than sitting day are not public per court.

---
# Gap-filling update (24 Oct 2026, 17:50 BST)

## Gap 1+3: per-court backlog, receipts, disposals – SOLVED ✅ downloaded
- Source: **cc_rdos_tool.xlsx**, same MoJ CCSQ Apr–Jun 2026 release: https://assets.publishing.service.gov.uk/media/6ab1379a086ce7c57b8187b1/cc_rdos_tool.xlsx
- Fields: year, quarter (2016Q1–2026Q2), receipt_type (either-way trials / indictable-only / committed for sentence / appeals), region, lcjb_area, **crown_court (71)**, rdos = Receipts / Disposals / **Open**, offence_group. 363,576 rows.
- Built `court_rdos_quarter.parquet` (2,957 rows: court, lcjb_area, year, quarter, receipts, disposals, open). Same court names as trials_tool → joins directly.
- Verified: national open 2026Q2 = 80,829 (ministers: "over 79,000" in Feb 2026); receipts 28,234, disposals 27,837. Biggest backlogs 2026Q2: Snaresbrook 4,588, Isleworth 2,799, Birmingham 2,574, Wood Green 2,372, Woolwich 2,304.
- Use: simulator now runs **per court**: open[t+1] = open[t] + receipts − disposals. Backtestable on real history.
- Also downloaded: `cc_waiting_hearing_tool.xlsx` (waiting/hearing times – region level only, not court) and `Transparency_files.zip` (325 MB; flat CSVs of all tools incl. cc_rdos_2026Q2.csv, trials_2026Q2.csv – same content, easier to load).

## Gap 2: per-court sitting days – PARTLY
- National monthly sitting days FY2015-16 → 2025-26 ✅ downloaded `data/Sitting_Day_Ad-Hoc_March_2026.xlsx` (HMCTS MI, 14 May 2026, https://www.gov.uk/government/statistical-data-sets/hmcts-management-information-march-2026). FY totals e.g. 107,921 (24-25), 110,647 (25-26). Monthly → aligns with quarters.
- **Best per-court source found: PQ 26915 (answered 5 Feb 2025)** – attached table gives, per Crown Court location per month (Jul 2023–Jun 2024), maximum available session hours and hours actually used. Attachment: https://qna.files.parliament.uk/qna-attachments/1759314/original/2025-02-05%20PQ%2026915%20Table.xlsx – ❌ NOT downloaded: Cloudflare blocks scripted download. Saed: open the link in a normal browser and save to data/. That gives one year of per-court capacity + utilisation → use to split national days by court (far better than trial-share assumption).
- PQ 29551 (14 Feb 2025): minister says per-court court time "is not currently (and never has been) published"; post-July-2024 data was being quality-assured. So no regular per-court series exists.
- Scattered per-court figures in PQs (e.g. Birmingham + Wolverhampton sat 5,655 days in 2024/25, 5,450 in 2023/24 – PQ 59985, 24 Jun 2025). Searchable via the API: https://questions-statements-api.parliament.uk/api/writtenquestions/questions?searchTerm=... (works with curl; attachments sit behind Cloudflare).
- Older FOI: MoJ FOI 190715025 (2019) – recorder sitting days by court centre since 2010 (recorders only, old): https://assets.publishing.service.gov.uk/media/5da977dce5274a5caa945a48/FOIA_190715025_Response.pdf
- Legal route for fresh per-court days: FOI to MoJ (20 working days) – e.g. via WhatDoTheyKnow. Not in time for the hackathon.

## Gap 4: lever costs/effects – PARTLY (no per-court costs anywhere)
- Sitting day £3,036 (PQ 4727, 2022-23) – already have.
- Prisoner escort: PECS penalty "over £600 per 15-minute delay in Crown Court" (Inside HMCTS blog, 13 Oct 2025, https://insidehmcts.blog.gov.uk/2025/10/13/inside-pecs-managing-one-of-governments-most-complex-contracts/). Contractual on-time performance 99.93% (PQ, 23 Jul 2025). Note MoJ says code 14 "may not have been as a direct result of PECS supplier failure" (PQ 57486, 13 Jun 2025).
- Video links: MoJ Virtual Court pilot evaluation – net extra cost £247 per case (incl. £240 tech) vs £34 transport saving per case (old, 2010, first hearings): https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/193633/virtual-courts-pilot-outcome-evaluation.pdf. Also "The impact of remote hearings on the Crown Court" (MoJ 2023): https://assets.publishing.service.gov.uk/media/641ac7ade90e0769ebc31f0b/the-impact-of-remote-hearings-on-the-crown-court.pdf (not read in full).
- Defence advocates: up to £34m/yr advocate fee uplift (PQ 100312); NAO 2024: counsel-unavailability cancellations 71 (2019) → 1,441 (2023); barristers doing public criminal work −10% 2016-17→2021-22 (https://www.nao.org.uk/wp-content/uploads/2024/05/reducing-the-backlog-in-the-crown-court-1.pdf).
- CPS: ✅ downloaded `data/CPS_area_tables_Q4_2025-26.xlsx` (https://www.cps.gov.uk/publication/cps-data-summary-quarter-4-2025-2026) – pre-charge and prosecution outcomes by CPS area (14 areas). Gives outcomes, NOT readiness/disclosure timeliness or cost. Context feature only.
- Conclusion: effect sizes stay as sliders; costs: sitting day (solid), PECS penalty (proxy for £ value of a lost escort slot), video £/case (old pilot), advocates (national only).

## Gap 5: case/hearing-level data – NOT available in 24h
- Daily Crown Court lists: Court and Tribunal Hearings Service (CaTH) https://www.court-tribunal-hearings.service.gov.uk/ (has an API), also Xhibit https://xhibit.justice.gov.uk/court_lists.htm and CourtServe (free sign-up). **Bulk scraping / computational reuse needs an HMCTS Third-Party Courts and Tribunals Data Licence** (approved by a governance panel): https://www.gov.uk/government/publications/hmcts-third-party-courts-and-tribunals-data-licence/hmcts-third-party-courts-and-tribunals-data-licence-application-guidance. Lists are published 11:59pm the night before and removed next day; no historic archive. → Don't scrape for the hackathon. Could be shown as a "future: live daily risk scoring" slide.
- MoJ Data First Crown Court defendant dataset (Xhibit, disposals Jan 2013–Mar 2023, one row per defendant per case): via ONS Secure Research Service. Needs accredited researcher + project approval (~10 weeks; ONS median 26 working days to approval + 12 to data) + HMCTS Data Access Panel (8–12 weeks). Guide: https://assets.publishing.service.gov.uk/media/683863d5c99c4f37ab4e867c/Data_First_User_Guide_Version_8.2.pdf
- HMCTS Data Access Panel (aggregate case info for research): dataaccesspanel@justice.gov.uk.

## Still truly unavailable (publicly, now)
1. Regular per-court sitting days (only one-year session-hours table via PQ 26915 + scattered PQs).
2. Per-court lever costs; CPS readiness/disclosure timeliness by area.
3. Individual trial/hearing records (licence or Data First only, weeks–months).
