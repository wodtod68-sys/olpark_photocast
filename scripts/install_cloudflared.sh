#!/usr/bin/env bash
# Cloudflare 공식 릴리스에서 cloudflared를 scripts/bin/ 에 받는다 (brew 없이). scripts/bin/은 커밋하지 않는다.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p bin
case "$(uname -m)" in
  arm64) F=cloudflared-darwin-arm64.tgz ;;
  *) F=cloudflared-darwin-amd64.tgz ;;
esac
curl -fsSL -o "bin/$F" "https://github.com/cloudflare/cloudflared/releases/latest/download/$F"
tar -xzf "bin/$F" -C bin && rm "bin/$F"
chmod +x bin/cloudflared
bin/cloudflared --version
