## 1. Guard core — `block_adhoc_scripts.py`(双端两份 byte-parity)

> 编辑 `releases/claude-code/hooks/block_adhoc_scripts.py` **与** `releases/opencode/hooks/block_adhoc_scripts.py`
> 两份(由 `tests/test_opencode_hook_parity.py` 强制 byte-identical;改一处必镜像另一处)。判定逻辑单一来源
> 留在 `.py`,`.ts` 插件不改。

- [x] 1.1 **激活 = env 或哨兵**:`main()` 激活判定由「仅 `MGH_*_ACTIVE=1` env」扩为「env **或**
      `<cwd>/<run-root>/.active` 哨兵」;run-root 按域:init→`.mgh-init`、sast→`security-scan`、sra→`.mgh-sra`、
      srr→`.mgh-srr`。新增 `_read_sentinel(cwd)` 读哨兵 JSON `{domain,target,out_roots[],v}`(容错:缺失/破损→None)。
- [x] 1.2 **MGH_TARGET 取值优先级** = env `MGH_TARGET` > 哨兵.`target` > cwd;子树/受信子树判定统一走该解析
      (使 opencode env 未设时子树守卫仍生效)。
- [x] 1.3 **脚本扩展名集**:把 `_is_blocked_py_write` 的 `.py`-only 检查换成集合
      `_SCRIPT_EXTS={.py,.ps1,.sh,.bash,.zsh,.bat,.cmd,.ts,.js,.mjs,.cjs}`;函数更名 `_is_blocked_script_write`。
- [x] 1.4 **取消白名单豁免**:删除 `"core/scripts" in norm` 与 `_WL_SEGMENTS` 放行分支(运行域脚本只读);
      保留「未激活 → return 0」早退(install/dev 态不受影响)。
- [x] 1.5 **init 正向受信子树允许清单**:init 域 `_is_out_of_tree` 升级为「须在 `MGH_TARGET` 内 **且** 在受信
      子树」;受信集 = `<target>/.mgh-init/**`、`<target>/.claude/rules/**`、`<target>/docs/security-controls/**`、
      `<target>/AGENTS.md` ∪ 哨兵 `out_roots[]`(均 `Path.resolve()` 绝对比对)。sast/sra/srr 保留既有树外拦截。
- [x] 1.6 **recipe / docstring 更新**:命中信息补「哨兵激活」「叶脚本 read-only」「受信子树」措辞;stderr recipe
      仍指向 `list_*`/`describe_artifact`/producer stdout 绝对路径字段。文件头 docstring 同步四条新规则。

## 2. Guard 单测 — `tests/test_block_adhoc_scripts.py`

- [x] 2.1 **翻白名单断言**:把 `test_pass_whitelisted_py_write` 改为运行域内 `Write` `.claude/mgh-core/scripts/*.py`
      → 断言 **BLOCK**(退出码 2)(agent 改叶脚本失守形状的回归锚)。
- [x] 2.2 **哨兵激活(env 未设)**:新增——`MGH_*_ACTIVE` env 全空 + 写 `<cwd>/.mgh-init/.active` 哨兵 → 守卫激活,
      `py -c` 内省/越权脚本写均退出码 2(opencode hole 关闭)。
- [x] 2.3 **哨兵携 target 的子树拦截**:env `MGH_TARGET` 未设 + 哨兵 `target=<tmp>` → `Write` 该 target 子树外
      路径退出码 2(验证 MGH_TARGET 取自哨兵)。
- [x] 2.4 **脚本扩展名集**:新增 `.ps1`/`.sh`/`.ts` 写入 → BLOCK;`.json`/`.md` 写入不受该规则拦。
- [x] 2.5 **init 根污染拦截**:`Write` `<target>/temp_clusters1.json`(在 target、非受信子树)→ BLOCK;
      `Write` `<target>/.mgh-init/inputs/t1/x.json` / `<target>/.claude/rules/x.md` / `<target>/docs/security-controls/a.md`
      / `<target>/AGENTS.md` → PASS;哨兵 `out_roots[]` 内自定义根写入 → PASS。
- [x] 2.6 **stale / 降级**:哨兵缺失 + env 未设 → 退出码 0(零噪声);MGH_TARGET 与哨兵.target 均缺 → 子树
      检查降级放行(不误伤)。

