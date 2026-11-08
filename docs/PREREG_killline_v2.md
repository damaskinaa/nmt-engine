# Pre-registration: Job-Graph Miner kill line v2

Status: committed **before** any v2 re-run. Its sha256 is in the PR description. The report must
quote the same hash, and any later change to this file voids the v2 verdict.

The Session A verdict stays on record: kill line v1 was hit (7.5% / 3.2% / 5.7% on habit
tracker / feature flags / invoicing, DeepSeek-v4.1-flash, run of 2026-11-08). v2 is a new test,
not a re-score. The v1 share is reported next to v2 in every table.

## 1. Categories, data and models

- Categories: `habit tracker` (consumer app), `feature flags` (developer tool), `invoicing`
  (SMB SaaS). Same as Session A.
- Keys: `TENSORX_API_KEY` only, plus sources that need no key.
- Producer (extraction, borderline merge confirmation, cluster naming):
  `deepseek/deepseek-v4.1-flash`, `reasoning_effort=none`, temperature 0.
- Auditor (pair labels, span-label audit): `moonshotai/kimi-k3.1-pro`, a different model family
  from the producer.
- Embeddings: `qwen/qwen3-embedding-8b`, full 4096 dimensions, cached by text hash.

## 2. Evidence families

Each source has an `evidence_family`, set from its adapter and kind:

| family | sources | customer voice? |
|---|---|---|
| discussion | Hacker News, Reddit, GitHub Discussions, YouTube comments, forums | yes |
| support_issue | GitHub issues, public trackers | yes |
| qa | Stack Exchange | yes |
| review | App Store, Google Play | yes |
| vendor_page | competitor pricing / feature / docs pages, incl. archived snapshots | no |
| change_history | Wayback diffs, changelogs, release notes | no |
| search_demand | DataForSEO | no |
| market_record | statistics, filings, procurement notices, package downloads | no |

Job spans are extracted only from customer-voice sources.

## 3. Unit of analysis

- **Instance** = one job proposed by the extractor in one post, with at least one verbatim span.
- **Cluster** = instances grouped by step 3: agglomerative clustering (average linkage, cosine
  distance) over all instances of a category, on the embedding of
  `"<statement>\n<first 'job' span, if any>"`. The cut distance `t*` is chosen in §5.
- **Borderline confirmation**: cut the dendrogram at `t* - 0.05` (tight) and `t* + 0.05` (loose).
  Tight clusters are kept as they are. For every loose cluster that contains more than one tight
  cluster, the producer is shown one representative statement per tight cluster. It may only merge
  tight clusters inside that loose cluster. Nothing is split, and nothing merges across loose
  clusters.
- **Naming**: the producer names each cluster with 2 or more instances as "I want to <verb> ...",
  and says whether its members name more than one distinct expected outcome. A cluster where they
  do is flagged `mixed`. Mixed clusters are kept and reported, but they can never pass.
- **Level** = the majority level of a cluster's instances. Ties are broken in the order core,
  small, big, micro. The report shows the level mix, and the share of instances whose level
  differs from their cluster's level.

## 4. Denominator and pass rule

- **Denominator**: all clusters whose level is `core` or `small`, singletons and mixed clusters
  included. `big` and `micro` clusters are reported but excluded.
- A cluster **passes v2** when all four hold:
  1. at least 4 of the 8 elements (context, trigger, job, success_criteria, alternatives,
     negative_emotions, positive_emotions, higher_goal) have a live receipt. A receipt is live
     when its claim and source survive the gates and are not retracted. Elements excluded by the
     label audit (§6) do not count.
  2. at least 2 distinct customer-voice families among the sources that carry those element
     receipts;
  3. at least 3 distinct voices (salted author hashes) among those sources. A source with no
     author hash adds no voice;
  4. the cluster is not `mixed`.
- **v1 rule**, unchanged and reported alongside: at least 4 of 8 elements and at least 2 source
  kinds, over the same clusters.

## 5. Clustering threshold (chosen on labelled pairs, never on the result)

- Distances are taken from all within-category instance pairs. Ten equal-width bands span
  distance 0 to the median within-category pair distance. Pair sampling is pooled over the three
  categories. 20 pairs are drawn per band (200 in total, seeded, as evenly split across
  categories as each band allows).
- The auditor labels each pair `same job` or `different job`.
- **Human check**: 30 pairs are drawn at random from the 200 and labelled blind by the operator.
  If agreement with the auditor is below 80%, the run stops here and is reported.
- `t*` is the candidate threshold (grid step 0.01 over the sampled range) that maximises F1 for
  "distance <= t means same job" on the 200 auditor labels. Ties go to the smaller t. Precision
  and recall are reported.
- The pairs, the labels and `t*` are committed before the ablation (§8) runs.

## 6. Label audit

- 50 accepted spans per element (400 in total) are sampled, seeded, from the R3 extraction
  (§8), pooled over categories.
- The auditor answers yes or no to: "is this span evidence of <element> for <job>?".
- The mislabel rate per element is reported with a 95% Wilson interval. An element whose lower
  bound is **above 20%** does not count toward the 4 of 8 in R4.
- **Human check**: the operator judges 20 random audited spans blind. Agreement with the auditor
  is reported.

## 7. Metrics and verdict

Per category and run:

- **v1 share** = clusters passing the v1 rule / all clusters;
- **v2 share** = clusters passing v2 / denominator;
- **v2 instance-weighted share** = posts (distinct sources) in passing clusters / posts in
  denominator clusters;
- cluster-size distribution. A run whose largest cluster holds more than 10% of a category's
  instances is flagged **over-merged**, and its v2 share is not counted as a pass.

**Kill line v2** (on R4): v2 share below 30% in at least 2 of 3 categories means narrow to
Problems + Consideration Sets (Radar first).

- **Robustness**: R4 is recomputed at `t* - 0.05` and `t* + 0.05`, using the same procedure with
  the confirmation band centred on the shifted threshold. If the kill-line verdict differs at
  either, the verdict is **undecidable**, not pass.
- **Specificity**: the operator reviews the top 10 passing clusters per category, ranked by
  voices and then posts. If more than 3 of 10 are too broad to design a product for, that
  category counts as below 30%.

## 8. Ablation

Per category, on the same traces where possible (the LLM cache replays identical requests):

| run | change |
|---|---|
| R0 | Session A code (baseline, existing runs) |
| R1 | + step 3 clustering |
| R2 | + evidence families (diversity and pass rule count customer-voice families) |
| R3 | + new no-key collection: 5 competitors per category, extra Stack Exchange sites, App Store |
| R4 | + label-audit exclusions (§6). This is the run the verdict is read from. |

R3 adds collection to a copy of the R0 run, so earlier responses replay from the collector cache
and the R0 traces stay in R3. Cost and run time are reported per run.
