#!/usr/bin/env bash
# 실험실을 이 맥에서 띄우고 Cloudflare quick tunnel로 친구가 접속할 주소를 만든다.
#   bash scripts/start_lab.sh            (끄기: Ctrl+C — 주소도 사라지고, 다음에 켜면 주소가 바뀐다)
# - caffeinate로 감싸 실행 중에는 맥이 잠들지 않는다(전원 연결 권장).
# - 실험실은 비밀번호(LAB_PASSCODE)가 있어야 들어갈 수 있다. API 키는 이 맥의 server/.env에만 있다.
# - 터널이 열려 있는 동안 공개 화면의 생성도 인터넷에 열리므로 공개 화면 하루 한도를 기본 10장으로 낮춘다
#   (바꾸려면 DAILY_LIMIT=20 bash scripts/start_lab.sh).
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8000}"
CF="$(command -v cloudflared || echo scripts/bin/cloudflared)"
[ -x "$CF" ] || { echo "cloudflared가 없어요: bash scripts/install_cloudflared.sh"; exit 1; }
[ -f server/.env ] || { echo "server/.env가 없어요 (LAB_GUIDE.md 0번 참고)"; exit 1; }
grep -q '^LAB_PASSCODE=..*' server/.env || { echo "server/.env에 LAB_PASSCODE가 있어야 해요"; exit 1; }
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "포트 $PORT를 이미 쓰고 있어요. 떠 있는 서버를 끄거나 PORT=8010 bash scripts/start_lab.sh 처럼 실행하세요."; exit 1
fi
export DAILY_LIMIT="${DAILY_LIMIT:-10}"
LOG=server/lab_data/logs
mkdir -p "$LOG"
SRV=""; TUN=""
trap '[ -n "$TUN" ] && kill $TUN 2>/dev/null; [ -n "$SRV" ] && kill $SRV 2>/dev/null; echo; echo "꺼졌어요"' EXIT INT TERM

echo "[1/3] 화면 빌드 (npm run build)"
npm run build >"$LOG/build.log" 2>&1 || { echo "빌드 실패: $LOG/build.log"; exit 1; }

echo "[2/3] 서버 시작 :$PORT (로그 $LOG/server.log)"
caffeinate -dimsu server/.venv/bin/uvicorn server.app:app --host 127.0.0.1 --port "$PORT" >"$LOG/server.log" 2>&1 &
SRV=$!
for _ in $(seq 40); do curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break; sleep 1; done
curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null || { echo "서버가 안 떠요: $LOG/server.log"; exit 1; }

echo "[3/3] 터널 여는 중 (로그 $LOG/tunnel.log)"
"$CF" tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" >"$LOG/tunnel.log" 2>&1 &
TUN=$!
URL=""
for _ in $(seq 60); do
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG/tunnel.log" | head -1 || true)
  [ -n "$URL" ] && break; sleep 1
done
[ -n "$URL" ] || { echo "터널 주소를 못 받았어요: $LOG/tunnel.log"; exit 1; }
echo
echo "  실험실(친구에게 보낼 주소):  $URL/#/lab"
echo "  공개 화면:                   $URL"
echo "  비밀번호는 server/.env 의 LAB_PASSCODE — 주소와 따로 보내세요."
echo
echo "  이 창을 닫거나 Ctrl+C를 누르면 꺼져요."
wait "$SRV"
