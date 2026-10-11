# -*- coding: utf-8 -*-
"""共用：文本切分、案由/法条/方向/主文抽取规则。

设计要点：这批判决书 100% 含「本院认为」「判决如下」，
所以「输入(案情)」和「答案(本院认为之后)」可以机械切分。
"""
import re
import os

# ---------------------------------------------------------------- 切分

RE_WEIYAN = re.compile(r"本院(?:经审理)?认为")
RE_BOTTOM = re.compile(r"判决如下")


def split_case(text):
    """返回 (case_text, tail)。tail = 本院认为…到文末；case_text = 之前的部分。"""
    m = RE_WEIYAN.search(text)
    if not m:
        return text, ""
    return text[: m.start()], text[m.start():]


def verdict_of(text):
    """取「判决如下」之后的主文，切掉上诉指引/落款/审判人员。"""
    m = RE_BOTTOM.search(text)
    if not m:
        return ""
    tail = text[m.end():]
    # 主文结束标志
    for stop in [
        r"如不服本判决", r"本判决为终审判决", r"如不服本裁定",
        r"审判长", r"审判员", r"代理审判员", r"人民陪审员",
        r"书记员", r"本件与原本核对无异", r"二[〇○零]{1,4}年",
    ]:
        mm = re.search(stop, tail)
        if mm:
            tail = tail[: mm.start()]
    return tail.strip(" \t\r\n：:；;")


# ---------------------------------------------------------------- 案由

# 案由一般出现在「原告X诉被告Y ○○纠纷一案」里；各家法院写法不一，多套模式依次尝试
CAUSE_PATTERNS = [
    re.compile(r"诉[^。；\n]{0,60}?([一-龥]{2,18}纠纷)一案"),
    re.compile(r"与[^。；\n]{0,60}?([一-龥]{2,18}纠纷)一案"),
    re.compile(r"本院(?:经审理)?认为[^。；\n]{0,40}?本案(?:系|为|属)[^。；\n]{0,10}?([一-龥]{2,18}纠纷)"),
    re.compile(r"本案(?:系|为|属)[^。；\n]{0,10}?([一-龥]{2,18}纠纷)"),
    re.compile(r"诉[^。；\n]{0,80}?([一-龥]{2,18}纠纷)"),
    re.compile(r"([一-龥]{2,18}纠纷)一案"),
    re.compile(r"因([一-龥]{2,18}纠纷)"),
]

# 当事人称谓/公司后缀被误吸进来时，从左侧削掉
LEAD_NOISE = [
    re.compile(r"^(?:与)?被告[一-龥A-Za-z0-9（）()·]{0,30}"),
    re.compile(r"^(?:与)?原告[一-龥A-Za-z0-9（）()·]{0,30}"),
    re.compile(r"^(?:与)?第三人[一-龥A-Za-z0-9（）()·]{0,30}"),
    re.compile(r"^[一-龥]{0,8}(?:有限公司|有限责任公司|支公司|公司)"),
]