## 3. opencode 胶水 + parity — `releases/opencode/plugins/block_adhoc_scripts.ts`、`tests/test_opencode_hook_parity.py`

- [x] 3.1 确认 `.ts` **无判定逻辑变更**(仍是事件归一化 + 管道 + 据退出码 2 阻断);`env: process.env` +
      `cwd: process.cwd()` 已就绪(哨兵经磁盘可见)。
- [x] 3.2 `tests/test_opencode_hook_parity.py` 扩:断言两份 `.py` byte-identical 含新哨兵/扩展名/受信子树逻辑;
      `.ts` 归一化 + 阻断契约不变。

## 4. 契约 + 文档

- [x] 4.1 新增 `core/contracts/hooks/runtime-enforcement.md`:哨兵 schema(`{domain,target,out_roots[],v}`)+
      各域 run-root 映射 + init 受信子树表 + `_SCRIPT_EXTS` 集 + MGH_TARGET 优先级 + step-0 写/完成移除契约。
- [x] 4.2 守卫文件头 docstring 与契约一致(交叉引用 `runtime-enforcement.md`)。

## 5. 命令壳(四命令 × claude/opencode 双壳 = 8 份)— step-0 哨兵 + 完成移除

- [x] 5.1 `mgh-init.md`(claude + opencode):step 0 增 `Bash` 写 `<target>/.mgh-init/.active`
      (`printf` JSON,含 `target_abs` + 自定义 `--out`/`--rules-dir` 解析进 `out_roots[]`);完成态(step 8)/
      干净停止移除哨兵。
- [x] 5.2 `mgh-sast.md`(claude + opencode):step 0 写 `<target>/security-scan/.active`;完成态移除。
- [x] 5.3 `mgh-sra.md`(claude + opencode):step 0 写 `<target>/.mgh-sra/.active`;完成态移除。
- [x] 5.4 `mgh-srr.md`(claude + opencode):step 0 写 `<target>/.mgh-srr/.active`;完成态移除。
- [x] 5.5 校验 8 壳的哨兵写/移除措辞双端对等;`--no-enforce-hook` opt-out 说明仍准确(哨兵是激活信号、
      opt-out 时守卫未注入→哨兵无作用,语义自洽)。

## 6. AGENTS.md 规约同步

- [x] 6.1 **R5.7 段 B**:把「opencode 插件不继承 mid-session env → 未激活 fail-soft」更新为「**由磁盘哨兵
      关闭**——激活 = env 或哨兵,守卫双端可靠激活」;`MGH_TARGET` 优先级(env>哨兵>cwd)入规。
- [x] 6.2 **R5.2 / R5.5①**:运行域脚本只读措辞(取消 `core/scripts` 白名单、扩展名集);recipe 补「哨兵激活」。
- [x] 6.3 **强制面索引表**:R5.7 行入口/机制描述同步(哨兵 + env 双激活)。

## 7. 回归 + 验收

- [x] 7.1 `py tests/test_block_adhoc_scripts.py` + `py tests/test_opencode_hook_parity.py` 全绿。
- [x] 7.2 `py tests/test_deterministic.py`(及既有 `test_list_*`/`test_init_*`)不退化。
- [x] 7.3 零依赖 AST 扫描:`grep -rnE "^[[:space:]]*(import|from) ..."` 无第三方包(哨兵读写仅 stdlib `json`/`pathlib`)。
- [x] 7.4 `openspec validate harden-mgh-opencode-hook-enforcement --strict` 通过;MODIFIED 要求 header 与
      `openspec/specs/` 原文逐字一致(control-discovery / sast-orchestration-discipline / freeform-security-review)。
- [x] 7.5 `tools/check_contracts.py`(无新脚本 flag,除非新增 `mark_run_domain.py`——决策 Q3 倾向不加)+
      `tools/check_distributed_purity.py`(分发 md 不携带 dev-meta)。
- [x] 7.6 VERSION bump + CHANGELOG(R5.8);install 自检 fail-soft + CI 必 fail(R5.8)。
- [x] 7.7 端到端:模拟 opencode env 未继承 → step-0 哨兵写入 → 守卫激活拦截 `py -c`/越权脚本写/越树写/
      根污染(手动或一次性校验脚本,非分发)。
