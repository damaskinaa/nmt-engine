# Invoicing gold: provenance

The labels in this directory come from models. No human has verified them, and the B1 human
blind check is NOT DONE (docs/VERDICTS.md). Any T1 figure computed from these files is precision
against model labels.

- `gold.jsonl`, `items.jsonl`: author-role and element labels (Kimi K3.1 Pro), under the role
  rules frozen in PREREG_v3.
- `node_items.jsonl`, `node_authors.jsonl`, `node_gold.jsonl`: node-check pairs and their labels
  (Kimi), PREREG_v3 amendments 2–3.
- `cross_*.json`, `node_cross_*.json`, `*cross_agreement.json`: blind GLM-5.3 labels and
  cross-model agreement. These are a weaker substitute for a human check, not a replacement.
- `recorded/`: producer (DeepSeek V4.1 Flash) outputs, keyed by prompt hash. When a prompt
  changes, the producer is re-recorded against the gold; the gold itself does not change.
- `node_canary.json`: six synthetic pairs used only to check the prompt; they never count toward
  T1.

`gold.check` and `node_gold.check_nodes` score the recordings against these labels. CI fails if a
recording is missing or a measured class falls below 85%.
