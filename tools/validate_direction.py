# -*- coding: utf-8 -*-
"""用大模型独立判一次方向，和规则结果比对，看规则准不准。

用法：python -I tools/validate_direction.py --corpus data/corpus.jsonl --per-class 60
"""
import argparse
import collections
import io
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import llm  # noqa: E402

SYS = "你是中国民事判决书分析助手。只输出 JSON，不要任何解释。"

PROMPT = """下面是一份民事一审判决书的判决主文（「判决如下」之后的部分）。

请判断判决方向，三选一：
- 支持：原告的诉讼请求全部得到支持
- 部分支持：支持了一部分，驳回其他诉讼请求
- 驳回：驳回原告全部诉讼请求

注意：诉讼费由谁负担不影响方向判断；「加倍支付迟延履行期间的债务利息」是套话，不影响判断。

判决主文：
%s

只输出 JSON：{"direction": "支持" 或 "部分支持" 或 "驳回"}"""


def judge_one(row):
    try:
        txt = llm.chat(PROMPT % row["verdict"][:1200], system=SYS, max_tokens=2500, timeout=90)
        d = llm.extract_json(txt) or {}
        got = (d.get("direction") or "").strip().strip('"')
        return row, got if got in ("支持", "部分支持", "驳回") else "?"
    except Exception as e:  # noqa: BLE001
        return row, "ERR:" + str(e)[:60]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--per-class", type=int, default=60)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(a.corpus, encoding="utf-8") if l.strip()]
    by = collections.defaultdict(list)
    for r in rows:
        by[r["direction"]].append(r)

    rnd = random.Random(20261011)
    sample = []
    for k, v in by.items():
        rnd.shuffle(v)
        sample += v[: a.per_class]

    with ThreadPoolExecutor(max_workers=8) as ex:
        res = list(ex.map(judge_one, sample))

    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    w = out.write
    conf = collections.Counter()
    bad = []
    for row, got in res:
        conf[(row["direction"], got)] += 1
        if got != row["direction"]:
            bad.append((row, got))

    w("样本 %d\n" % len(res))
    w("规则 vs 模型 混淆矩阵（行=规则，列=模型）:\n")
    w("        %-10s %-10s %-10s %-10s\n" % ("支持", "部分支持", "驳回", "其它"))
    for a_ in ("支持", "部分支持", "驳回"):
        w("%-8s %-10d %-10d %-10d %-10d\n" % (
            a_, conf[(a_, "支持")], conf[(a_, "部分支持")], conf[(a_, "驳回")],
            sum(c for (x, y), c in conf.items() if x == a_ and y not in ("支持", "部分支持", "驳回"))))
    agree = sum(c for (x, y), c in conf.items() if x == y)
    w("一致率: %d/%d = %.1f%%\n" % (agree, len(res), 100.0 * agree / len(res)))
    for a_ in ("支持", "部分支持", "驳回"):
        tot = sum(c for (x, y), c in conf.items() if x == a_)
        ok = conf[(a_, a_)]
        if tot:
            w("  %s 精确率: %.1f%% (%d/%d)\n" % (a_, 100.0 * ok / tot, ok, tot))

    w("\n--- 分歧样例（最多 12 条）---\n")
    for row, got in bad[:12]:
        w("[%s] 规则=%s 模型=%s\n    %s\n\n" % (row["id"], row["direction"], got, row["verdict"][:260]))
    out.flush()

    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump([{"id": r["id"], "rule": r["direction"], "model": g,
                        "verdict": r["verdict"]} for r, g in res],
                      f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
