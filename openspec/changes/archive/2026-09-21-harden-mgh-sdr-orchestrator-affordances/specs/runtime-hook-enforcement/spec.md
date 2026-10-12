## ADDED Requirements

### Requirement: Bash inline interpreter code blocked in all feeding forms (heredoc / here-string)

The guard's inline-code introspection judgment SHALL cover **every** form that feeds interpreter
code inline through a `Bash` command, not only the `-c` flag:

- interpreter token (`py`/`python`/`python2`/`python3`, start- or delimiter-bound) followed by
  `-c` (existing shape, unchanged);
- the same interpreter token followed by a **standalone `-`** argument (code on stdin — the
  heredoc shape `python3 - <<'EOF' … EOF`);
- the same interpreter token followed by a **here-string** (`- <<<` or `< <<` feeding stdin).

A hit SHALL fail-loud (exit 2) with the SAME sanctioned-primitive recipe as the `-c` shape (work
list / `describe_artifact.py --keys/--field` / producer stdout). The rule SHALL fire regardless of
whether the inline body contains introspection tokens in the heredoc form — an inline
interpreter body is ad-hoc processing by shape, and token sniffing inside heredoc payloads is
unreliable; for `-c` bodies the existing token-based discrimination is retained unchanged.
A command that merely runs a script whose stdout is piped into a **non-interpreter** consumer
(e.g. `py … | tail -5`) SHALL NOT trip this rule (piping per se is governed by the
redirect/temp-io rules). Both host faces share the single Python guard (opencode `.ts` shim
unchanged — it normalizes the event, never judges), so double-side parity is guaranteed by the
existing parity test contract; regression cases SHALL include the exact real-machine shapes
`python3 <script> --flags 2>/dev/null | python3 - <<'EOF'` and `py - <<<"$code"`.

#### Scenario: heredoc-fed introspection is blocked

- **WHEN** an mgh run-domain is active and the agent issues
  `python3 sdr_context.py --repo … | python3 - <<'EOF'\nimport sys,json; json.load(sys.stdin)\nEOF`
- **THEN** the guard blocks with exit 2 + the sanctioned-primitive recipe (previously the payload
  passed: the `-c` regex did not match a standalone `-`, so the model got negative reinforcement
  that "inline python works")

#### Scenario: here-string form is blocked

- **WHEN** the agent issues `py - <<<"import json; print(json.load(open('x.json')))"` inside an
  active run-domain
- **THEN** the guard blocks with exit 2 + the same recipe

#### Scenario: -c token discrimination unchanged

- **WHEN** the agent issues `py -c "print('hello')"` (no introspection tokens) inside an active
  run-domain
- **THEN** behavior is exactly as before this requirement (token-based rule unchanged; no new
  false positive on benign `-c` bodies)

#### Scenario: pipe to a shell utility is not an inline interpreter

- **WHEN** the agent issues `py <in-tree script> --summary | tail -5` inside an active run-domain
- **THEN** this rule does not fire (`tail` is not an interpreter receiving code); path-side rules
  still judge any path tokens as before

## MODIFIED Requirements

### Requirement: sdr 域哨兵的确定性写入、存在性校验与重写

`mgh-sdr` 域哨兵 `<repo>/.mgh-sdr/.active` SHALL 由**确定性脚本副作用**写入,分**两级时序**:

- **step 0 预武装**:`resume_sdr_state.py --run-dir <abs> --repo <abs> --arm-sentinel` 在编排器首次
  调用 `sdr_context.py` **之前**写最小哨兵,JSON 为
  `{"domain":"mgh-sdr","target":"<--repo 绝对路径,Windows 原生>","out_roots":[],"read_roots":[],"v":1}`。
  幂等:哨兵已存在且 `target` 相同 → 逐字不变(NEVER 清空已被细化的 `read_roots[]`);`target` 不同 →
  退出码 2 + 报错(拒绝把守卫锚到第二棵树)。`--repo` 缺失且无法从 `<run-dir>` 布局推导 → 退出码 2 +
  recipe。
- **step 1 细化**:`sdr_context.py` 完成基线投影与外部仓检索后 co-write 完整哨兵,`read_roots[]` =
  实际检索过且存在为目录的根 ∪ 操作者 `--read-root` / `--approve-external` 确认后实际检索的根
  (最小化原则不变),SHALL NOT 透传任意路径。

两级均 SHALL NOT 依赖编排器读懂并执行 `Bash printf` 配方(脚本一跑哨兵必在)。

`mgh_sdr_launch.py` 保留的哨兵写入 SHALL 为**幂等刷新**(它在 spawn 宿主 CLI 之前,对已确认根再做一次
项目配置复核 + 并入操作者 `--read-root`,作为版本错配的第二道闸门),与 `sdr_context` 的 co-write 同语义、
同内容来源;两处均 SHALL NOT 写入未确认根。