# 语料里高频的标准案由（用于把「某离婚纠纷」「务者受害责任纠纷」这类噪声归一）
CANON_CAUSES = [
    "物业服务合同纠纷", "机动车交通事故责任纠纷", "金融借款合同纠纷",
    "劳动争议纠纷", "劳动合同纠纷", "买卖合同纠纷", "离婚纠纷",
    "民间借贷纠纷", "提供劳务者受害责任纠纷", "商品房买卖合同纠纷",
    "借款合同纠纷", "房屋买卖合同纠纷", "财产损害赔偿纠纷", "保证合同纠纷",
    "建设工程施工合同纠纷", "生命权、健康权、身体权纠纷", "健康权纠纷",
    "追偿权纠纷", "保险人代位求偿权纠纷", "不当得利纠纷", "租赁合同纠纷",
    "房屋租赁合同纠纷", "土地承包经营权纠纷", "赡养纠纷", "抚养费纠纷",
    "继承纠纷", "所有权确认纠纷", "返还原物纠纷", "排除妨害纠纷",
    "相邻关系纠纷", "承揽合同纠纷", "委托合同纠纷", "合同纠纷",
    "责任保险合同纠纷", "财产保险合同纠纷", "人身保险合同纠纷",
    "确认合同效力纠纷", "债权转让合同纠纷", "服务合同纠纷", "供用热力合同纠纷",
    "供用电合同纠纷", "运输合同纠纷", "定作合同纠纷", "赠与合同纠纷",
    "劳务合同纠纷", "定金合同纠纷", "仓储合同纠纷", "质押合同纠纷",
    "抵押合同纠纷", "农业承包合同纠纷", "种植、养殖回收合同纠纷",
    "侵害商标权纠纷", "侵犯著作权纠纷", "网络服务合同纠纷",
    "义务帮工人受害责任纠纷", "产品责任纠纷", "教育机构责任纠纷",
    "违反安全保障义务责任纠纷", "医疗损害责任纠纷", "环境污染责任纠纷",
    "触电人身损害责任纠纷", "铁路运输人身损害责任纠纷",
    "相邻损害防免关系纠纷", "生命权纠纷", "身体权纠纷", "名誉权纠纷",
    "隐私权纠纷", "肖像权纠纷", "一般人格权纠纷", "婚姻家庭纠纷",
    "婚约财产纠纷", "同居关系子女抚养纠纷", "分家析产纠纷",
    "遗赠扶养协议纠纷", "遗嘱继承纠纷", "法定继承纠纷",
    "被继承人债务清偿纠纷", "执行异议之诉", "案外人执行异议之诉",
    "申请执行人执行异议之诉", "第三人撤销之诉", "公司决议效力确认纠纷",
    "股东资格确认纠纷", "股权转让纠纷", "损害股东利益责任纠纷",
    "损害公司利益责任纠纷", "合伙协议纠纷", "企业承包经营合同纠纷",
]


def _strip_lead(c):
    changed = True
    while changed:
        changed = False
        for p in LEAD_NOISE:
            m = p.match(c)
            if m and m.end() < len(c) - 3 and c[m.end():].endswith("纠纷"):
                c = c[m.end():]
                changed = True
    return c


def normalize_cause(raw):
    """把抽到的案由串归一：去噪声前缀，再对标准案由表做最长后缀匹配。"""
    if not raw:
        return ""
    c = re.sub(r"\s+", "", raw)
    if not c or c == "纠纷":
        return ""
    c = _strip_lead(c)
    if not c.endswith("纠纷"):
        # 模型常只写「劳动争议」这种不带「纠纷」二字的标准案由
        c = c + "纠纷"
    # 完全命中
    if c in CANON_CAUSES:
        return c
    # 最长后缀匹配
    best = ""
    for canon in CANON_CAUSES:
        if c.endswith(canon) and len(canon) > len(best):
            best = canon
    if best:
        return best
    # 前缀匹配（防截断，如「务者受害责任纠纷」→ 提供劳务者受害责任纠纷）
    for canon in CANON_CAUSES:
        if canon.endswith(c) and len(c) >= 4:
            return canon
    return c if len(c) <= 18 else ""


def extract_cause(case_text, tail=""):
    """返回 (cause, raw, source)。先在案情段找，再在「本院认为」开头找。"""
    for stage, seg in (("input", case_text), ("tail", tail[:400])):
        if not seg:
            continue
        for i, p in enumerate(CAUSE_PATTERNS):
            for m in p.finditer(seg):
                c = normalize_cause(m.group(1))
                if c:
                    return c, m.group(1), "%s_p%d" % (stage, i)
    return "", "", "none"


# ---------------------------------------------------------------- 法条

RE_LAW = re.compile(
    r"《([^》\n]{2,50}?)》\s*(第[一-龥零〇\d]{1,8}条(?:之[一二三四五六七八九十])?(?:第[一二三四五六七八九十\d]{1,4}款)?)"
)


def extract_laws(text):
    """按出现顺序去重，输出《全称》第X条。"""
    out, seen = [], set()
    for m in RE_LAW.finditer(text):
        name = re.sub(r"\s+", "", m.group(1))
        art = re.sub(r"\s+", "", m.group(2))
        # 去掉「第X款」，作业要求只到「条」
        art = re.sub(r"第[一二三四五六七八九十\d]{1,4}款$", "", art)
        if not art.endswith("条"):
            continue
        s = "《%s》%s" % (name, art)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


