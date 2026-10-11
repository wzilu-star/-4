# -*- coding: utf-8 -*-
"""把 judgments.jsonl 拆成「案情 / 标准答案」并抽结构化字段。

用法：
  python -I src/01_build_corpus.py --input <judgments.jsonl> --out <corpus.jsonl> [--report]
"""
import argparse
import collections
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (  # noqa: E402
    split_case, verdict_of, extract_cause, extract_laws, extract_basis_laws,
    classify_direction, extract_parties,
)


def build_one(rec):
    text = rec["text"]
    case_text, tail = split_case(text)
    verdict = verdict_of(text)
    cause, cause_raw, cause_src = extract_cause(case_text, tail)
    laws = extract_basis_laws(text)
    laws_all = extract_laws(tail)
    direction = classify_direction(verdict)
    return {
        "id": rec["id"],
        "cause": cause,
        "cause_raw": cause_raw,
        "cause_source": cause_src,
        "laws": laws,
        "laws_all": laws_all,
        "direction": direction,
        "verdict": verdict,
        "case_text": case_text,
        "chars": len(text),
        "verdict_chars": len(verdict),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    rows = []
    with open(a.input, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(build_one(json.loads(line)))

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    if a.report:
        out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        n = len(rows)
        w = out.write
        w("总数 %d\n" % n)
        w("无 verdict: %d\n" % sum(1 for r in rows if not r["verdict"]))
        w("无 cause : %d\n" % sum(1 for r in rows if not r["cause"]))
        w("无 laws  : %d\n" % sum(1 for r in rows if not r["laws"]))
        w("方向分布 : %s\n" % dict(collections.Counter(r["direction"] for r in rows)))
        w("案由来源 : %s\n" % dict(collections.Counter(r["cause_source"].split("_")[0] for r in rows)))
        cc = collections.Counter(r["cause"] for r in rows if r["cause"])
        w("不同案由 : %d\n" % len(cc))
        w("Top25 案由:\n")
        for k, v in cc.most_common(25):
            w("   %-26s %d\n" % (k, v))
        w("单例案由数: %d\n" % sum(1 for v in cc.values() if v == 1))
        w("verdict 长度 中位: %d\n" % sorted(r["verdict_chars"] for r in rows)[n // 2])
        w("\n--- 方向=驳回 的样例主文 ---\n")
        for r in [x for x in rows if x["direction"] == "驳回"][:5]:
            w("%s: %s\n\n" % (r["id"], r["verdict"][:200]))
        w("--- 无案由样例 id ---\n")
        w(str([r["id"] for r in rows if not r["cause"]][:40]) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
