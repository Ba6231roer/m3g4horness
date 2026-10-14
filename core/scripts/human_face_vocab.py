#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""human_face_vocab — single-source closed-set vocabulary of toolchain-internal words
banned from human-facing output surfaces, plus the text scanner both consumers share.

Two consumers import THIS module's constants (never a copy):
  • the regression suite (tests/test_human_face_vocab.py content anchors, plus the
    deterministic-copy guard in tests/test_render_sdr_report.py) — a hit in code-written
    report copy is an implementation defect -> test fail, CI blocks;
  • the end-of-pipeline checker (render_sdr_report.py --check) — a hit in LLM-produced
    field text is soft quality -> stderr count warning only, never a different exit
    code, never a rewrite of the model's words.

Maintenance (the growth loop — 发现 → 确认 → 加一行 → 同步改内容锚测试):
  • A term enters ONLY by an explicit one-line addition here, sourced from a readability
    review advisory or a maintainer's own finding, AFTER human confirmation (review
    output is advisory; an unconfirmed false positive must never pollute the closed set).
  • Every entry carries `plain` — the plain-word replacement used both to rewrite
    deterministic copy and to guide the readability review.
  • Same-form rule (同形词守则, hard rule): words that mean different things in different
    contexts are collected as EXACT word forms scoped to one command domain; NEVER a
    bare word banned by substring. Red-light sample: 锚点 (evidence pointer, `file:line`)
    is a product concept and 锚定 "anchor to" is a normal verb — only 路由锚/向上锚定/
    锚定单元 are sdr grouping-algorithm words, so banning 锚定 by substring would kill
    both legitimate uses. 基线/单元/哨兵/存量/簇/扫描器 are all handled the same way.
  • Editing the vocabulary REQUIRES updating the content anchors in
    tests/test_human_face_vocab.py in the same change (vocab edit without anchor edit
    = red) — that is what keeps every addition conscious.

