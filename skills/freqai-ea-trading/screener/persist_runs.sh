#!/usr/bin/env bash
# 把篩選器紀錄（RUN_ROOT/<日期>/）存到 git 分支 screener-runs，或從分支取回。
# 給「容器用完即丟」的雲端排程用；本機排程不需要（紀錄留在 ~/.intraday-screener/runs）。
# 在另一個 worktree 操作，不會切換或修改目前的程式碼分支。
#
#   bash persist_runs.sh push RUN_ROOT [DAY]   把 RUN_ROOT/DAY（省略 = 全部）加進分支並推上 origin
#   bash persist_runs.sh pull RUN_ROOT         把分支上的紀錄複製回 RUN_ROOT（已存在的檔案不覆寫）
#
# 分支名稱可用環境變數 SCREENER_RUNS_BRANCH 改（預設 screener-runs）。
set -euo pipefail

cmd="${1:-}"; root="${2:-}"; day="${3:-}"
if [[ "$cmd" != "push" && "$cmd" != "pull" ]] || [[ -z "$root" ]]; then
  sed -n '2,11p' "$0"; exit 64
fi
BRANCH="${SCREENER_RUNS_BRANCH:-screener-runs}"
root="${root/#\~/$HOME}"
repo="$(git rev-parse --show-toplevel)"
wt="$(mktemp -d)"
cleanup() { git -C "$repo" worktree remove --force "$wt" >/dev/null 2>&1 || true; rm -rf "$wt"; }
trap cleanup EXIT

if git -C "$repo" fetch -q origin "$BRANCH" 2>/dev/null; then
  git -C "$repo" worktree add -q --detach "$wt" FETCH_HEAD
  fresh=0
else
  [[ "$cmd" == "pull" ]] && { echo "遠端還沒有 $BRANCH 分支（還沒有任何紀錄）"; exit 0; }
  git -C "$repo" worktree add -q --detach "$wt"
  git -C "$wt" checkout -q --orphan "$BRANCH"
  git -C "$wt" rm -rq --cached . >/dev/null
  find "$wt" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
  fresh=1
fi

case "$cmd" in
  push)
    mkdir -p "$wt/runs"
    if [[ -n "$day" ]]; then
      [[ -d "$root/$day" ]] || { echo "找不到 $root/$day"; exit 66; }
      cp -R "$root/$day" "$wt/runs/"
    else
      cp -R "$root"/. "$wt/runs/"
    fi
    git -C "$wt" add runs
    if git -C "$wt" diff --cached --quiet; then echo "沒有新紀錄"; exit 0; fi
    git -C "$wt" commit -q -m "screener runs ${day:-all}"
    for i in 1 2 3 4; do
      if git -C "$wt" push -q origin "HEAD:refs/heads/$BRANCH"; then echo "已推上 $BRANCH（${day:-全部}）"; exit 0; fi
      sleep $((2 ** i))
      [[ "$fresh" == 0 ]] && git -C "$wt" pull -q --rebase origin "$BRANCH" || true
    done
    echo "推送失敗：紀錄還在 $root，下次再試"; exit 75
    ;;
  pull)
    mkdir -p "$root"
    if [[ -d "$wt/runs" ]]; then
      (cd "$wt/runs" && find . -type f) | while IFS= read -r f; do   # 已存在的檔案不覆寫
        [[ -e "$root/$f" ]] || { mkdir -p "$root/$(dirname "$f")"; cp "$wt/runs/$f" "$root/$f"; }
      done
      echo "已取回 $(find "$wt/runs" -name 'scan-*Z.json' | wc -l | tr -d ' ') 天的紀錄到 $root"
    else
      echo "分支上還沒有紀錄"
    fi
    ;;
esac
