#!/bin/bash
# Kill line v2 ablation (PREREG_killline_v2.md §8) after the operator checkpoint.
# Usage: v2_ablate.sh T_STAR   (needs TENSORX_API_KEY; writes under ~/nmt-v2/ablation)
set -u
T=$1
export NMT_LLM_MAX_TOKENS=4096 NMT_LLM_PROVIDER=openai NMT_LLM_BASE_URL=https://api.tensorx.ai/v1
export NMT_LLM_MODEL=deepseek/deepseek-v4.1-flash
export NMT_AUTHOR_SALT=$(cat ~/nmt-runs2/.salt)
A=~/nmt-v2/ablation
mkdir -p $A
cd ~/repos/nmt-engine
one() { # name src carry category t
  rm -rf "$A/$1"; cp -r "$2" "$A/$1"
  s=$(date +%s)
  if [ -n "$3" ]; then carry=(--carry-from "$3"); else carry=(); fi
  .venv/bin/nmt mine "$A/$1" --category "$4" --t-star "$5" "${carry[@]}" > "$A/$1.mine.log" 2>&1
  echo "$1 exit=$? $(( $(date +%s)-s ))s" >> $A/times
}
cats=("habit-tracker:habit-tracker:habit tracker" "feature-flags:feature-flags:feature flags" "invoicing:invoicing-deepseek:invoicing")
for c in "${cats[@]}"; do
  IFS=: read -r name r0 cat <<< "$c"
  ( one "r12-$name" ~/nmt-live/$r0 "" "$cat" "$T"
    one "r34-$name" ~/nmt-v2/r3/$name ~/nmt-live/$r0 "$cat" "$T"
    one "r34lo-$name" ~/nmt-v2/r3/$name ~/nmt-live/$r0 "$cat" "$(python3 -c "print(round($T-0.05,2))")"
    one "r34hi-$name" ~/nmt-v2/r3/$name ~/nmt-live/$r0 "$cat" "$(python3 -c "print(round($T+0.05,2))")" ) &
done
wait
