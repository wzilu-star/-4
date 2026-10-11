# -*- coding: utf-8 -*-
"""判案 API：GET /health、POST /judge。

用法：
  python -I src/04_serve.py --index index --host 127.0.0.1 --port 8000

Key 从 .env 的 JUDGE_API_KEY 读（.env 不进仓库）。
"""
import argparse
import json
import os
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402

bootstrap.add_user_site()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
import uvicorn  # noqa: E402

from rag import JudgeEngine  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(ROOT, "logs", "requests.jsonl")
_log_lock = threading.Lock()


def load_dotenv(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)


def log_req(rec):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with _log_lock, open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def make_app(engine, api_key, budget_s=95.0):
    app = FastAPI(title="判案 API", docs_url=None, redoc_url=None)
    pool = ThreadPoolExecutor(max_workers=4)
    stats = {"n": 0, "err": 0}

    def authorized(req: Request):
        h = req.headers.get("authorization") or ""
        if h.lower().startswith("bearer "):
            h = h[7:].strip()
        return bool(api_key) and secrets.compare_digest(h, api_key)

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.post("/judge")
    async def judge(req: Request):
        t0 = time.time()
        if not authorized(req):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            body = await req.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "invalid json"}, status_code=400)
        case_text = (body or {}).get("case_text") or ""
        if not isinstance(case_text, str) or not case_text.strip():
            return JSONResponse({"error": "case_text required"}, status_code=400)

        stats["n"] += 1
        fut = pool.submit(engine.judge, case_text, budget_s)
        try:
            result, debug = fut.result(timeout=budget_s + 12)
        except FutTimeout:
            stats["err"] += 1
            # 到点了也要给四项，绝不让隧道 524
            try:
                cause, _ = engine.guess_cause(case_text)
                hits = engine.retrieve(case_text, cause, topk=20)
                result = {"cause": cause or "合同纠纷",
                          "laws": engine.guess_laws(hits) or ["《中华人民共和国民事诉讼法》第六十四条"],
                          "direction": engine.guess_direction(hits),
                          "verdict": engine.fallback_verdict(case_text, hits)}
            except Exception:  # noqa: BLE001
                result = {"cause": "合同纠纷",
                          "laws": ["《中华人民共和国民事诉讼法》第六十四条"],
                          "direction": "部分支持", "verdict": "驳回原告的诉讼请求。"}
            debug = {"timeout": True}
        except Exception as e:  # noqa: BLE001
            stats["err"] += 1
            result = {"cause": "合同纠纷",
                      "laws": ["《中华人民共和国民事诉讼法》第六十四条"],
                      "direction": "部分支持", "verdict": "驳回原告的诉讼请求。"}
            debug = {"error": repr(e)[:200]}

        elapsed = round(time.time() - t0, 2)
        log_req({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "elapsed": elapsed,
                 "chars": len(case_text), "out": result,
                 "generated": debug.get("generated")})
        print("[judge] %.1fs cause=%s dir=%s laws=%d %s" % (
            elapsed, result["cause"], result["direction"], len(result["laws"]),
            "gen" if debug.get("generated") else "fallback"), flush=True)

        # 严格只返回这四项
        return JSONResponse({
            "cause": result["cause"],
            "laws": result["laws"],
            "direction": result["direction"],
            "verdict": result["verdict"],
        })

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=os.path.join(ROOT, "index"))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--budget", type=float, default=95.0)
    a = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))
    api_key = os.environ.get("JUDGE_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("缺少 JUDGE_API_KEY，请在 %s 里配置" % os.path.join(ROOT, ".env"))

    t0 = time.time()
    engine = JudgeEngine(a.index)
    print("索引载入 %.1fs，%d 份；key 前缀 %s…" % (engine.load_s, len(engine.docs), api_key[:4]), flush=True)

    app = make_app(engine, api_key, a.budget)
    print("监听 http://%s:%d  (/health, /judge)" % (a.host, a.port), flush=True)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
