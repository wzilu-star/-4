# -*- coding: utf-8 -*-
"""用留出的 100 份"新案件"自测：拿案情当输入，比对案由/方向/法条/主文，记录召回与用时。

用法：python -I src/05_eval.py --index index --out eval [--limit 20] [--workers 4] [--no-llm]
"""
import argparse
import collections
import io
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rag import JudgeEngine, DIRECTIONS  # noqa: E402


def law_head(s):
    """法条只比到「第一条」这种粒度，忽略款/项差异。"""
    m = re.match(r"^(《[^》]+》第[一-龥零〇\d]+条)", s)
    return m.group(1) if m else s


def score_one(args):
    engine, row = args
    t0 = time.time()
    res, dbg = engine.judge(row["case_text"])
    return {
        "id": row["id"],
        "gold": {"cause": row["cause"], "direction": row["direction"],
                 "laws": row["laws"], "verdict": row["verdict"]},
        "pred": res,
        "debug": dbg,
        "elapsed": time.time() - t0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="index")
    ap.add_argument("--cases", default="")
    ap.add_argument("--out", default="eval")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()

    if a.no_llm:
        os.environ["LLM_BASE_URL"] = ""
        os.environ["ANTHROPIC_BASE_URL"] = ""

    cases_path = a.cases or os.path.join(a.index, "holdout_cases.jsonl")
    rows = [json.loads(l) for l in open(cases_path, encoding="utf-8") if l.strip()][: a.limit]

    t0 = time.time()
    engine = JudgeEngine(a.index)
    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    out.write("索引载入 %.1fs，%d 份文档；评测 %d 件\n" % (engine.load_s, len(engine.docs), len(rows)))
    out.flush()

    if a.workers > 1:
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            recs = list(ex.map(score_one, [(engine, r) for r in rows]))
    else:
        recs = []
        for i, r in enumerate(rows):
            rec = score_one((engine, r))
            recs.append(rec)
            out.write("  [%d/%d] %s  案由%s 方向%s %s  %.1fs\n" % (
                i + 1, len(rows), rec["id"],
                "✓" if rec["pred"]["cause"] == rec["gold"]["cause"] else "✗",
                "✓" if rec["pred"]["direction"] == rec["gold"]["direction"] else "✗",
                rec["pred"]["direction"], rec["elapsed"]))
            out.flush()

    # ---- 统计 ----
    n = len(recs)
    cause_ok = sum(1 for r in recs if r["pred"]["cause"] == r["gold"]["cause"])
    dir_ok = sum(1 for r in recs if r["pred"]["direction"] == r["gold"]["direction"])
    lat = sorted(r["elapsed"] for r in recs)

    def law_rec(r):
        g = {law_head(x) for x in r["gold"]["laws"]}
        p = {law_head(x) for x in r["pred"]["laws"]}
        return len(g & p) / len(g) if g else 0.0

    def law_prec(r):
        g = {law_head(x) for x in r["gold"]["laws"]}
        p = {law_head(x) for x in r["pred"]["laws"]}
        return len(g & p) / len(p) if p else 0.0

    dirs = collections.Counter((r["gold"]["direction"], r["pred"]["direction"]) for r in recs)

    lines = []
    W = lines.append
    W("# 判案 API 自测报告")
    W("")
    W("- 评测时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    W("- 评测集：留出的 %d 份判决书（**不在**检索库里，模拟老师的新案件）" % n)
    W("- 大模型：%s" % ("启用" if recs and recs[0]["debug"].get("generated") is not None else "关闭"))
    W("")
    W("## 总体")
    W("")
    W("| 指标 | 结果 |")
    W("|---|---|")
    W("| 案由准确率 | %d/%d = **%.1f%%** |" % (cause_ok, n, 100.0 * cause_ok / n))
    W("| 判决方向准确率 | %d/%d = **%.1f%%** |" % (dir_ok, n, 100.0 * dir_ok / n))
    W("| 法条召回率(平均) | **%.1f%%** |" % (100.0 * sum(law_rec(r) for r in recs) / n))
    W("| 法条精确率(平均) | **%.1f%%** |" % (100.0 * sum(law_prec(r) for r in recs) / n))
    W("| 四项齐全率 | %d/%d = %.1f%% |" % (
        sum(1 for r in recs if all(r["pred"][k] for k in ("cause", "laws", "direction", "verdict"))),
        n, 100.0 * sum(1 for r in recs if all(r["pred"][k] for k in ("cause", "laws", "direction", "verdict"))) / n))
    W("| 用时 中位 / 最大 | %.1fs / %.1fs |" % (lat[n // 2], lat[-1]))
    W("")
    W("## 判决方向混淆矩阵（行=真实，列=预测）")
    W("")
    W("| 真实\\预测 | 支持 | 部分支持 | 驳回 |")
    W("|---|---|---|---|")
    for g in DIRECTIONS:
        W("| **%s** | %d | %d | %d |" % (g, dirs[(g, "支持")], dirs[(g, "部分支持")], dirs[(g, "驳回")]))
    W("")
    W("## 逐题记录")
    W("")
    for r in recs:
        p, g = r["pred"], r["gold"]
        W("### %s  (%.1fs)" % (r["id"], r["elapsed"]))
        W("")
        W("- 案由：预测 `%s` / 真实 `%s`  %s" % (p["cause"], g["cause"], "✅" if p["cause"] == g["cause"] else "❌"))
        W("- 方向：预测 `%s` / 真实 `%s`  %s" % (p["direction"], g["direction"], "✅" if p["direction"] == g["direction"] else "❌"))
        W("- 法条：预测 %s" % "；".join(p["laws"]))
        W("- 　　真实 %s" % "；".join(g["laws"]))
        hit = [h for h in r["debug"].get("retrieved", [])[:5]]
        W("- 召回块：%s" % "、".join("%s(%s,%.1f)" % (h["id"], h["direction"], h["score"]) for h in hit))
        W("- 预测主文：%s" % p["verdict"][:220])
        W("- 真实主文：%s" % g["verdict"][:220])
        W("")

    os.makedirs(a.out, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    md = os.path.join(a.out, "results_%s.md" % ts)
    with open(md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(os.path.join(a.out, "results_%s.json" % ts), "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=1)

    out.write("\n".join(lines[:26]) + "\n")
    out.write("\n报告: %s\n总耗时 %.0fs\n" % (md, time.time() - t0))
    out.flush()


if __name__ == "__main__":
    main()
