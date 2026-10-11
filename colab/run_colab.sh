#!/usr/bin/env bash
# Colab / 任意 Linux 上一键：装依赖 → 建库 → 起 API → 开 Cloudflare 隧道 → 打印公网地址
#
# 用法：
#   JUDGMENTS=/content/case-judge-api/judge_data/judgments.jsonl bash colab/run_colab.sh
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs data index

JUDGMENTS="${JUDGMENTS:-$ROOT/judge_data/judgments.jsonl}"
PORT="${PORT:-8000}"

echo "== 1/5 安装依赖 =="
pip -q install -r requirements.txt

echo "== 2/5 准备 cloudflared =="
if ! command -v cloudflared >/dev/null 2>&1; then
  wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
       -O /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared
fi
cloudflared --version || { echo "cloudflared 安装失败"; exit 1; }

echo "== 3/5 建库与索引（已存在则跳过）=="
if [ ! -f "$ROOT/index/tokens.pkl" ]; then
  [ -f "$JUDGMENTS" ] || { echo "找不到判决书：$JUDGMENTS"; exit 1; }
  python -I src/01_build_corpus.py --input "$JUDGMENTS" --out data/corpus.jsonl
  python -I src/02_label_cause.py  --corpus data/corpus.jsonl
  python -I src/03_build_index.py  --corpus data/corpus.jsonl --out-dir index --holdout 100
else
  echo "索引已存在，跳过"
fi

echo "== 4/5 启动 API =="
pkill -f "04_serve.py" 2>/dev/null || true
nohup python -I src/04_serve.py --index index --host 127.0.0.1 --port "$PORT" > logs/server.log 2>&1 &
for i in $(seq 1 30); do
  sleep 1
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then break; fi
done
echo -n "本地 /health: "; curl -sS "http://127.0.0.1:$PORT/health"; echo

echo "== 5/5 启动 Cloudflare 隧道 =="
pkill -f "cloudflared tunnel" 2>/dev/null || true
nohup cloudflared tunnel --url "http://127.0.0.1:$PORT" --protocol http2 > logs/tunnel.log 2>&1 &
for i in $(seq 1 40); do
  sleep 2
  URL="$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' logs/tunnel.log | head -1)"
  [ -n "$URL" ] && break
done

if [ -n "${URL:-}" ]; then
  echo
  echo "======================================================"
  echo " 公网地址: $URL"
  echo " Key     : $(grep JUDGE_API_KEY .env | cut -d= -f2)"
  echo "======================================================"
  echo "浏览器打开 $URL/health 应看到 {\"ok\":true}"
else
  echo "隧道地址没拿到，看 logs/tunnel.log"
  tail -20 logs/tunnel.log
fi
