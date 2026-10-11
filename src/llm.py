# -*- coding: utf-8 -*-
"""大模型调用（只用标准库，方便在 Colab / 本地都能跑）。

环境变量：
  LLM_BASE_URL 或 ANTHROPIC_BASE_URL   例如 https://api.deepseek.com/anthropic
  LLM_API_KEY  或 ANTHROPIC_API_KEY
  LLM_MODEL    或 ANTHROPIC_MODEL      例如 deepseek-flash / deepseek-chat
  LLM_KIND     anthropic | openai      默认按 base_url 猜
"""
import json
import os
import re
import time
import urllib.error
import urllib.request


def cfg():
    base = (os.environ.get("LLM_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
    key = os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or ""
    model = os.environ.get("LLM_MODEL") or os.environ.get("ANTHROPIC_MODEL") or "deepseek-chat"
    kind = os.environ.get("LLM_KIND") or ("anthropic" if "anthropic" in base else "openai")
    return base, key, model, kind


def available():
    base, key, _, _ = cfg()
    return bool(base and key)


def thinking_enabled():
    return (os.environ.get("LLM_THINKING") or "").strip().lower() in ("1", "on", "true", "yes")


def chat(prompt, system=None, max_tokens=1600, timeout=90, retries=1, temperature=None):
    """返回模型输出的纯文本；失败抛异常。

    默认关掉「思考链」：这个端点默认先吐一大段 thinking，
    长案情下会把 max_tokens 吃光导致只剩 thinking 块、没有正文。
    需要思考链时设 LLM_THINKING=1。
    """
    base, key, model, kind = cfg()
    if not base or not key:
        raise RuntimeError("LLM 未配置（缺 LLM_BASE_URL / LLM_API_KEY）")

    if kind == "anthropic":
        url = base + "/v1/messages"
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system
        if temperature is not None:
            body["temperature"] = temperature
        if not thinking_enabled():
            body["thinking"] = {"type": "disabled"}
        headers = {"content-type": "application/json", "x-api-key": key,
                   "anthropic-version": "2023-06-01"}
    else:
        url = base + "/chat/completions"
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        body = {"model": model, "max_tokens": max_tokens, "messages": msgs}
        if temperature is not None:
            body["temperature"] = temperature
        headers = {"content-type": "application/json", "authorization": "Bearer " + key}

    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
            return _text_of(d, kind)
        except Exception as e:  # noqa: BLE001
            last = e
            # 有的部署不认 thinking 字段：去掉再试一次
            if body.pop("thinking", None) is not None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                continue
            if i < retries:
                time.sleep(1.5)
    raise last


def _text_of(d, kind):
    if kind == "anthropic":
        blocks = d.get("content") or []
        parts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        txt = "".join(parts).strip()
        if not txt:
            # 这个端点在生成前会先吐 thinking 块；max_tokens 太小会把预算吃光，
            # 只留下 thinking 没有 text。抛错让上层重试/兜底，别返回空串。
            stop = d.get("stop_reason")
            raise RuntimeError("模型未返回文本块(stop_reason=%s)，多半是 max_tokens 不够" % stop)
        return txt
    ch = (d.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    txt = msg.get("content") or ch.get("text") or ""
    if isinstance(txt, list):
        txt = "".join(p.get("text", "") for p in txt if isinstance(p, dict))
    return (txt or "").strip()


RE_JSON = re.compile(r"\{.*\}", re.S)


def extract_json(text):
    """从模型输出里抠出第一个 JSON 对象。"""
    if not text:
        return None
    m = RE_JSON.search(text)
    if not m:
        return None
    s = m.group(0)
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        pass
    # 试着截到最后一个 }
    for end in range(len(s), 0, -1):
        if s[end - 1] == "}":
            try:
                return json.loads(s[:end])
            except Exception:  # noqa: BLE001
                continue
    return None
