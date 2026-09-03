## Context

- **`add-mgh-sdr` 现状**:`diff_group.py` 分组是「注解启发式接口单元 + 目录簇 standalone」,
  codegraph 是「可选减扇出信号、不进分组依赖」。本 change 把分组升级为调用链感知。
- **codegraph CLI 能力(已核实)**:`callers <sym> --json` / `callees <sym> --json`(调用边)、
  `impact <sym> --depth --json`(影响半径)、`node <file> --file --symbols-only`(文件内符号
  边界 + dependents)、`query <search> --json`。**Java 全支持 + Spring 框架路由**
  (`@GetMapping/@PostMapping/@RequestMapping` 链到 handler);实测 Java 跨文件覆盖 93.3%、
  Spring 路由 83.3%(诚实的静态分析天花板 = 反射/DI/AOP 残差)。
- **关键判定**:分组必须**确定性**完成(不进主壳 LLM)——否则大 diff 时主壳做「理解调用链 +
  分组」的思考会撑爆 150k 上下文、后续派发/汇总退化。codegraph 的 `--json` 输出让「理解调用
  链」成为 `diff_group.py` 内的一次子进程调用 + 并查集,主壳只读 `pending[]` 小清单。
- **约束**:R2(零 pip 依赖;codegraph 是可选宿主二进制,同 git)、R5.3a/b(`diff_group.py` CLI
  契约与 `pending[]` shape 不变)、R5.9(`--check`)、R5.10(壳零 dev-meta)。

## Goals / Non-Goals

**Goals:**
- 同一接口调用链上的变更合并进一个 fan-out 单元,让「跨层判定」(鉴权 + SQL + 校验)在单个
  subagent 上下文内完整可见,不漏检、不越界读。
- 分组全程确定性(脚本侧)、可复现、有 `--check` 校验;主壳上下文不随 diff 大小增长。
- codegraph 保持可选:off 时退化为 `add-mgh-sdr` 现状,行为等价、零失败。

**Non-Goals:**
- 不做 tree-sitter 调用链后端(那是 mgh-sast 的规划)。
- 不改 `diff_group.py` 的 CLI flag 面与 `pending[]` 字段 shape。
- 不改 fan-out 派发、波次状态机、模板填充、render 去重的任何行为。
- 不把 codegraph 变成硬依赖(probe 不到即降级)。

## Decisions

### D1 — 分组机制:codegraph 调用边驱动的确定性调用链分组(替代注解+目录为主策略)

备选 A「主壳 LLM 读 diff 后思考分组」:准确但主壳上下文随 diff 线性膨胀,大 diff 直接爆 150k,
且非确定性、不可复现。拒绝(正是用户点 5 的顾虑)。
备选 B「注解+目录启发式」(现状):确定性、便宜,但把同链切成两半,跨层判定不完整。
选 codegraph 调用边驱动:变更符号集建图 → `callers`/`callees --json` 取边 → 并查集连通分量 →
含路由分量 = interface 单元、其余 = standalone 单元。全程确定性、可复现、O(变更符号数);无
codegraph 退化 B。codegraph 判不穿(反射/DI)→ 该符号无边 → 落 standalone 拆多个(正是「拆多个
不硬塞」)。〔质量 + 确定性 + 上下文有界 + 失败退化安全〕

### D2 — 分组算法:变更符号提取 + 连通分量 + 单元物化(细节)

1. **变更符号提取**:`git diff --name-only` 得变更文件;对每个变更文件,用注解启发式(接口方法)
   + `codegraph node --file --symbols-only`(有 codegraph 时)把每个 diff hunk 映射到「包住它的
   符号」(方法/接口);无符号可映射的 hunk 归「文件级变更」。
2. **建图**:节点 = 变更符号;边 = codegraph `callers`/`callees` 在**变更符号集内**的调用关系
   (仅保留两端都在变更集内的边——只关心「本次 diff 改了什么、它们之间的调用关系」)。
