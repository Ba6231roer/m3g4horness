<!--
  mgh-init stage-flow — assemble (step 6b). Install mirrors to <mgh-core>/prompts/fragments/init-stage/.
  Loaded per-step via resume_state.py stdout stage_flow_files[] (current-step single file).
-->

## assemble (step 6b)

```
6b. ASSEMBLE / LINT (Bash, deterministic; uses the run's --format, after T3 / before T4):
     py .claude/mgh-core/scripts/assemble_rules.py --target <target> --format <format>
   · opencode: 扫 `<rules-dir>/*.md` 详述文件建 `<target>/AGENTS.md` 简洁**惰性索引块**(幂等、迁移旧 `mgh-init:` 块、内置 lint);正文留详述文件按需加载
   · claude: 无索引(T3 已直写文件),仅对 `.claude/rules/security-*.md` 做纯净性 lint
   · lint(fail-loud 退出码 2)= 规则正文泄漏:T3 禁 front matter / inventory schema 字段
     (`found_controls`/`evidence_count`)/ 过程散文(`扫描器模式定义` 等)/ 无源码锚点的控制;lint 覆盖
     工具内部 token + schema 字段 + 特征过程散文(opencode 另查 `---` YAML 围栏;claude `paths:` frontmatter 豁免)。
     回 T3 修正后重跑
```