No CLI entry point; Python >=3.10 stdlib only; importable from any cwd (pure module).
"""

# Core layer: toolchain-wide internal words (cross-domain, stable word form, substring
# matching is safe for every one of them). Each entry: term / plain (人话替身 — the
# rewrite direction) / note (collision or provenance remarks).
CORE_TERMS = (
    {"term": "投影", "plain": "按预算截取/只带了一部分",
     "note": "子串匹配自动覆盖「基线投影」;DB 投影/物化视图撞车可接受(告警面软)"},
    {"term": "切片", "plain": "从 diff 里切出的一小份只读评审内容",
     "note": "日常词(数据切片),安全报告语境基本无撞车"},
    {"term": "hunk", "plain": "一段改动(diff 里的连续行块)", "note": "git 行话"},
    {"term": "扇出", "plain": "一项大任务拆成多个并行子任务",
     "note": "电子学「扇出系数」撞车中等,报告语境无碍"},
    {"term": "物化", "plain": "落成文件/生成实际文件", "note": "借自 DB「物化视图」"},
    {"term": "待办壳", "plain": "编排器看到的待跑任务清单条目", "note": "纯内部生造词"},
    {"term": "facet", "plain": "子类/细项", "note": "英文黑话未翻译"},
    {"term": "闭集", "plain": "固定清单/固定枚举",
     "note": "数学词;「按闭集排除」→「按固定清单排除」"},
    {"term": "vvah", "plain": "改述为「原上游项目」或删除",
     "note": "上游工具代号,曾实际泄漏进报告页脚"},
    {"term": "vvaharness", "plain": "改述为「原上游项目」或删除", "note": "同上"},
)

# Domain supplement layers: words that are internal ONLY inside one command's domain.
# A layer is inert data until its domain registers a human-face surface (the consumer
# passes the domain names it is guarding); unregistered domains cost nothing.
# init/ut-init share one pool; sast/srr share one pool (same family shape as the
# registry: one row per registered surface, pools per command family).
_INIT_FAMILY_TERMS = (
    {"term": "家法", "plain": "团队实际在用的测试惯例", "note": ""},
    {"term": "存量控制", "plain": "项目里已有的安全措施",
     "note": "单词「存量」不收"},
    {"term": "扫描器模式定义", "plain": "删除(实现细节)", "note": "单词「扫描器」不收(SAST scanner 强撞车),只禁这两个短语"},
    {"term": "扫描器内部正则", "plain": "删除(实现细节)", "note": "同上"},
    {"term": "归类器", "plain": "测试风格分类", "note": ""},
    {"term": "归类器子分", "plain": "删除(实现细节)", "note": ""},
    {"term": "断言密度", "plain": "测试里断言的数量与分布", "note": ""},
    {"term": "均匀组", "plain": "风格一致的分组", "note": ""},
    {"term": "异质组", "plain": "风格不一致的分组", "note": ""},
    {"term": "均匀度", "plain": "分组风格一致程度", "note": ""},
    {"term": "抽样提炼", "plain": "按样本归纳,非全量审读", "note": ""},
    {"term": "锚内", "plain": "已安装目录内", "note": ""},
    {"term": "惰性索引块", "plain": "按需加载的索引段", "note": ""},
    {"term": "源头净化层", "plain": "删除(实现细节)", "note": ""},
    {"term": "伪控制", "plain": "由 mock/测试代码造成的假命中", "note": ""},
    {"term": "一方业务代码", "plain": "项目自己的业务代码", "note": ""},
    {"term": "烧 token", "plain": "浪费调用开销", "note": ""},
    {"term": "毒输入", "plain": "损坏或不可信的输入", "note": ""},
    {"term": "过期凭证", "plain": "基于旧输入的过期产物标记", "note": ""},
    {"term": "判别尾", "plain": "删除(编码细节)", "note": ""},
    {"term": "显示槽位", "plain": "删除(编码细节)", "note": ""},
    {"term": "sha8", "plain": "删除(编码细节)", "note": ""},
    {"term": "召唤语义", "plain": "调用方式", "note": ""},
    {"term": "净网", "plain": "路径白名单校验", "note": ""},
    {"term": "有界 ack", "plain": "单行结果回执", "note": ""},
)

_SRA_TERMS = (
    {"term": "三信号", "plain": "三种匹配依据:维度契合/业务域相似/业务事实", "note": ""},
    {"term": "信号-1", "plain": "维度契合", "note": ""},
    {"term": "信号-2", "plain": "业务域相似", "note": ""},
    {"term": "信号-3", "plain": "业务事实", "note": ""},
    {"term": "泛化缺口", "plain": "没有具体落点的通用建议", "note": ""},
    {"term": "引用控制", "plain": "复用了项目已有措施", "note": ""},
    {"term": "评审原子", "plain": "不可再切分的评审单位", "note": ""},
    {"term": "O4 减问门控", "plain": "删除(实现细节)", "note": ""},
    {"term": "外科式上下文", "plain": "只取需要的片段", "note": ""},
    {"term": "秒批", "plain": "可直接采纳默认值", "note": ""},
    {"term": "文件回填", "plain": "把回答写进文件带回", "note": ""},
    {"term": "块外快照", "plain": "合并影响范围记录", "note": ""},
)

_SAST_SRR_TERMS = (
    {"term": "canonical 6-enum", "plain": "删除或列全枚举名", "note": ""},
    {"term": "下架", "plain": "标记为已处理", "note": "处置黑话"},
    {"term": "中和", "plain": "标记为已处理", "note": "处置黑话"},
    {"term": "降权", "plain": "降低严重级别", "note": "处置黑话"},
    {"term": "triage candidate", "plain": "待复核候选", "note": ""},
    {"term": "dropped findings", "plain": "已过滤的低价值发现", "note": ""},
    {"term": "docx-best-effort", "plain": "尽力抽取,抽不全处已标注", "note": "降级码"},
    {"term": "tables-flattened", "plain": "尽力抽取,抽不全处已标注", "note": "降级码"},
)

DOMAIN_TERMS = {
    "sdr": (
        {"term": "路由锚", "plain": "作为分组入口的变更接口", "note": ""},
        {"term": "向上锚定", "plain": "改动挂接到未变更的接口", "note": ""},
        {"term": "锚定单元", "plain": "挂接单元", "note": "与「锚点(证据)」区分的精确词形"},
        {"term": "目录聚簇", "plain": "按目录归堆的兜底分组", "note": "单词「簇」不收(撞聚簇索引)"},
        {"term": "判不穿", "plain": "解析不出调用关系", "note": ""},
        {"term": "残余归并", "plain": "实在归不了组的落回独立评审", "note": ""},
        {"term": "链合并", "plain": "同入口的链路合并为一组", "note": ""},
        {"term": "检查面", "plain": "本次检查的范围", "note": ""},
        {"term": "interface 单元", "plain": "接口单元", "note": "概览分类语境组合形;单词 interface 不收"},
        {"term": "interface 模式", "plain": "接口单元模式", "note": "同上"},
        {"term": "standalone 单元", "plain": "独立文件单元", "note": "概览分类语境组合形;单词 standalone 不收"},
        {"term": "standalone 模式", "plain": "独立文件单元模式", "note": "同上"},
    ),
    "init": _INIT_FAMILY_TERMS,
    "ut-init": _INIT_FAMILY_TERMS,
    "sra": _SRA_TERMS,
    "sast": _SAST_SRR_TERMS,
    "srr": _SAST_SRR_TERMS,
}


def scan_text(text, domains=("sdr",)):
    """Return the closed-set terms found in `text` (each term once, core layer always
    active, then the requested domain supplement layers). Substring match over the
    EXACT term forms only — per the same-form rule, no bare word is ever banned, so a
    hit is always the real internal word, never a legitimate collision inside a
    compound the reader understands."""
    if not isinstance(text, str) or not text:
        return []
    terms = [e["term"] for e in CORE_TERMS]
    for d in domains or ():
        terms.extend(e["term"] for e in DOMAIN_TERMS.get(d, ()))
    hits = []
    for t in terms:
        if t in text and t not in hits:
            hits.append(t)
    return hits
