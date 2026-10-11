# -*- coding: utf-8 -*-
"""建 BM25 索引（jieba 分词 + 自定义法律词典），并留出评测集。

产出 index/ 下：
  docs.json    每份文书的元数据（案由/方向/法条/主文/案情摘要）
  tokens.pkl   每份案情段的分词结果（启动时据此重建倒排索引，秒级）
  holdout.json 留出评测的 id

用法：python -I src/03_build_index.py --corpus data/corpus.jsonl --out-dir index --holdout 100
"""
import argparse
import collections
import io
import json
import os
import pickle
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402

bootstrap.add_user_site()
import jieba  # noqa: E402

LEGAL_WORDS = [
    "物业管理费", "物业服务", "违约金", "诉讼请求", "案件受理费", "受理费", "诉讼费",
    "连带责任", "连带赔偿责任", "机动车交通事故责任强制保险", "交强险", "商业第三者责任险",
    "残疾赔偿金", "精神损害抚慰金", "误工费", "护理费", "抚养费", "赡养费", "扶养费",
    "经济补偿金", "工伤保险", "医疗费", "住院伙食补助费", "营养费", "鉴定费", "保全费",
    "公告费", "反诉", "举证责任", "诉讼时效", "民间借贷", "买卖合同", "劳务关系",
    "劳动关系", "劳务报酬", "借款本金", "借款利息", "逾期利息", "年利率", "月利率",
    "房屋租赁", "土地承包经营权", "继承", "遗嘱", "夫妻共同财产", "子女抚养",
    "交通事故认定书", "责任限额", "赔偿限额", "城镇居民", "农村居民", "可支配收入",
    "法定继承人", "不当得利", "房屋买卖合同", "建设工程施工合同", "追偿权",
]


def load_corpus(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def tokenize(text):
    return [w for w in jieba.cut(text) if w.strip() and len(w.strip()) > 1 and not w.isdigit()]


def make_split(rows, n, seed=20261011):
    """按案由分层抽样，保证评测集覆盖主要案由。"""
    by = collections.defaultdict(list)
    for r in rows:
        by[r["cause"]].append(r["id"])
    rnd = random.Random(seed)
    hold, total = [], len(rows)
    for cause, ids in sorted(by.items(), key=lambda kv: -len(kv[1])):
        rnd.shuffle(ids)
        k = max(1, round(n * len(ids) / total)) if len(ids) >= 8 else 0
        hold += ids[:k]
    hold = sorted(set(hold))[:n]
    return hold


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--holdout", type=int, default=100)
    a = ap.parse_args()

    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    for w in LEGAL_WORDS:
        jieba.add_word(w, freq=10000)

    rows = load_corpus(a.corpus)
    out.write("载入 %d 份\n" % len(rows))

    hold = make_split(rows, a.holdout) if a.holdout else []
    hold_set = set(hold)
    serve = [r for r in rows if r["id"] not in hold_set]

    os.makedirs(a.out_dir, exist_ok=True)

    docs = []
    tokens = []
    for r in serve:
        docs.append({
            "id": r["id"], "cause": r["cause"], "direction": r["direction"],
            "laws": r["laws"], "verdict": r["verdict"],
            "brief": r["case_text"][:420],
        })
        tokens.append(tokenize(r["case_text"]))

    with open(os.path.join(a.out_dir, "docs.json"), "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False)
    with open(os.path.join(a.out_dir, "tokens.pkl"), "wb") as f:
        pickle.dump(tokens, f, protocol=4)
    with open(os.path.join(a.out_dir, "holdout.json"), "w", encoding="utf-8") as f:
        json.dump(hold, f, ensure_ascii=False)

    # 也把留出集的原文单独存一份，评测时当"新案件"用
    hold_rows = [{"id": r["id"], "case_text": r["case_text"], "cause": r["cause"],
                  "direction": r["direction"], "laws": r["laws"], "verdict": r["verdict"]}
                 for r in rows if r["id"] in hold_set]
    with open(os.path.join(a.out_dir, "holdout_cases.jsonl"), "w", encoding="utf-8") as f:
        for r in hold_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    out.write("参与服务 %d 份，留出 %d 份\n" % (len(serve), len(hold)))
    out.write("留出集案由分布: %s\n" % dict(collections.Counter(
        next(r["cause"] for r in rows if r["id"] == i) for i in hold).most_common(12)))
    out.write("平均词数: %.0f\n" % (sum(len(t) for t in tokens) / max(1, len(tokens))))
    out.write("docs.json %.1f MB, tokens.pkl %.1f MB\n" % (
        os.path.getsize(os.path.join(a.out_dir, "docs.json")) / 1e6,
        os.path.getsize(os.path.join(a.out_dir, "tokens.pkl")) / 1e6))
    out.flush()


if __name__ == "__main__":
    main()