`resume_sdr_state.py --check` SHALL 在「run 进行中而哨兵缺失」时 fail-loud:`context.json` 存在且
`step ∈ {group, fanout, render}`(已有工作产物、守卫却休眠 = 脚本只读 / 子树限定静默失效)而
`<repo>/.mgh-sdr/.active` 不存在 → 退出码 2 + re-arm recipe,NEVER 静默继续。`step == "done"`(run 已收尾)
时哨兵缺失 SHALL NOT 视为违例(守卫本就应当休眠)。`step == "not-started"`(尚无产物)时 SHALL 仅
advisory 披露,不作 gate;**预武装已发生而 `context.json` 未写出**(step 1 失败窗口)属该 advisory
分支的正常形态,`--check` SHALL NOT 因此失败。

`--rearm-sentinel` SHALL 据磁盘**确定性**重写该哨兵:`target` 取 `context.json::repo`,
`read_roots[]` 取 `context.json::external_repos[].path`(存在且为目录者),`domain` 恒为 `mgh-sdr`,
`out_roots` 为 `[]`;路径 SHALL 由 Python 叶脚本产出(Windows 原生形态),SHALL NOT 取自 shell 的 MSYS 形态
(`/c/…`)。重写 SHALL 幂等(同一磁盘状态 → 逐字相同文件)。`--arm-sentinel` 与 `--rearm-sentinel` 的
语义差异 SHALL 固定为:前者面向 run **起点**(空 `read_roots`、以 `--repo` 为 target 来源),后者面向
run **中途** re-arm(以 `context.json` 为唯一真相源);两者对同一磁盘状态 NEVER 产出互相覆盖冲突的
内容(起点覆盖中途不发生,中途重写在 context.json 缺失时退出码 2 + 指向 `--arm-sentinel`)。

#### Scenario: 预武装在 step 1 之前闭合失败窗口

- **WHEN** 编排器 step 0 执行 `resume_sdr_state.py --run-dir <abs> --repo <abs> --arm-sentinel`,随后
  首次 `sdr_context.py` 调用因未知 flag 在 argparse 即失败
- **THEN** `<repo>/.mgh-sdr/.active` 已存在(`read_roots:[]`、`target` 正确),守卫对该 run 目录树内的
  后续违规动作保持激活——此前该窗口守卫休眠

#### Scenario: sdr_context 跑完哨兵必在

- **WHEN** 编排器 step 0 预武装之后执行 `sdr_context.py --repo <abs> --run-dir <abs>`(无论经 launcher 还是经宿主会话)
- **THEN** `<repo>/.mgh-sdr/.active` 已存在,`domain="mgh-sdr"`、`target` 为 Windows 原生绝对路径、
  `read_roots[]` 为实际检索过的根;哨兵不依赖编排器执行任何 `printf` 配方

#### Scenario: 预武装幂等不覆盖已细化根

- **WHEN** step 1 已把 `read_roots[]` 细化为两个根后,编排器(压缩重入)再次执行同一 `--arm-sentinel`
- **THEN** 哨兵文件逐字不变,两个已声明根 NEVER 被清空

#### Scenario: 进行中缺哨兵即 fail-loud

- **WHEN** 某 sdr run 已有 `context.json` 与 `grouping.json`(step = fanout),但 `<repo>/.mgh-sdr/.active` 被误删
- **THEN** `resume_sdr_state.py --check --run-dir <abs>` 退出码 2,violations 载明「守卫休眠」+ re-arm recipe
  (`resume_sdr_state.py --rearm-sentinel --run-dir <abs>`);NEVER 静默继续

#### Scenario: 收尾后哨兵缺失非违例

- **WHEN** run 已收尾(`sdr_manifest.json` 在)、哨兵已在收尾步被移除
- **THEN** `--check` 退出码 0,无哨兵相关 violation

#### Scenario: re-arm 由磁盘确定性重写且幂等

- **WHEN** 对同一 run 目录连续两次执行 `--rearm-sentinel`
- **THEN** 两次写出的哨兵内容逐字相同;`target` / `read_roots[]` 全部由 Python 产出(无 MSYS `/c/…` 形态)

#### Scenario: re-arm 只认实际检索过的根

- **WHEN** `context.json::external_repos[]` 含两个根,其一在磁盘上已不存在
- **THEN** 重写后的 `read_roots[]` 只含仍然存在且为目录的那一个,NEVER 写入不存在的路径

#### Scenario: context.json 缺失时 rearm 指向 arm

- **WHEN** step 1 从未成功(`context.json` 不存在)而对某 run 目录执行 `--rearm-sentinel`
- **THEN** 退出码 2,stderr recipe 指明「run 未起步 → 用 `--arm-sentinel --repo <abs>` 预武装」,NEVER
  静默写出空 target 哨兵
