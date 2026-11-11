#!/usr/bin/env bash
# docs/data/history.json(대시보드 스냅샷)의 임계값 등을 data/stock.txt 와 일치시켜 main 에 push 한다.
#
# history.json 의 이 필드들은 stock.txt 에서 파생되는 값이므로, push 가 경쟁(다른 워크플로가 먼저
# push)으로 거절되면 rebase 하지 않고 "최신 origin/main 으로 되돌린 뒤 다시 계산"한다.
# (rebase 시 두 워크플로가 같은 JSON 을 고쳐 생기는 충돌을 피하기 위함 — 결과는 항상 동일하다.)
set -u

BRANCH="${SYNC_BRANCH:-main}"
MSG="${SYNC_COMMIT_MSG:-[Stock Alert] Sync dashboard thresholds}"

git config --local user.email "action@github.com"
git config --local user.name "GitHub Action"

for i in 1 2 3 4; do
  git fetch -q origin "$BRANCH" || { sleep $((i * 5)); continue; }
  git reset -q --hard "origin/$BRANCH"    # 추적 파일만 되돌린다 (data/state.json 등 .gitignore 대상은 유지)

  python src/generate_dashboard_data.py --sync-thresholds || exit 1

  if git diff --quiet -- docs/data/history.json; then
    echo "대시보드 임계값이 이미 stock.txt 와 일치합니다."
    exit 0
  fi

  git add docs/data/history.json
  git commit -q -m "$MSG"
  if git push -q origin "HEAD:$BRANCH"; then
    echo "대시보드 임계값 동기화 push 완료 (시도 $i)"
    exit 0
  fi
  echo "push 경쟁으로 거절됨 — 최신 상태에서 다시 시도합니다 ($i/4)" >&2
  sleep $((i * 5))
done

echo "대시보드 임계값 동기화 push 실패" >&2
exit 1
