# -*- coding: utf-8 -*-
"""试哪些模型名 / 参数组合能在不吐 thinking 的情况下正常返回。"""
import io, json, os, sys, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import llm

base, key, _, _ = llm.cfg()

LONG = ("〔本案案情〕" + "原告张某与被告李某因物业服务合同产生纠纷，原告主张被告拖欠2015年至2018年物业费共计12000元。" * 60 +
        "〔要求〕只输出 JSON：{\"verdict\": \"一、被告于本判决生效之日起十日内支付原告物业管理费12000元。\"}")

CASES = [
    ("deepseek-flash", {"max_tokens": 4000}),
    ("deepseek-chat", {"max_tokens": 4000}),
    ("deepseek-flash", {"max_tokens": 4000, "thinking": {"type": "disabled"}}),
    ("deepseek-chat", {"max_tokens": 1500}),
    ("deepseek-reasoner", {"max_tokens": 1500}),
]

for model, extra in CASES:
    body = {"model": model, "messages": [{"role": "user", "content": LONG}]}
    body.update(extra)
    req = urllib.request.Request(base + "/v1/messages", data=json.dumps(body, ensure_ascii=False).encode(),
                                 headers={"content-type": "application/json", "x-api-key": key,
                                          "anthropic-version": "2023-06-01"})
    t0 = time.time()
    tag = "%s %s" % (model, extra)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode())
        blocks = [(b.get("type"), len(b.get("text") or b.get("thinking") or "")) for b in d.get("content") or []]
        print("%-58s OK %.1fs stop=%s usage=%s blocks=%s" % (
            tag, time.time() - t0, d.get("stop_reason"), d.get("usage", {}).get("output_tokens"), blocks))
    except Exception as e:
        msg = ""
        if hasattr(e, "read"):
            try:
                msg = e.read().decode()[:200]
            except Exception:
                pass
        print("%-58s FAIL %.1fs %r %s" % (tag, time.time() - t0, e, msg))
