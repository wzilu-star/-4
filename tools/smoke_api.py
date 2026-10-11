# -*- coding: utf-8 -*-
"""打靶：按老师的检查方式调一遍 API（/health、无 key 401、带 key /judge）。

用法：
  python -I tools/smoke_api.py --url http://127.0.0.1:8000 --limit 3 [--key xxx]
  不传 --key 时从 .env 读 JUDGE_API_KEY
"""
import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def read_key():
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line.startswith("JUDGE_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8")


def post(url, payload, headers=None, timeout=150):
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers=dict({"content-type": "application/json"}, **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--key", default="")
    ap.add_argument("--cases", default=os.path.join(ROOT, "index", "holdout_cases.jsonl"))
    ap.add_argument("--limit", type=int, default=3)
    a = ap.parse_args()

    key = a.key or read_key()
    url = a.url.rstrip("/")
    print("目标: %s   key: %s…" % (url, key[:4]))

    # 1) /health
    try:
        st, body = get(url + "/health", timeout=40)
        print("[1] GET /health -> %s %s  %s" % (st, body.strip(), "✅" if st == 200 and '"ok"' in body else "❌"))
    except Exception as e:  # noqa: BLE001
        print("[1] GET /health -> 失败 %r  ❌" % e)
        return

    # 2) 不带 key
    try:
        st, _ = post(url + "/judge", {"case_text": "原告与被告因合同产生纠纷。"}, timeout=40)
        print("[2] 无 key POST /judge -> %s  %s" % (st, "❌ 竟然放行了" if st != 401 else "✅ 正确拒绝"))
    except urllib.error.HTTPError as e:
        print("[2] 无 key POST /judge -> %s  %s" % (e.code, "✅ 正确拒绝" if e.code == 401 else "❌"))
    except Exception as e:  # noqa: BLE001
        print("[2] 无 key POST /judge -> 失败 %r  ❌" % e)
        return

    # 3) 带 key 逐件
    rows = [json.loads(l) for l in open(a.cases, encoding="utf-8") if l.strip()][: a.limit]
    ok = 0
    for i, r in enumerate(rows, 1):
        t0 = time.time()
        try:
            st, body = post(url + "/judge", {"case_text": r["case_text"]},
                            headers={"authorization": "Bearer " + key}, timeout=150)
            dt = time.time() - t0
            d = json.loads(body)
            four = all(d.get(k) for k in ("cause", "laws", "direction", "verdict"))
            ok += 1 if four else 0
            print("\n[3.%d] %s  %.1fs  %s" % (i, r["id"], dt, "✅四项齐全" if four else "❌缺项"))
            print("   案由: %s   (真实: %s)" % (d.get("cause"), r["cause"]))
            print("   方向: %s   (真实: %s)" % (d.get("direction"), r["direction"]))
            print("   法条: %s" % "；".join(d.get("laws") or []))
            print("   主文: %s" % (d.get("verdict") or "")[:200])
        except urllib.error.HTTPError as e:
            print("\n[3.%d] %s  HTTP %s %s" % (i, r["id"], e.code, e.read()[:200]))
        except Exception as e:  # noqa: BLE001
            print("\n[3.%d] %s  失败 %.1fs %r" % (i, r["id"], time.time() - t0, e))

    print("\n小结: %d/%d 件四项齐全" % (ok, len(rows)))


if __name__ == "__main__":
    main()