RE_BASIS = re.compile(r"(?:依照|依据|根据|按照)\s*(.{0,600}?)(?:之规定|的规定)\s*[，,]?\s*判决如下", re.S)


def extract_basis_laws(text):
    """「依照……之规定，判决如下」这句里的法条 = 判决依据。"""
    m = RE_BASIS.search(text)
    seg = m.group(1) if m else ""
    laws = extract_laws(seg) if seg else []
    if not laws:
        # 兜底：判决如下之前 800 字里的法条
        mm = RE_BOTTOM.search(text)
        if mm:
            laws = extract_laws(text[max(0, mm.start() - 800): mm.start()])
    return laws


# ---------------------------------------------------------------- 判决方向

# 判决主文里的套话，不参与方向判断
RE_BOILERPLATE = re.compile(
    r"加倍支付迟延履行期间的债务利息|迟延履行期间的债务利息|"
    r"如果未按本判决指定的(?:期限|期间)履行|如未按本判决指定的(?:期限|期间)履行|"
    r"本判决为终审判决|本判决即发生法律效力|上述(?:款项|款)于本判决生效|"
    r"如果未按本判决指定期限履行"
)
RE_FEE = re.compile(r"案件受理费|诉讼费|受理费|保全费|公告费|鉴定费|反诉费|申请费")
RE_ITEM_NO = re.compile(r"^[一二三四五六七八九十\d]{1,3}、")
RE_DISMISS_RES = re.compile(r"驳回(原告|被告|反诉原告|反诉被告)?[一-龥A-Za-z0-9（）()·、，,]{0,60}?(诉讼请求|诉讼请求项下的|请求|起诉)")


def _split_clauses(v):
    """按句号/分号切条，顺带去掉「一、二、」编号。"""
    parts = [p for p in re.split(r"[。；;]", v) if p.strip()]
    return [RE_ITEM_NO.sub("", p) for p in parts]


def classify_direction(verdict):
    """支持 / 部分支持 / 驳回。

    规则：把主文切成条款，剔除套话与诉讼费负担条，然后
      只有驳回条 → 驳回；只有支持条 → 支持；两者都有 → 部分支持。
    """
    v = re.sub(r"\s+", "", verdict or "")
    if not v:
        return "部分支持"

    n_dismiss = n_grant = 0
    for c in _split_clauses(v):
        # 「驳回原告的起诉」是程序性裁定，不算驳回诉讼请求
        if re.search(r"驳回[^，,。]{0,20}起诉", c):
            continue
        if RE_DISMISS_RES.search(c):
            n_dismiss += 1
            continue
        # 不准离婚 / 不予准许 这类否定式，等价于驳回原告该项请求
        if re.search(r"不准(?:予)?[一-龥]{0,24}离婚|不予(?:支持|准许|受理)|驳回全部诉讼请求", c):
            if not re.search(r"支付|赔偿|给付|返还|履行|腾退|交付", c):
                n_dismiss += 1
                continue
        if RE_BOILERPLATE.search(c):
            continue
        if RE_FEE.search(c) and not re.search(r"支付|赔偿|给付|返还|履行|负担之外的", c):
            continue
        if len(c) <= 2:
            continue
        n_grant += 1

    if n_dismiss and n_grant:
        return "部分支持"
    if n_dismiss:
        return "驳回"
    return "支持"


# ---------------------------------------------------------------- 当事人 / 金额

RE_PARTY = re.compile(
    r"原告[：:（(]?\s*([一-龥A-Za-z0-9（）()·]{2,30}?)[，,。；;、\n（(]"
)
RE_PARTY2 = re.compile(r"原告\s*([一-龥]{2,10}?)[，,。；;、\n（(]")
RE_AMOUNT = re.compile(r"[\d,，]+(?:\.\d+)?\s*(?:万)?元")


def extract_parties(case_text):
    names = []
    for p in (RE_PARTY, RE_PARTY2):
        for m in p.finditer(case_text[:1200]):
            n = m.group(1).strip()
            if n and n not in names:
                names.append(n)
        if names:
            break
    return names
