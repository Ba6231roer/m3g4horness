#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""human_face_vocab unit tests: closed-set content anchors, scan behaviour, and the
distribution-doc reconciliation for the human-face writing discipline.

The content anchors ARE the growth-loop enforcement: the exact term sets below MUST be
updated in the same change that edits the vocabulary — a vocab edit without its anchor
edit fails here, so every term addition is conscious and carries its plain-word
replacement into both guard surfaces (deterministic-copy regression test + end-of-chain
--check warning).

The doc-reconciliation tests lock the prompt-side half of the discipline: the sdr task
template carries the writing discipline + extended schema, its human-face field
descriptions are themselves written in reader language (zero closed-set words), and the
three agent definitions' Output schema lines stay byte-identical.

Run: py tests/test_human_face_vocab.py
"""
import importlib.util
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "core" / "scripts"
VOCAB = SCRIPTS / "human_face_vocab.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- the anchored closed sets (edit together with human_face_vocab.py) --------------

CORE_TERMS = {"投影", "切片", "hunk", "扇出", "物化", "待办壳", "facet", "闭集",
              "vvah", "vvaharness"}

SDR_TERMS = {"路由锚", "向上锚定", "锚定单元", "目录聚簇", "判不穿", "残余归并",
             "链合并", "检查面",
             "interface 单元", "interface 模式", "standalone 单元", "standalone 模式"}

# same-form guard: these bare words are NOT banned anywhere (they collide with the
# reader's working language or other domains' legitimate usage); only exact compound
# forms scoped to a domain may enter the closed set
NEGATIVE_BARE_WORDS = {"锚点", "锚定", "基线", "单元", "哨兵", "存量", "簇", "扫描器",
                       "维度"}

INIT_FAMILY_SPOT = {"家法", "存量控制", "扫描器模式定义", "扫描器内部正则", "归类器",
                    "断言密度", "抽样提炼", "锚内", "惰性索引块", "伪控制",
                    "一方业务代码", "毒输入", "过期凭证", "召唤语义", "净网", "有界 ack"}
SRA_SPOT = {"三信号", "信号-1", "信号-2", "信号-3", "泛化缺口", "引用控制", "评审原子",
            "外科式上下文", "秒批", "文件回填", "块外快照"}
SAST_SRR_SPOT = {"canonical 6-enum", "下架", "中和", "降权", "triage candidate",
                 "dropped findings", "docx-best-effort", "tables-flattened"}


class VocabContentAnchorTest(unittest.TestCase):
    """改词表不改测试 = 红:exact-set anchors over every vocabulary layer."""

    def setUp(self):
        self.v = _load("human_face_vocab", VOCAB)

    def test_core_terms_exact_set(self):
        terms = {e["term"] for e in self.v.CORE_TERMS}
        self.assertEqual(terms, CORE_TERMS)
        for e in self.v.CORE_TERMS:
            self.assertTrue(e["plain"].strip(), f"core term {e['term']!r} needs plain")

    def test_sdr_domain_exact_set(self):
        terms = {e["term"] for e in self.v.DOMAIN_TERMS["sdr"]}
        self.assertEqual(terms, SDR_TERMS)
        for e in self.v.DOMAIN_TERMS["sdr"]:
            self.assertTrue(e["plain"].strip(), f"sdr term {e['term']!r} needs plain")

    def test_preset_domains_seeded(self):
        # init/ut-init share one pool; sast/srr share one pool; sra has its own
        self.assertIs(self.v.DOMAIN_TERMS["init"], self.v.DOMAIN_TERMS["ut-init"])
        self.assertIs(self.v.DOMAIN_TERMS["sast"], self.v.DOMAIN_TERMS["srr"])
        init_terms = {e["term"] for e in self.v.DOMAIN_TERMS["init"]}
        sra_terms = {e["term"] for e in self.v.DOMAIN_TERMS["sra"]}
        sast_terms = {e["term"] for e in self.v.DOMAIN_TERMS["sast"]}
        self.assertTrue(INIT_FAMILY_SPOT <= init_terms,
                        f"init pool missing: {INIT_FAMILY_SPOT - init_terms}")
        self.assertTrue(SRA_SPOT <= sra_terms,
                        f"sra pool missing: {SRA_SPOT - sra_terms}")
        self.assertTrue(SAST_SRR_SPOT <= sast_terms,
                        f"sast/srr pool missing: {SAST_SRR_SPOT - sast_terms}")
        for domain in ("init", "ut-init", "sra", "sast", "srr"):
            for e in self.v.DOMAIN_TERMS[domain]:
                self.assertTrue(e["plain"].strip(),
                                f"{domain} term {e['term']!r} needs plain")

    def test_no_bare_word_terms_anywhere(self):
        # same-form rule: NEVER a bare word banned by substring (the 锚 family is the
        # red-light sample); every layer must hold this
        all_terms = [e["term"] for e in self.v.CORE_TERMS]
        for domain, entries in self.v.DOMAIN_TERMS.items():
            all_terms.extend(e["term"] for e in entries)
        for t in all_terms:
            self.assertNotIn(t, NEGATIVE_BARE_WORDS,
                             f"term {t!r} is a bare word barred by the same-form rule")


class VocabScanBehaviourTest(unittest.TestCase):
    def setUp(self):
        self.v = _load("human_face_vocab", VOCAB)

    def test_core_hit(self):
        self.assertEqual(self.v.scan_text("基线投影下未命中", domains=("sdr",)), ["投影"])

    def test_no_hit_on_legitimate_same_forms(self):
        # 锚点 (evidence pointer) is a product word; 锚定到 (sra verb) is normal prose
        self.assertEqual(
            self.v.scan_text("证据锚点见 OrderController.java:10", domains=("sdr",)), [])
        self.assertEqual(
            self.v.scan_text("把发现锚定到需求条目", domains=("sra",)), [])

    def test_combo_forms_only_in_domain_context(self):
        self.assertEqual(
            self.v.scan_text("本次产出 interface 单元 3 个", domains=("sdr",)),
            ["interface 单元"])
        # the bare English word in code context is the reader's working language
        self.assertEqual(
            self.v.scan_text("the UserService interface declares", domains=("sdr",)), [])
        # domain terms are inactive when their domain is not registered
        self.assertEqual(self.v.scan_text("interface 单元", domains=()), [])

    def test_core_always_active(self):
        self.assertEqual(self.v.scan_text("投影", domains=()), ["投影"])

    def test_substring_match_is_by_design(self):
        # the core layer only admits substring-safe terms; the DB-projection collision
        # is accepted (warn-side, soft)
        self.assertEqual(self.v.scan_text("用投影仪展示", domains=("sdr",)), ["投影"])

    def test_upstream_code_names_hit(self):
        hits = self.v.scan_text("页脚写着 vvaharness", domains=("sdr",))
        self.assertIn("vvaharness", hits)
        self.assertIn("vvah", hits)          # prefix substring — by design

    def test_clean_text_no_hits(self):
        self.assertEqual(
            self.v.scan_text("以任一有效登录会话 POST /user/del 传他人 id,他人记录会被删除。",
                             domains=("sdr",)), [])

    def test_each_hit_reported_once(self):
        hits = self.v.scan_text("投影与切片,再提一次投影", domains=("sdr",))
        self.assertEqual(sorted(hits), ["切片", "投影"])

    def test_non_string_input(self):
        self.assertEqual(self.v.scan_text(None, domains=("sdr",)), [])
        self.assertEqual(self.v.scan_text("", domains=("sdr",)), [])
        self.assertEqual(self.v.scan_text(42, domains=("sdr",)), [])


class DualConsumerSameSourceTest(unittest.TestCase):
    """词表单一真相源:末步校验(render_sdr_report)与回归测试 import 同一模块文件。"""

    def test_renderer_imports_this_vocab_file(self):
        m = _load("render_sdr_report", SCRIPTS / "render_sdr_report.py")
        self.assertEqual(Path(m.human_face_vocab.__file__).resolve(), VOCAB.resolve())


class HumanFaceDocsTest(unittest.TestCase):
    """1.6 对账:任务模板携写作纪律 + 扩字段 schema(字段描述自身零闭集词);
    三面 agent 定义 Output schema 行一致;三面壳均含可读性评审步骤。"""

    def setUp(self):
        self.v = _load("human_face_vocab", VOCAB)
        self.task_md = (ROOT / "core" / "prompts" / "fragments" / "fanout"
                        / "sdr-task.md").read_text(encoding="utf-8")

    def test_task_template_carries_discipline_and_schema(self):
        self.assertIn("写作纪律", self.task_md)
        self.assertIn('"repro"', self.task_md)
        self.assertIn('"fix_diff"', self.task_md)

    def test_task_template_field_descriptions_closed_set_free(self):
        # the model imitates the register of field descriptions — they must be written
        # in the calibrated reader's language (zero closed-set words)
        lines = [ln for ln in self.task_md.splitlines()
                 if re.search(r'"(risk|suggestion|repro|fix_diff)"\s*:', ln)]
        self.assertTrue(lines, "no human-face field description lines found")
        for ln in lines:
            self.assertEqual(self.v.scan_text(ln, domains=("sdr",)), [],
                             f"field description hit closed set: {ln!r}")

    def test_three_agent_output_schema_lines_identical(self):
        agent_files = [
            ROOT / "releases" / "opencode" / "agent" / "sdr-review-fanout.md",
            ROOT / "releases" / "claude-code" / "agents" / "sdr-review-fanout.md",
            ROOT / "releases" / "dsh" / "agents" / "sdr.md",
        ]
        blocks = []
        for p in agent_files:
            text = p.read_text(encoding="utf-8")
            m = re.search(r'\{"unit".*?\]\}', text, re.S)
            self.assertIsNotNone(m, f"{p} has no Output schema line")
            block = m.group(0)
            self.assertIn("repro", block, f"{p} Output schema missing repro")
            self.assertIn("fix_diff", block, f"{p} Output schema missing fix_diff")
            self.assertIn("写作纪律", text, f"{p} missing the discipline pointer")
            blocks.append(block)
        self.assertEqual(blocks[0], blocks[1])
        self.assertEqual(blocks[1], blocks[2])

    def test_three_shells_carry_readability_review_step(self):
        shells = [
            ROOT / "releases" / "opencode" / "command" / "mgh-sdr.md",
            ROOT / "releases" / "claude-code" / "commands" / "mgh-sdr.md",
            ROOT / "releases" / "dsh" / "skills" / "mgh-sdr" / "SKILL.md",
        ]
        for p in shells:
            text = p.read_text(encoding="utf-8")
            # the convention paths themselves live in the fragment header + the
            # pipeline contract; the shell carries the step pointer + best-effort terms
            for marker in ("readability-review.md", "编排器指派", "尽力而为", "可读性自检"):
                self.assertIn(marker, text, f"{p} missing readability-step marker {marker!r}")


class OnePassDisciplineDocsTest(unittest.TestCase):
    """fix-mgh-sdr-quota-adaptive-fanout 6.x 对账:任务模板携单遍往返纪律段
    (全部输入第一批并行读入 → 一次判断 → 写 draft 与 touch marker 同批 → 单行 ack,
    NEVER 逐文件多轮往返),且与刚性三元组共存(路径闭集措辞逐字保留);三面 agent
    定义各含与模板一致的单行指针(逐字对账)。"""

    def setUp(self):
        self.task_md = (ROOT / "core" / "prompts" / "fragments" / "fanout"
                        / "sdr-task.md").read_text(encoding="utf-8")
        self.agent_files = [
            ROOT / "releases" / "opencode" / "agent" / "sdr-review-fanout.md",
            ROOT / "releases" / "claude-code" / "agents" / "sdr-review-fanout.md",
            ROOT / "releases" / "dsh" / "agents" / "sdr.md",
        ]

    def test_task_template_carries_one_pass_discipline(self):
        for marker in ("单遍往返纪律", "first batch of parallel reads",
                       "ONE same batch", "single ack line",
                       "NEVER read your inputs one file per round",
                       "逐文件多轮往返"):
            self.assertIn(marker, self.task_md, marker)

    def test_one_pass_discipline_coexists_with_rigid_triple(self):
        # the discipline bounds ROUND TRIPS only — the rigid I/O triple's
        # path-closed-set wording must survive verbatim
        self.assertIn("## Rigid I/O triple", self.task_md)
        self.assertIn("Read ONLY `input_path`", self.task_md)
        self.assertIn("Write EXACTLY `draft_path`", self.task_md)
        self.assertIn("unchanged, word for word", self.task_md)

    def test_three_agent_pointers_identical_and_match_template(self):
        pointer = ("- 单遍往返(调用次数收敛):全部输入(slice + 基线投影 + 敏感目录 + 外部结论)第一批并行\n"
                   "  读入 → 一次判断 → 写 draft 与 touch marker 同批 → 单行 ack;NEVER 逐文件多轮往返\n"
                   "  (调用次数限流网关下每次往返都烧配额)。本条只约束往返次数——读/写路径闭集与刚性\n"
                   "  三元组逐字不变。")
        for p in self.agent_files:
            text = p.read_text(encoding="utf-8")
            self.assertIn(pointer, text,
                          f"{p} missing the verbatim one-pass pointer line")
        # template and pointer agree on the canonical sequence
        for marker in ("first batch of parallel reads", "ONE same batch",
                       "逐文件多轮往返"):
            self.assertIn(marker, self.task_md, marker)


if __name__ == "__main__":
    unittest.main(verbosity=2)