3. **连通分量**:并查集求连通分量。含 ≥1 路由注解符号的分量 → `interface` 单元(route = 该路由
   注解方法的 route 串);无路由分量 → `standalone` 单元。
4. **单元物化**:`interface` 单元 slice = 分量内全部变更符号的 diff hunk(controller 路由方法 +
   其下游变更 service/dao)+ 类级注解上下文 + 权限注解命中;`standalone` 单元 slice = 分量内变更
   文件的 hunk(按目录簇,`--max-standalone-bytes` 超限再拆)。
5. **共享下游**:一个变更符号被多个 interface 分量引用(service 被 /a 与 /b 都调)→ 不并成一个
   分量(接口是隔离单位),该符号 hunk 在每个引用它的 interface 单元 slice 内重复,单 slice 仍受
   `unit_bytes` 预算;跨单元重复 finding 由 render 三元组去重。
〔可复现 + 接口是判定单位 + 共享下游不破坏隔离 + 预算有界〕

### D3 — codegraph 是「可选分组输入」,不是硬依赖

分组质量依赖调用边,而调用边只有 codegraph 能确定性提供(文本 grep 脆弱)。故 codegraph 升为
分组阶段的输入;但仍是**可选宿主能力**:`diff_group.py` 启动时 probe `<repo>/.codegraph/` 存在
∧ PATH 有 `codegraph` 才走调用链分组,否则退化为注解+目录(与现状逐字等价)。probe 失败 = 零
codegraph 调用、退出码不受影响。codegraph 是外部二进制(非 pip 依赖),承 R2。
〔质量增益与「零运行时依赖」两全:可选、可降级、非 pip〕

### D4 — 共享下游按接口拆(不并成一个「共享簇」)

一个 service 被多个变更接口调用时,「并成一个共享簇」会让一个单元承载多个接口的语义(路由不止
一条、判定锚点分裂),与「一个接口一个单元」的判定语义冲突,且单元体积不可控。故按接口拆:
service hunk 在每个引用接口的 slice 内字节预算内重复。代价是少量重复分析,收益是接口隔离清晰
+ 单元体积有界;重复 finding 交 render 三元组去重,不产生报告噪声。
〔接口 = 隔离单位;重复可去重;体积有界〕

## Risks / Trade-offs

- [codegraph 调用边漏反射/DI/AOP] → 该变更符号无调用边,落 standalone 拆多个(不漏检、粒度粗);
  覆盖上限在报告诚实边界披露。
- [codegraph 缺失时分组退回注解+目录,同链仍被切] → 与现状等价(非回归);文档与 `--help` 披露
  「调用链分组需 codegraph」,用户可选装。
- [变更符号提取不精确(hunk 映射错方法)] → 映射失败退「文件级变更」并入目录簇;分组仍是确定性
  (同输入同输出),不产生非确定漂移。
- [共享下游重复 slice 放大 token] → 单 slice `unit_bytes` 预算 + render 去重;重复仅发生在真
  共享(同一 service 被多接口调)场景,频率低。
- [codegraph index 滞后(刚 commit 未索引)] → 变更符号/调用边可能取旧索引;诚实边界:索引是
  快照,用户可 `codegraph sync` 后再跑。

## Migration Plan

纯增量:`diff_group.py` 内部算法升级,CLI flag 面、`pending[]` shape、下游派发/渲染契约零变;无
codegraph 的项目行为与现状逐字等价(非回归)。部署 = 重跑 install 覆盖更新后的 `diff_group.py`
+ `sdr-task.md`。回滚 = 还原 `diff_group.py` 旧版即可,无 schema 迁移、无状态迁移。

## Open Questions

- 变更符号提取的 hunk→符号映射是否要覆盖 Kotlin/Scala(目标域 java web,首版以 java 为主,
  codegraph 对 Kotlin/Scala 亦有支持,按需后扩)。
- codegraph `callers`/`callees` 的 `--limit`(默认 20)是否够用(大服务类可能超 20 个 caller;
  分组只关心变更集内的边,可传 `--limit` 上调或按需翻页)。
