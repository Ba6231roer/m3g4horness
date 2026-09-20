## ADDED Requirements

### Requirement: sdr 域哨兵的确定性写入、存在性校验与重写

`mgh-sdr` 域哨兵 `<repo>/.mgh-sdr/.active` SHALL 由**确定性脚本副作用**写入——`sdr_context.py` 完成基线
投影与外部仓检索后 co-write,JSON 为
`{"domain":"mgh-sdr","target":"<repo 绝对路径,Windows 原生>","out_roots":[],"read_roots":["<实际检索过的外部根绝对路径>…"],"v":1}`;
SHALL NOT 依赖编排器读懂并执行 `Bash printf` 配方(脚本一跑哨兵必在)。`read_roots[]` SHALL 取
`context.json::external_repos[].path` 中实际存在且为目录的条目(即**实际检索过的根** + 操作者经
`--read-root` 显式确认的根,最小化原则),SHALL NOT 透传任意路径。

`mgh_sdr_launch.py` 保留的哨兵写入 SHALL 为**幂等刷新**(它在 spawn 宿主 CLI 之前,对已确认根再做一次
项目配置复核 + 并入操作者 `--read-root`,作为版本错配的第二道闸门),与 `sdr_context` 的 co-write 同语义、
同内容来源;两处均 SHALL NOT 写入未确认根。

`resume_sdr_state.py --check` SHALL 在「run 进行中而哨兵缺失」时 fail-loud:`context.json` 存在且
`step ∈ {group, fanout, render}`(已有工作产物、守卫却休眠 = 脚本只读 / 子树限定静默失效)而
`<repo>/.mgh-sdr/.active` 不存在 → 退出码 2 + re-arm recipe,NEVER 静默继续。`step == "done"`(run 已收尾)
时哨兵缺失 SHALL NOT 视为违例(守卫本就应当休眠)。`step == "not-started"`(尚无产物)时 SHALL 仅
advisory 披露,不作 gate。

`--rearm-sentinel` SHALL 据磁盘**确定性**重写该哨兵:`target` 取 `context.json::repo`,
`read_roots[]` 取 `context.json::external_repos[].path`(存在且为目录者),`domain` 恒为 `mgh-sdr`,
`out_roots` 为 `[]`;路径 SHALL 由 Python 叶脚本产出(Windows 原生形态),SHALL NOT 取自 shell 的 MSYS 形态
(`/c/…`)。重写 SHALL 幂等(同一磁盘状态 → 逐字相同文件)。

#### Scenario: sdr_context 跑完哨兵必在

- **WHEN** 编排器 step 0 之后执行 `sdr_context.py --repo <abs> --run-dir <abs>`(无论经 launcher 还是经宿主会话)
- **THEN** `<repo>/.mgh-sdr/.active` 已存在,`domain="mgh-sdr"`、`target` 为 Windows 原生绝对路径、
  `read_roots[]` 为实际检索过的根;哨兵不依赖编排器执行任何 `printf` 配方

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
