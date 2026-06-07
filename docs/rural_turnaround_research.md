# Rural NY Population Turnarounds: Research & Findings

*Prepared 2026-06-06. Two strands: (1) a verified review of the academic / institutional literature on whether and why declining rural areas reverse population loss, and (2) an empirical analysis of which rural NY towns and villages actually turned around in the decennial census record, why, and what they have in common — backed by per-place research into news coverage, planning documents, and demographic data.*

*Data backbone: hard decennial census counts (2000 / 2010 / 2020) plus 2025 PEP estimates, built by the loader at `src/popfc/data/census_decennial.py` into `data_interim/subcounty_decennial_history.parquet`. Analysis: `scripts/rural_turnaround_v2.py`.*

---

## Table of contents

- [1. Summary](#1-summary)
  - [Summary table](#summary-table)
- [2. What the research literature says](#2-what-the-research-literature-says)
  - [Academic source list](#academic-source-list)
- [3. What we chose, and why](#3-what-we-chose-and-why)
- [4. Places, by mechanism](#4-places-by-mechanism)
  - [A. Amenity / recreation migration + second-home conversion](#a-amenity--recreation-migration--second-home-conversion)
    - [Bethel](#bethel)
    - [Edinburg](#edinburg)
    - [Sempronius](#sempronius)
    - [Speculator](#speculator)
    - [Lake George](#lake-george)
  - [B. Metro / exurban spillover](#b-metro--exurban-spillover)
    - [Princetown](#princetown)
  - [C. High-fertility religious settlement](#c-high-fertility-religious-settlement)
    - [Williamstown](#williamstown)
    - [Amboy](#amboy)
    - [Constableville](#constableville)
  - [D. Measurement artifact / small-N noise](#d-measurement-artifact--small-n-noise)
    - [Cobleskill](#cobleskill)
    - [Champlain](#champlain)
- [5. Caveats & data limits](#5-caveats--data-limits)
- [6. Next steps](#6-next-steps)

---

## 1. Summary

Declining, aging rural areas *do* sometimes reverse population loss, but — both in the national literature and in our NY data — turnarounds are **episodic, geographically selective, and concentrated in a specific kind of place**. There is no broad "rural revival"; there is what demographer Kenneth Johnson calls *selective deconcentration*: a partial, cyclical redistribution toward amenity-rich and metro-adjacent places, even as the surrounding county keeps declining.

When we look at our own NY census record, the rural towns and villages that turned around do **not** share one story. They sort into **four distinct mechanisms**, and only the first two are the "amenity migration" the national literature emphasizes:

- **A — Amenity / recreation migration + second-home→year-round conversion** (often supercharged by post-COVID remote work).
- **B — Metro / exurban spillover** from a growing metro.
- **C — High-fertility religious settlement** (Amish / Mennonite; Hasidic) — *natural increase, not migration*. A distinctively Northeast / NY phenomenon the national amenity literature underweights.
- **D — Measurement artifact / small-N noise** — chiefly the April 1, 2020 census taken during COVID lockdown, which depressed counts in seasonal-home towns and emptied college dorms.

The single most important methodological takeaway: **a meaningful share of the "turnarounds" our analysis first flagged are partly or wholly 2020-census artifacts.** Cobleskill is mostly a college-dorm undercount; several lake towns' 2020 troughs are seasonal-residence timing effects. See [§5](#5-caveats--data-limits).

### Summary table

| Place | Type | County / region | Census 2000→2010→2020 (+2025est) | Mechanism | Real turnaround? |
|---|---|---|---|---|---|
| [Bethel](#bethel) | town | Sullivan / Catskills | 4362→4255→3959 (4296) | A — amenity + NYC exurb | ✅ **Strong, well-documented** |
| [Edinburg](#edinburg) | town | Saratoga / Sacandaga Lake | 1384→1214→1333 (1339) | A — seasonal→year-round | ✅ Real (gain landed in 2020 count) |
| [Sempronius](#sempronius) | town | Cayuga / Finger Lakes | 893→895→840 (891) | A — lake amenity + census timing | ⚠️ Modest / partly artifact |
| [Princetown](#princetown) | town | Schenectady | 2132→2115→2024 (2113) | B — exurban spillover | ✅ Real, modest |
| [Williamstown](#williamstown) | town | Oswego | 1350→1277→1335 (1356) | C — Amish (natural increase) | ✅ Real (not migration) |
| [Amboy](#amboy) | town | Oswego | 1312→1263→1245 (1305) | C — Amish (natural increase) | ✅ Real (post-2020) |
| [Cobleskill](#cobleskill) | town | Schoharie / SUNY | 6407→6625→6086 (6484) | D — college dorm / COVID artifact | ❌ **Mostly artifact** |
| [Speculator](#speculator) | village | Hamilton / Adirondacks | 348→324→406 | A — retiree/amenity, thin base | ✅ / noise |
| [Constableville](#constableville) | village | Lewis | 305→242→293 | C — Amish + housing loss | ✅ direction, very noisy |
| [Lake George](#lake-george) | village | Warren / Adirondacks | 985→906→1008 | A — tourism hub, 2nd-home conv. | ✅ Special case |
| [Champlain](#champlain) | village | Clinton / border | 1173→1101→1170 | D — equilibrium (border economy) | ➖ Not structural |

---

## 2. What the research literature says

*(Synthesized from a verified deep-research pass — 22 sources fetched, 25 falsifiable claims adversarially fact-checked with 3-vote panels, 0 refuted. The field is dominated by Kenneth Johnson (UNH/Carsey Institute) and Calvin Beale / David McGranahan (USDA ERS) — canonical authorities, but not a fully independent set of research programs.)*

**Do declining rural areas turn around?** Yes, but episodically. There have been three documented nonmetro rebounds in ~50 years, each followed by renewed loss:

- **1970s "turnaround"** (Beale): for the first time in ≥150 years nonmetro gains exceeded metro gains, driven by net in-migration. Reversed in the 1980s.
- **1990s "rural rebound"** (Johnson): ~71% of nonmetro counties grew vs ~45% in the 1980s (~600 more growing counties). Concentrated in the first half of the decade; ~507 rebounding counties resumed losing population after 2000.
- **2020–21 pandemic blip**: rural America grew again after the **2010–2020 decade — the first net nonmetro loss in U.S. history**. The blip was migration-driven and bifurcated (most gains to high-amenity recreation/retirement counties); by 2020–2023 only ~45% of rural counties were gaining.

**What drives rural in-migration** (in rough order of evidentiary weight): (1) **natural amenities** — McGranahan's USDA ERS Natural Amenities Scale: high-amenity nonmetro counties grew ~120% over 1970–96 vs ~1% for low-amenity; amenities pull people first, jobs follow; (2) **recreation & retirement destinations** — the most consistent growers (all 190 retirement-destination counties gained 1990–2000); (3) **metro proximity / exurban spillover**; (4) **remote work / "Zoom towns"** (newer, lighter evidence); (5) situational drivers — energy booms, immigration, return migration — treated as non-deterministic overrides.

**Durable vs temporary:** durability is strongest in high-amenity recreation/retirement counties; broad rebounds are cyclical and tempered by economic-period effects (amenity-led migration "sharply diminished during the Great Recession").

**Why similar places diverge:** turnaround is *selective*. Even in the 1990s rebound, the Great Plains, western Corn Belt, and Mississippi Delta lost population; "remote, very thinly settled, and relatively lacking in natural amenities" counties remain extremely prone to loss regardless of national trends.

**Gap relevant to this project:** the verified literature is almost entirely national or by county-type — it contains essentially **no New York / Northeast-specific case study**. That gap is what [§4](#4-places-by-mechanism) fills.

### Academic source list

1. **Johnson, K.M. (2002).** *The Rural Rebound.* USDA Forest Service / PRB — 1970s turnaround, 1990s rebound, metro-adjacency spillover. <https://www.nrs.fs.usda.gov/pubs/book/nc_2002_johnson_001.pdf>
2. **Johnson, K.M. & Beale, C.L. (2002).** USDA Forest Service — recreation (19.3% growth) and retirement (190/190 counties gaining) destinations sustained over three decades.
3. **Johnson, K.M., Nucci, A. & Long, L. (2005).** *Population Research and Policy Review* 24:527–542 — "selective deconcentration"; rebound waned late-1990s. <https://link.springer.com/article/10.1007/s11113-005-4479-1>
4. **McGranahan, D.A. (1999).** *Natural Amenities Drive Rural Population Change.* USDA ERS AER-781 — the Natural Amenities Scale; 120% vs 1% growth gap. <https://www.leg.mn.gov/docs/2015/other/150681/PFEISref_2/McGranahan%201999.pdf>
5. **USDA ERS — Natural Amenities Scale** (topic page). <https://www.ers.usda.gov/topics/rural-economy-population/natural-amenities>
6. **Johnson, K.M. (2023).** "Population Redistribution Trends in Nonmetropolitan America, 2010 to 2021." *Rural Sociology* 88 — first-ever 2010–2020 nonmetro loss; 2020–21 migration-driven rebound. <https://onlinelibrary.wiley.com/doi/abs/10.1111/ruso.12473>
7. **Carsey Institute / UNH (2022).** "Recent Data Suggest Rural America Is Growing Again…" — pandemic rebound concentrated in amenity/recreation counties. <https://carsey.unh.edu/publication/recent-data-suggest-rural-america-growing-again-after-decade-population-loss>
8. **USDA ERS Amber Waves (2024).** "Net Migration Spurs Renewed Growth in Rural Areas." <https://www.ers.usda.gov/amber-waves/2024/february/net-migration-spurs-renewed-growth-in-rural-areas-of-the-united-states>
9. **UVA Cooper Center.** "Remote Work Persists, Migration Continues in Rural America." <https://www.coopercenter.org/research/remote-work-persists-migration-continues-rural-america>
10. **USDA ERS Amber Waves (2006).** "Recreation Counties Are the Fastest-Growing Nonmetro Counties." <https://ers.usda.gov/amber-waves/2006/february/recreation-counties-are-the-fastest-growing-nonmetro-counties>

---

## 3. What we chose, and why

**Data backbone — hard census counts, not the ACS stitch.** The repo previously had only a 2007–2025 sub-county series stitched from ACS 5-year midpoints + PEP, with a noisy methodology seam at 2019/2020 and **no villages**. That is too short and too shaky to distinguish a real multi-decade decline-then-rebound from estimation noise. We added **decennial census anchors (2000/2010/2020)** for towns *and* villages, statewide, via the Census Data API:

- County subdivisions (towns/cities — MCDs): 2000/2010 SF1 `P001001`, 2020 DHC `P1_001N`.
- Places (villages/cities/CDPs): same variables.
- Built into `data_interim/subcounty_decennial_history.parquet` (6,600 rows; 1,023 county subdivisions + 1,294 places × 3 censuses; 0 nulls).
- 1990 and earlier sub-county counts are **not** served by the Census API (NHGIS-only) — out of scope here, so "turnaround" means a 2000→2020(→2025) trajectory, not a reversal back to the 1970s.

**"Rural" filter.** Exclude NYC, Long Island (Nassau, Suffolk), and dense downstate (Westchester, Rockland); keep towns with a 2020 census count of 500–8,000. For villages we attach a primary county (via the Census sub-county estimates SUMLEV 157) and apply the same exclusion, so the rankings aren't swamped by Long Island / Westchester resort villages (Quogue, the Hamptons, Larchmont) — which are themselves textbook amenity turnarounds, but downstate, not rural-upstate.

**"Turnaround" definition.** For towns: a peak among the census points, a subsequent decline of ≥5% into a 2010 or 2020 trough, then recovery of ≥25% of the lost population, with the latest value at or above 2020. For villages (3 census points only): a V-shape — declined ≥3% 2000→2010, rebounded ≥2% 2010→2020. We show the trajectory mix (of 711 rural towns: 300 steady decline, 279 peak-and-fall, 70 V-shaped turnaround, 60 steady growth) so the turnarounds are seen against the dominant decline.

**Why a four-mechanism framing.** When we researched the top places individually (news, planning docs, demographic data), they clearly did not share one cause. Forcing them into a single "amenity migration" narrative would be wrong: two of the strongest, cleanest cases (the Oswego towns) are **Amish natural increase**, and one (Cobleskill) is **not a real turnaround at all**. Sorting by mechanism keeps those distinctions honest — and matters for forecasting, because mechanisms C and D will *not* respond to amenity-based models.

**Real vs artifact.** We explicitly grade each place. The 2020 census reference date (April 1, 2020) fell during COVID lockdown and systematically biased counts downward for (a) seasonal/lake communities (owners counted at primary residences) and (b) college towns (students sent home from dorms). Post-2020 PEP estimates, built on a depressed 2020 base, then show illusory "recovery." We flag where this dominates.

---

## 4. Places, by mechanism

*Population figures are decennial census total counts (2000 / 2010 / 2020); the parenthetical is the 2025 PEP estimate where available. Absolute swings are small — for the tiniest villages, ~30 households is the entire turnaround, so treat percentages with care.*

### A. Amenity / recreation migration + second-home conversion

*The literature's #1–#3 drivers (natural amenities, recreation/retirement, metro proximity), often accelerated by post-COVID remote work.*

#### Bethel
**Town, Sullivan County (Catskills). 4362→4255→3959 (4296).** The best-documented and most clearly "real" turnaround of all seven towns — a textbook Catskills **"Zoom town."** Sullivan County was **New York's fastest-growing county in 2020–21** (+1.5%; 762 movers directly from NYC); Q1-2021 home sales jumped +63% YoY and median prices nearly doubled 2019→2023 — a study by Pattern for Progress called it "irrefutable evidence of gentrification." Layered on the migration wave: **Bethel Woods Center for the Arts** (opened 2006 on the original Woodstock site; Wikipedia notes it "led to increased development… along the Route 17B corridor"); the **Resorts World Catskills casino** (2018, the county's largest private employer); waterfront conversion on **White and Kauneonga Lakes**; and **Hasidic/Orthodox** seasonal→year-round settlement. The wave compressed into 2020–22 (Sullivan resumed slight net loss by 2022–23), and the deep 2020 trough is partly a seasonal-residence April-census effect.

- Cornell PAD — NYC pandemic exodus to upstate: <https://news.cornell.edu/stories/2022/03/pandemic-prompted-exodus-new-york-city-gains-upstate>
- Pattern for Progress — gentrification study (Sullivan median home price $141K→$280K, 2019–23): <https://wjffradio.org/new-study-of-pandemic-era-population-shifts-shows-irrefutable-evidence-of-gentrification/>
- Catskill Farms / Westfair — Q1-2021 Sullivan real-estate data: <https://westfaironline.com/138195/chuck-petersheim-pandemic-fuels-a-new-and-forever-changed-hudson-valley-catskills/>
- Empire Center — NYC out-migration fueling upstate gains: <https://www.empirecenter.org/publications/nycs-out-migration-fueled-ny-states-record-population-drop/>
- Bethel Woods Center for the Arts (economic impact, development effect): <https://en.wikipedia.org/wiki/Bethel_Woods_Center_for_the_Arts>
- Resorts World Catskills: <https://en.wikipedia.org/wiki/Resorts_World_Catskills>

#### Edinburg
**Town, Saratoga County (Great Sacandaga Lake, southern Adirondacks). 1384→1214→1333 (1339).** ~63% of housing units are seasonal camps; median age 56.8. The clearest local journalism of any town here: the *Daily Gazette* (2021) documented Great Sacandaga Lake as a **pandemic refuge** — NYC/NJ second-home owners arriving early in 2020 (and thus enumerated at the lake on April 1) and converting to year-round — and the four Saratoga-Adirondack towns ran a 2021 **resident-recruitment campaign** citing "part-timers moving up permanently." Growth is essentially flat after 2020 and capped by Adirondack Park Agency density limits, so the recovery largely *landed in the 2020 count itself*.

- Daily Gazette — "For many, Great Sacandaga Lake was a refuge during pandemic" (2021): <https://dailygazette.com/2021/05/27/for-many-great-sacandaga-lake-was-refuge-during-pandemic/>
- NCPR — Saratoga's four Adirondack towns seek new residents (2021): <https://www.northcountrypublicradio.org/news/story/43868/20210602/saratoga-county-s-four-adirondack-towns-seek-to-attract-new-residents>
- Adirondack Explorer — Adirondack real-estate boom: <https://www.adirondackexplorer.org/stories/adirondack-real-estate-boom/>
- EIG — how remote work shifts population (vacation-home concentrations predict growth): <https://eig.org/how-remote-work-is-shifting-population-growth-across-the-u-s/>

#### Sempronius
**Town, Cayuga County (Owasco/Skaneateles Lakes, Finger Lakes). 893→895→840 (891).** No place-specific journalism exists. Best-supported reading: a lake-amenity town whose 2020 trough is substantially an **April-census seasonal-timing effect** (the Glen Haven resort hamlet on Skaneateles Lake, where cottages are increasingly built "for year-round occupancy"), plus modest post-COVID amenity in-migration and possible spillover from the **adjacent Summerhill Amish settlement**. The recovery runs *against* a declining Cayuga County, implying a localized driver. ⚠️ Modest and partly artifact.

- Glen Haven, NY (seasonal→year-round cottage conversion): <https://en.wikipedia.org/wiki/Glen_Haven,_New_York>
- Census 2020 residence criteria (seasonal homes counted at primary residence): <https://www.census.gov/content/dam/Census/programs-surveys/decennial/2020/2020-Census-Residence-Criteria.pdf>
- USDA ERS — post-2020 rural net-migration growth: <https://www.ers.usda.gov/amber-waves/2024/february/net-migration-spurs-renewed-growth-in-rural-areas-of-the-united-states/>
- Amish settlement in adjacent Summerhill (Amish America): <https://amishamerica.com/amish-greenhouse/>

#### Speculator
**Village, Hamilton County (Adirondacks). 348→324→406.** Hamilton County (NY's least-populous, >70% seasonal housing, 31% aged 65+) was nearly the only Adirondack county to gain 2010–2020, and Adirondack Explorer attributes it to **empty-nest retirees** plus **second-home→primary-residence conversion**. Oak Mountain ski area was revived ~2010–12. But at 324→406 people, a swing of **~30 households is the whole turnaround** — structural amenity drift and small-N noise are indistinguishable.

- Adirondack Explorer — Adirondack census numbers, sparsity of people/housing: <https://www.adirondackexplorer.org/stories/adirondack-census-numbers-point-to-sparsity-of-people-housing>
- Protect the Adirondacks — Hamilton/Warren/Saratoga 2020 gains: <https://www.protectadks.org/us-census-saratoga-hamilton-and-warren-counties-all-post-2020-population-gains-in-first-release-of-new-data/>
- Adirondack Life — Oak Mountain, Speculator: <https://www.adirondacklife.com/2024/01/04/small-wonder-speculators-oak-mountain/>

#### Lake George
**Village, Warren County (Adirondacks). 985→906→1008.** The special case you flagged. Distinct from Speculator: a **year-round tourism hub** (Canada Street; ~250,000 summer-area population; ~1,000 J-1 workers each summer) with **central water/sewer** that supports denser year-round habitation, plus second-home conversion and modest net housing-unit growth. Recently awarded a **$10M state Downtown Revitalization Initiative grant (2023)** aimed explicitly at a "year-round economy" — though that post-dates the 2020 census. Short-term-rental growth is now a countervailing pressure on year-round housing. The April-census timing does *not* inflate it (the summer workforce isn't present on April 1).

- NCPR — Lake George $10M Downtown Revitalization grant: <https://www.northcountrypublicradio.org/news/story/49027/20231227/lake-george-town-village-to-get-10-million-downtown-revitalization-grant>
- NY HCR — DRI award announcement: <https://hcr.ny.gov/news/governor-hochul-announces-lake-george-10-million-capital-region-winner-seventh-round-downtown>
- Lake George Mirror — STRs limiting year-round housing stock: <https://www.lakegeorgemirror.com/short-term-rentals-driving-up-costs-limiting-stock-of-year-round-housing/>

### B. Metro / exurban spillover

#### Princetown
**Town, Schenectady County. 2132→2115→2024 (2113).** A farm-and-subdivision exurb 7 miles west of Schenectady (32-min mean commute; household income ~25% above county). The **Capital Region is the only NY metro with positive domestic migration**, and Schenectady County posted the state's 2nd-largest numeric gain in 2023–24. No town-specific reporting, but the regional exurban pull (amplified by remote-work willingness to live farther out) is well-documented. ✅ Real, modest; minor 2020-COVID enumeration noise possible.

- CDRPC — 87% of Capital Region communities grew 2023–24: <https://cdrpc.org/87-of-communities-in-the-capital-region-experienced-growth-between-2023-and-2024>
- Center for Economic Growth — Capital Region is NY's 3rd-fastest-growing: <https://www.ceg.org/articles/capital-region-is-nys-3rd-fastest-growing-region/>
- Census Bureau — metro growth driven by exurbs (2026): <https://www.census.gov/library/stories/2026/05/major-city-outer-edge-growth.html>

### C. High-fertility religious settlement

*Natural increase (and land purchase), not amenity migration — a distinctively Northeast/NY phenomenon. NY's Amish population quadrupled 2000→2023 (~4,500 → ~23,285).*

#### Williamstown
**Town, Oswego County. 1350→1277→1335 (1356).** The best-documented driver of any town here. The **Swartzentruber "Pulaski/Williamstown" Amish settlement**, founded 2006 by families from Wayne County, OH, grew from 25 families (2009) to **4 church districts / ~465–615 people by 2021** (Young Center / Elizabethtown College) across Williamstown, Amboy, and adjacent towns. Williamstown's **ACS fertility rate is flagged at more than double the benchmark** — a direct demographic fingerprint (Swartzentruber TFR ≈ 10.4). No prison/college/lake; recovery is natural increase. ✅ Real (not migration).

- Amish America — Oswego County NY Amish (settlement founding, growth, named towns): <https://amishamerica.com/oswego-county-new-york-amish/>
- Census Reporter — Williamstown (elevated fertility flag): <http://censusreporter.org/profiles/06000US3607582073-williamstown-town-oswego-county-ny/>
- Young Center — 2023 NY Amish statistics (58 settlements, 23,285 people): <https://groups.etown.edu/amishstudies/statistics/population-2023/>
- Daily Yonder — Amish population growth in rural America: <https://dailyyonder.com/amish-population-growth-rural-america/2024/04/10/>

#### Amboy
**Town, Oswego County. 1312→1263→1245 (1305).** The same Pulaski/Williamstown Amish settlement explicitly includes Amboy ("our growing Amish community in Amboy/Williamstown"). Amboy's 2020 count still sits below 2010 — the recovery shows up *after* 2020 in the estimates — consistent with the settlement filling in the Williamstown/Richland core first and reaching Amboy's geography later. ✅ Real, post-2020.

- Census Reporter — Amboy: <http://censusreporter.org/profiles/06000US3607501649-amboy-town-oswego-county-ny/>
- Amish America — Amboy/Williamstown community reference: <https://amishamerica.com/ever-see-an-amish-buggy-like-this/>

#### Constableville
**Village, Lewis County. 305→242→293.** Its own **2025 Comprehensive Plan** documents a "dramatic decrease in housing units between 2000 and 2010" — explaining the deep 2010 trough. The 2010→2020 rebound is most plausibly **Amish spillover from the well-documented Lowville settlement** (founded 1999) — corroborated because the surrounding **town of West Turin bounced in lockstep** (1,674→1,524→1,688), a township-wide force, not a village quirk. ✅ Direction is real; very high small-N noise (~300 people); Amish link is regional inference, not village-level documented.

- Village of Constableville Comprehensive Plan (2025): <https://lewiscountyny.gov/wp-content/uploads/2025/06/FINAL-Village-of-Constableville-Comprehensive-Plan.pdf>
- Watertown Daily Times / nny360 — North Country Amish growth: <https://www.nny360.com/news/north-country-s-amish-population-continues-to-grow/article_1b199cc8-c7ff-5360-b9c1-760ef5f697d7.html>
- West Turin, NY (parallel township rebound): <https://en.wikipedia.org/wiki/West_Turin,_New_York>

### D. Measurement artifact / small-N noise

#### Cobleskill
**Town, Schoharie County (SUNY Cobleskill). 6407→6625→6086 (6484). ❌ Mostly a census artifact — recommend dropping or flagging, not treating as a real turnaround.** Hard census group-quarters data: dorm population fell **1,266 (2010) → 1,076 (2020)**, and SUNY Cobleskill emptied its dorms by **March 30, 2020 — two days before the April 1 Census Day** — during the COVID shutdown. National research finds college counties undercounted ~2% in 2020 (5–15% in some college towns). The +200 PEP jump in 2021 is largely an artifact of building estimates on a depressed 2020 base; enrollment is still below 2,000 and dorms hold ~1,200. The genuine 2010s decline (real enrollment slide + rural household loss) is separate and downward.

- SUNY Cobleskill — Quick Facts (enrollment, on-campus housing): <https://www.cobleskill.edu/about/institutional-research/quick-facts.aspx>
- EdWorkingPapers (2023) — COVID college-closure impact on the 2020 Census (~2% undercount in college counties): <https://edworkingpapers.com/ai23-765>
- Route Fifty — college towns challenging 2020 census results: <https://www.route-fifty.com/management/2021/10/college-towns-challenging-census-results-after-pandemic-poses-count-problems/186421/>
- Census Bureau — modifying 2020 operations for counting college students: <https://www.census.gov/newsroom/press-releases/2020/modifying-2020-operations-for-counting-college-students.html>

#### Champlain
**Village, Clinton County (US–Canada border). 1173→1101→1170.** Not really a turnaround — the village **oscillates around a stable ~1,150 equilibrium**, anchored by the I-87 border-crossing economy and a stable, well-paid **CBP / Border Patrol** presence (a new 50-agent station broke ground 2023), plus above-average fertility. The Roxham Road asylum crossings involved people *transiting to Canada*, not settling. ➖ Stabilization, not a structural rebound.

- CBP — new Champlain Border Patrol station groundbreaking (2023): <https://www.cbp.gov/newsroom/local-media-release/border-patrol-breaks-ground-new-station-champlain-new-york>
- Town of Champlain — economic development: <https://www.townofchamplain.gov/economic-development>
- Census Reporter — Champlain village (fertility, ancestry): <http://censusreporter.org/profiles/16000US3613739-champlain-ny/>

---

## 5. Caveats & data limits

- **No pre-2000 sub-county data.** 1990 and earlier town/village counts are not on the Census API (NHGIS-only). "Turnaround" here is a 2000→2020(→2025) trajectory, not a reversal of multi-decade 20th-century decline. Adding an NHGIS extract would materially strengthen this.
- **The 2020 census is a biased trough.** Taken April 1, 2020 during COVID lockdown, it systematically **undercounts seasonal/lake communities** (owners at primary residences) and **college dorms** (students sent home). Post-2020 PEP "recovery," built on that depressed base, can be illusory. This affects the lake towns ([Bethel](#bethel), [Edinburg](#edinburg), [Sempronius](#sempronius), [Speculator](#speculator)) and especially [Cobleskill](#cobleskill). The town forecast keys off exactly this 2020 point — read the real signal off 2000→2010 plus 2023–2025 instead.
- **Town-level components of change don't exist in-repo** (births/deaths/migration are county-only), so migration-vs-natural-increase attribution is *inferred*, not measured.
- **Small-N noise.** Several places (Speculator, Constableville, Champlain ~300–1,100 people) swing several percent on a handful of households; no structural story is strictly required.
- **Region/amenity tags are hand-coded by county FIPS** — coarse. Quantifying the amenity hypothesis properly is the next step ([§6](#6-next-steps)).
- **Place-specific journalism is thin** for the smallest towns (Williamstown, Amboy, Sempronius, Princetown); their explanations lean on regional reporting + demographic fingerprints, clearly labeled as inference.

---

## 6. Next steps

1. **Merge in the USDA ERS Natural Amenities Scale** (county-level): join to the NY towns/villages by `county_fips` and test whether the turnaround set scores higher than the steady-decline set — quantifying the amenity hypothesis, while explicitly separating the Amish/Hasidic (Mechanism C) and artifact (Mechanism D) cases that should *not* track amenities.
2. **Add artifact flags to `subcounty_decennial_history.parquet`**: a college/group-quarters flag (pullable from Census GQ tables) and a seasonal-housing share, so the forecast can down-weight 2020-census troughs where they are timing artifacts.
3. **Add the 1970–1990 NHGIS extract** so "turnaround" can mean a true multi-decade reversal.

*See also: [`docs/planning.md`](planning.md) for project status; loader at `src/popfc/data/census_decennial.py`; analysis at `scripts/rural_turnaround_v2.py`.*
