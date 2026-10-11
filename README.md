# 判案 API —— 用 3,520 份民事一审判决书做一个判案服务

输入一份判决书「本院认为」**之前**的部分（法院、案号、当事人、诉讼请求、事实与证据），
返回四项：**案由 / 适用法条 / 判决方向 / 判决主文**。

---

## 一、方法（一句话）

3,520 份判决书**没有任何标注**，但每份都自带答案。所以：

1. **离线切分**：判决书 100% 含「本院认为」，按它把文书切成「案情」（输入）和「答案」（输出）。
2. **离线抽标签**：从「答案」一侧抽出四类结构化字段——
   - **案由**：正则匹配 → 对标准案由表做最长后缀归一（覆盖 95.8%），剩下 149 份用大模型补标；
   - **法条**：抓「依照……之规定，判决如下」这句里的引用，只保留《全称》第 X 条；
   - **判决方向**：把「判决如下」之后的主文切成条款，剔除诉讼费负担条和「加倍支付迟延履行期间债务利息」这类套话，按「只有驳回条→驳回 / 只有支持条→支持 / 两者都有→部分支持」判定；
   - **判决主文**：切到上诉指引/落款之前。
3. **服务时**：用 BM25（jieba + 法律自定义词典）拿本案案情检索同类已判案例
   （**先按案由圈定检索范围**，案由相同时才在全库兜底），
   统计出候选法条与方向分布，把这些类案连同本案案情交给 DeepSeek 生成四项结果。

```
            离线（一次性）                                在线（每次请求）
  judgments.jsonl
        │
        ├─ 按「本院认为」切分 ──► 案情 / 答案
        │                              │
        │                       抽案由·法条·方向·主文
        │                              │
        └──────────────────────► corpus.jsonl
                                       │
                                 jieba 分词 + BM25
                                       │
                                       ▼
   案情 ──► 案由识别 ──► 同案由内 BM25 检索 top-20 ──► 方向投票 / 法条候选
                                       │
                                       ▼
                        DeepSeek 参照类案按本案事实生成四项
                                       │
                          失败/超时 ──► 规则+最近邻主文改写兜底
```

**为什么要兜底**：Cloudflare 免费隧道单次请求超过约 2 分钟会断（524），
所以整条链路有硬预算（默认 95 秒，LLM 调用超时更短），
任何异常都退回「规则 + 最近邻主文改写」，保证**四项永远非空**。

---

## 二、接口

| | |
|---|---|
| `GET /health` | 200 `{"ok": true}`，不需要 key |
| `POST /judge` | 请求头 `Authorization: Bearer <key>`，体 `{"case_text": "..."}` |

返回（**只有这四项**）：

```json
{"cause": "买卖合同纠纷",
 "laws": ["《中华人民共和国合同法》第一百零七条", "《中华人民共和国民事诉讼法》第六十四条"],
 "direction": "部分支持",
 "verdict": "一、被告……；二、驳回原告……的其他诉讼请求。"}
```

`direction` 三选一：`支持` / `部分支持` / `驳回`。
不带 key 或 key 不对返回 **401**。非流式输出。

---

## 三、怎么跑

### 本地（Windows / 任意机器）

```bash
pip install -r requirements.txt

# 1) 建语料（把 judgments.jsonl 的路径换成你自己的）
python -I src/01_build_corpus.py --input <judgments.jsonl> --out data/corpus.jsonl --report
python -I src/02_label_cause.py  --corpus data/corpus.jsonl       # 补标 149 份缺失案由
python -I src/03_build_index.py  --corpus data/corpus.jsonl --out-dir index --holdout 100

# 2) 起服务（key 配在 .env 的 JUDGE_API_KEY）
python -I src/04_serve.py --index index --host 127.0.0.1 --port 8000

# 3) 开公网
cloudflared tunnel --url http://127.0.0.1:8000
```

大模型走环境变量 `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL`
（也可用 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` 覆盖）。
默认**关闭思考链**（`thinking: disabled`）——该端点默认先吐一大段 thinking，
长案情下会把 `max_tokens` 吃光导致只返回 thinking 块、没有正文。需要思考链设 `LLM_THINKING=1`。

### Colab

见 `colab/judge_api_colab.ipynb`（挂 Drive 读判决书 → 拉代码 → 一键脚本建库起服务开隧道）。

---

## 四、自测

`index/holdout.json` 里的 **100 份判决书没有进检索库**，用它们的案情当「新案件」打自己的 API，
模拟老师的测试：

```bash
python -I src/05_eval.py --index index --out eval --limit 100
```

结果见 `eval/results_*.md`（逐题记录：召回了哪些块、答对没有、错在哪）。
打靶脚本 `tools/smoke_api.py` 按老师的方式调一遍（health → 无 key 401 → 带 key 逐件）。

---

## 五、目录

```
case-judge-api/
├─ src/
│  ├─ common.py            切分与抽取规则（案由/法条/方向/主文）
│  ├─ llm.py               大模型调用（只用标准库）
│  ├─ rag.py               BM25 检索 + 生成 + 兜底（核心）
│  ├─ 01_build_corpus.py   切分 + 抽字段
│  ├─ 02_label_cause.py    大模型补标缺失案由
│  ├─ 03_build_index.py    分词 + 建索引 + 留出评测集
│  ├─ 04_serve.py          FastAPI 服务
│  └─ 05_eval.py           自测
├─ tools/                  验证与打靶脚本
├─ colab/                  Colab 部署
├─ data/  index/  logs/    运行产物（不进仓库）
└─ .env                    JUDGE_API_KEY（不进仓库）
```

---

## 六、注意

- `.env`、`data/`、`index/`、`logs/` 都在 `.gitignore` 里；**判决书原文和 key 都不进仓库**。
- 判决书来自中国裁判文书网公开文书，只用于本课作业，**不外传**。
- 本服务是课堂方法演示，输出**不构成法律意见**。
