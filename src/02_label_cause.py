# -*- coding: utf-8 -*-
"""给正则抽不出案由的少量文书用大模型补标，并就地更新 corpus.jsonl。

用法：python -I src/02_label_cause.py --corpus data/corpus.jsonl [--limit N]
"""
import argparse
import collections
import io
import json
import os
import sys
import shutil
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm  # noqa: E402
from common import extract_cause, normalize_cause  # noqa: E402

SYS = "你是中国民事判决书案由标注助手。只输出 JSON，不要解释。"

PROMPT = """下面是一份民事一审判决书的开头部分（当事人、诉讼请求、事实与证据）。

请判断本案的案由，写标准名称，例如「民间借贷纠纷」「物业服务合同纠纷」「机动车交通事故责任纠纷」。

案情：
%s

只输出 JSON：{"cause": "案由名称"}"""


def label(row):
    seg = row["case_text"][:2200]
    try:
        txt = llm.chat(PROMPT % seg, system=SYS, max_tokens=2500, timeout=90)
        d = llm.extract_json(txt) or {}
        c = normalize_cause((d.get("cause") or "").strip())
        if not c:
            # 模型给的写法不在标准表里，退回正则看「本院认为」段
            c, _, _ = extract_cause(row["case_text"], row.get("cite", ""))
        return row["id"], c
    except Exception as e:  # noqa: BLE001
        return row["id"], ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(a.corpus, encoding="utf-8") if l.strip()]
    todo = [r for r in rows if not r["cause"]]
    if a.limit:
        todo = todo[: a.limit]
    print("待补标: %d" % len(todo))

    if todo:
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            got = dict(ex.map(label, todo))
        for r in rows:
            if not r["cause"] and got.get(r["id"]):
                r["cause"] = got[r["id"]]
                r["cause_source"] = "llm"
        shutil.copy(a.corpus, a.corpus + ".bak")
        with open(a.corpus, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    miss = [r["id"] for r in rows if not r["cause"]]
    out.write("补标后仍缺: %d %s\n" % (len(miss), miss[:20]))
    out.write("案由来源: %s\n" % dict(collections.Counter(r["cause_source"].split("_")[0] for r in rows)))
    out.write("不同案由: %d\n" % len(set(r["cause"] for r in rows if r["cause"])))
    out.flush()


if __name__ == "__main__":
    main()
