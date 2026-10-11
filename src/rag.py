# -*- coding: utf-8 -*-
"""判案核心：案情 → 案由 / 法条 / 判决方向 / 判决主文。

思路：这批判决书没有标注，所以先离线把 3,520 份拆成
「案情(本院认为之前)」和「答案(本院认为之后)」，
服务时用案情去检索同类已判案例，把它们的结果当依据，
再让大模型按本案事实改写；大模型不可用时退回规则/模板，保证四项都有。
"""
import collections
import json
import math
import os
import pickle
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bootstrap  # noqa: E402

bootstrap.add_user_site()
import jieba  # noqa: E402

from common import (  # noqa: E402
    extract_cause, extract_laws, extract_basis_laws, classify_direction,
    extract_parties, RE_AMOUNT,
)
import llm  # noqa: E402

K1, B = 1.5, 0.75
DIRECTIONS = ("支持", "部分支持", "驳回")

# 案情里最有信息量的部分从这些词开始，前面的法院/案号/当事人是噪声
RE_FOCUS = re.compile(r"(原告诉称|原告向本院提出诉讼请求|诉讼请求|原告请求|起诉称|诉称)")
RE_CASE_NO = re.compile(r"[（(]\d{4}[）)][^号\n]{0,20}号")
RE_COURT = re.compile(r"[一-龥]{2,20}(?:人民法院|法院)")


class BM25:
    def __init__(self, token_lists):
        self.n = len(token_lists)
        self.doc_len = [len(t) for t in token_lists]
        self.avgdl = (sum(self.doc_len) / self.n) if self.n else 0.0
        postings = collections.defaultdict(list)
        for i, toks in enumerate(token_lists):
            tf = collections.Counter(toks)
            for w, c in tf.items():
                postings[w].append((i, c))
        self.postings = postings
        self.idf = {w: math.log(1 + (self.n - len(ps) + 0.5) / (len(ps) + 0.5))
                    for w, ps in postings.items()}

    def search(self, query_tokens, allowed=None, topk=20, exclude=()):
        """allowed: 只在这些 doc 下标里检索（None = 全部）。"""
        scores = collections.defaultdict(float)
        ex = set(exclude)
        for w in set(query_tokens):
            ps = self.postings.get(w)
            if not ps:
                continue
            idf = self.idf[w]
            for i, tf in ps:
                if i in ex or (allowed is not None and i not in allowed):
                    continue
                dl = self.doc_len[i]
                scores[i] += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * dl / self.avgdl))
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:topk]
        return ranked


def focus_text(case_text, limit=1600):
    """截掉法院/案号/当事人抬头，从「诉称/诉讼请求」开始取。"""
    m = RE_FOCUS.search(case_text)
    seg = case_text[m.start():] if m else case_text
    return seg[:limit]


class JudgeEngine:
    def __init__(self, index_dir):
        t0 = time.time()
        with open(os.path.join(index_dir, "docs.json"), encoding="utf-8") as f:
            self.docs = json.load(f)
        with open(os.path.join(index_dir, "tokens.pkl"), "rb") as f:
            tokens = pickle.load(f)
        self.bm25 = BM25(tokens)
        self.by_cause = collections.defaultdict(list)
        for i, d in enumerate(self.docs):
            self.by_cause[d["cause"]].append(i)
        self.load_s = time.time() - t0

    # ---------------------------------------------------------- 检索
    def retrieve(self, case_text, cause, topk=20):
        q = [w for w in jieba.cut(focus_text(case_text)) if len(w.strip()) > 1]
        allowed = set(self.by_cause.get(cause, [])) if cause else None
        hits = self.bm25.search(q, allowed=allowed, topk=topk)
        if len(hits) < 5:
            # 同案由样本太少 → 退回全库检索
            hits = self.bm25.search(q, allowed=None, topk=topk)
        return hits

    # ---------------------------------------------------------- 案由
    def guess_cause(self, case_text):
        c, raw, src = extract_cause(case_text, "")
        if c:
            return c, "rule"
        q = [w for w in jieba.cut(focus_text(case_text, 900)) if len(w.strip()) > 1]
        hits = self.bm25.search(q, topk=25)
        vote = collections.Counter()
        for i, s in hits:
            vote[self.docs[i]["cause"]] += s
        if vote:
            return vote.most_common(1)[0][0], "vote"
        return "", "none"

    # ---------------------------------------------------------- 法条
    def guess_laws(self, hits, n_ctx=15):
        """从近邻的判决依据里取高频法条（法条以判决书引用的为准）。"""
        cnt = collections.Counter()
        wsum = collections.Counter()
        seen = 0
        for i, s in hits[:n_ctx]:
            laws = self.docs[i]["laws"]
            if not laws:
                continue
            seen += 1
            for l in set(laws):
                cnt[l] += 1
                wsum[l] += s
        if not seen:
            return []
        thresh = max(2, int(seen * 0.25))
        picked = [l for l, c in cnt.most_common() if c >= thresh][:8]
        if len(picked) < 2:
            picked = [l for l, _ in cnt.most_common(5)]
        return picked

    def guess_direction(self, hits, n_ctx=15):
        vote = collections.Counter()
        for i, s in hits[:n_ctx]:
            vote[self.docs[i]["direction"]] += s
        if not vote:
            return "部分支持"
        return vote.most_common(1)[0][0]

    # ---------------------------------------------------------- 主文兜底
    def fallback_verdict(self, case_text, hits):
        """大模型不可用时：拿最相似一份的主文，换成本案当事人。"""
        if not hits:
            return "驳回原告的诉讼请求。"
        v = self.docs[hits[0][0]]["verdict"]
        if not v:
            return "驳回原告的诉讼请求。"
        src_brief = self.docs[hits[0][0]]["brief"]
        src_names = extract_parties(src_brief)
        dst_names = extract_parties(case_text)
        for old, new in zip(src_names, dst_names):
            if old and new and old != new:
                v = v.replace(old, new)
        return v

    # ---------------------------------------------------------- 主流程
    def judge(self, case_text, budget_s=95.0):
        t0 = time.time()
        debug = {"steps": []}

        cause, cause_src = self.guess_cause(case_text)
        debug["cause_source"] = cause_src

        hits = self.retrieve(case_text, cause, topk=20)
        debug["retrieved"] = [
            {"id": self.docs[i]["id"], "cause": self.docs[i]["cause"],
             "score": round(s, 2), "direction": self.docs[i]["direction"]}
            for i, s in hits[:10]
        ]
        if not cause and hits:
            cause = self.docs[hits[0][0]]["cause"]
            debug["cause_source"] = "top1"

        laws = self.guess_laws(hits)
        direction = self.guess_direction(hits)
        debug["rule_laws"] = laws
        debug["rule_direction"] = direction

        result = {"cause": cause, "laws": laws, "direction": direction, "verdict": ""}

        if llm.available():
            try:
                gen = self.generate(case_text, cause, laws, direction, hits,
                                    timeout=max(20.0, budget_s - (time.time() - t0) - 8))
                if gen:
                    for k in ("cause", "laws", "direction", "verdict"):
                        v = gen.get(k)
                        if k == "laws":
                            if isinstance(v, list) and v:
                                result["laws"] = [str(x).strip() for x in v if str(x).strip()][:8]
                        elif isinstance(v, str) and v.strip():
                            result[k] = v.strip()
                    debug["generated"] = True
            except Exception as e:  # noqa: BLE001
                debug["llm_error"] = repr(e)[:200]

        if not result["verdict"]:
            result["verdict"] = self.fallback_verdict(case_text, hits)
            debug["generated"] = False

        # 兜底补齐
        if not result["cause"]:
            result["cause"] = cause or "合同纠纷"
        if not result["laws"]:
            result["laws"] = laws or ["《中华人民共和国民事诉讼法》第六十四条"]
        if result["direction"] not in DIRECTIONS:
            result["direction"] = direction if direction in DIRECTIONS else "部分支持"
        result["laws"] = [l if re.match(r"^《.+》第.+条$", l) else l for l in result["laws"]]

        debug["elapsed_s"] = round(time.time() - t0, 2)
        return result, debug

    # ---------------------------------------------------------- 大模型
    def generate(self, case_text, cause, laws, direction, hits, timeout=75.0, n_examples=5):
        # 按方向分组给例子：让模型直接看到「支持/部分支持/驳回」在主文结构上的差别
        groups = {"支持": [], "部分支持": [], "驳回": []}
        for i, s in hits[:12]:
            d = self.docs[i]
            groups[d["direction"]].append(d)
        caption = {
            "支持": "判成「支持」的样子（主文里没有「驳回…诉讼请求」）",
            "部分支持": "判成「部分支持」的样子（主文里有一项「驳回原告的其余（其他）诉讼请求」）",
            "驳回": "判成「驳回」的样子（主文只有「驳回原告…的诉讼请求」）",
        }
        blocks = []
        for k in ("支持", "部分支持", "驳回"):
            for d in groups[k][:2]:
                blocks.append("〔%s〕案由%s；引用法条：%s\n判决主文：%s" % (
                    caption[k], d["cause"], "；".join(d["laws"][:4]) or "（无）", d["verdict"][:380]))
                if len(blocks) >= n_examples:
                    break
            if len(blocks) >= n_examples:
                break
        ex_txt = "\n\n".join(blocks) if blocks else "（无同类案例）"

        laws_txt = "；".join(laws) if laws else "（无）"
        dist = collections.Counter(self.docs[i]["direction"] for i, _ in hits[:15])
        tot = sum(dist.values()) or 1
        dist_txt = "、".join("%s %d/%d" % (k, dist[k], tot) for k in DIRECTIONS if dist[k])
        prompt = PROMPT_TMPL % (
            case_text[:3500], ex_txt,
            cause or "（未知）", dist_txt, laws_txt)

        txt = llm.chat(prompt, system=SYS_PROMPT, max_tokens=4000, timeout=timeout)
        d = llm.extract_json(txt)
        if not d:
            raise RuntimeError("模型输出无法解析为 JSON")
        return d


SYS_PROMPT = (
    "你是中国民事一审法官助理。依据随案检索到的同类判决书，为本案撰写判决结果。"
    "严格按要求输出 JSON，不要输出解释。"
)

PROMPT_TMPL = """下面是本案的案情（一份判决书「本院认为」之前的部分）。

〔本案案情〕
%s

〔检索到的同类案例，已按判决方向分组——请对照它们主文结构的差别，判断本案属于哪一种。
  只参考裁判口径，不要照抄它们的事实、人名和金额〕
%s

〔同类案例的统计参考〕
- 本案案由：%s
- 同类案例里最常见的判决方向：%s
- 同类案例常引用的法条：%s

先判断判决方向，再据此写判决主文，最后输出 JSON。

判决方向的判定标准（严格执行）：
- 支持 = 原告的每一项诉讼请求都得到支持。此时主文里**不得**出现任何「驳回……诉讼请求」的表述。
- 部分支持 = 原告的请求一部分获支持、一部分被驳回。此时主文里必须有一项「驳回原告的其余（其他）诉讼请求」。
- 驳回 = 原告的诉讼请求全部不予支持。此时主文只写「驳回原告……的诉讼请求」。

⚠️ 不要习惯性添加「驳回原告的其他诉讼请求」——只有确实驳回了某项请求才写。
   诉讼费由谁负担与方向无关，别因为诉讼费分摊就判成部分支持。

判决主文的要求：
1. 用本案当事人的真实姓名/名称和本案的真实金额，从案情里取，不得编造案情里没有的数字。
2. 逐项编号「一、二、三、」；涉及给付的写明履行期限；最后写诉讼费由谁负担。
3. 方向与主文必须自洽（支持就不写驳回项，部分支持就必须有驳回项）。

输出 JSON（只输出 JSON，不要 markdown 代码块，不要解释）：

{"cause": "案由标准名称",
 "laws": ["《法律全称》第X条", "..."],
 "direction": "支持 或 部分支持 或 驳回",
 "verdict": "判决主文"}

laws 每条写成《法律全称》第X条，优先从上面「同类案例常引用的法条」里选，最多 6 条。"""
