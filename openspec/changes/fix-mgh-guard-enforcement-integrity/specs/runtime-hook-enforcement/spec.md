## MODIFIED Requirements

### Requirement: Bash write-verb confinement to the MGH_TARGET tree

When active, the guard SHALL scan each `Bash` command for a leading **write verb** — `New-Item`/`ni`,
`Set-Content`/`sc`, `Add-Content`/`ac`, `Out-File`, `tee`, `mkdir`/`md`, `Copy-Item`/`cpi`/`cp`/`copy`/`xcopy`,
`Move-Item`/`mi`/`mv`/`rename`/`Rename-Item` (or the same verb as the first token of a sub-command after
`;`/`|`/`&&`/`||`) — and, on a hit, SHALL block when EITHER (a) the write **destination** resolves outside the
`MGH_TARGET` tree (for single-path verbs any out-of-tree absolute-path token; for `Copy-Item`/`Move-Item`/`xcopy` the
LAST absolute-path token = the destination), OR (b) the command carries no explicit absolute path (destination
defaults to cwd) AND the guard's cwd resolves outside the `MGH_TARGET` tree. A hit SHALL fail-loud (exit 2) + the
write-side recipe. `MGH_TARGET` resolves with the same precedence as the read/write sides (env > sentinel.`target` >
degrade-pass). This closes the bypass where the model, instead of using the native `Write`/`Edit` tool (whose target
is already confined by the existing write-confinement rule), invokes a file-write verb directly in `Bash` (which routes
through the `Bash` branch, and the existing Bash rules — `py -c` introspection / temp-I/O / aggregate-read / file-assoc /
file-search — do not target out-of-tree write paths). The detection is regex-over-observed-shape and SHALL NOT claim
exhaustive coverage of every write form (pipes, aliases, env-injected paths, PowerShell `.NET` static methods like
`[System.IO.File]::WriteAllText`, `robocopy`/`fsutil` are not guaranteed) — consistent with the temp-I/O,
file-association, and read-side Bash file-search rules.

**写目的地判定的域分派(与各自 Write/Edit 工具面逐字镜像)**:对 `mgh-init`/`mgh-ut-init`(受信子树
allowlist 域),一个**树外**目的地经哨兵 `out_roots[]` 豁免——落在某个 out_root 内则放行(与
Write/Edit 工具层 `_allowlist_write_blocked` 同一查询、同一来源;定制 `--out`/`--rules-dir` 绝对根是
合法写目的地);树内目的地照旧走受信子树 P1。对 sast/sra/srr/sdr(无 allowlist 域),树外目的地一律
拦——它们的 Write/Edit 工具面同样不咨询 `out_roots`,Bash 写动词面与之镜像,NEVER 出现「同一目的地、
工具面拦、Bash 面放行」(或反向)的入口翻转。**`read_roots`(哨兵与项目配置)在任何写面永不豁免**:
已声明的只读根是读侧概念,写入它(任何动词、任何面)SHALL 拦 + 写侧 recipe。

#### Scenario: Bash Set-Content to an out-of-tree path is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Set-Content D:\out\f.json "x"` (the Write/Edit tool's confinement is bypassed by invoking a write verb directly
  in Bash with an out-of-tree path)
- **THEN** the guard scans the absolute-path token `D:\out\f.json`, resolves it outside the target tree, and blocks
  with exit 2 + the write-side recipe — the out-of-tree write does not silently execute

#### Scenario: Bash New-Item creating an out-of-tree file/dir is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `New-Item -ItemType File -Path D:\out\f.json -Force` (or `-ItemType Directory -Path D:\out\d`)
- **THEN** the guard resolves the `-Path` token outside the target tree and blocks with exit 2 + the write-side recipe

#### Scenario: Bash mkdir of an out-of-tree directory is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `mkdir D:\out\d`
- **THEN** the guard blocks with exit 2 + the write-side recipe

#### Scenario: Bash Copy-Item destination outside the target tree is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Copy-Item x.java D:\out\` (the LAST absolute-path token = destination, outside the target tree)
- **THEN** the guard resolves the destination token outside the target tree and blocks with exit 2 + the write-side
  recipe; the in-tree source token does not exempt the out-of-tree destination

#### Scenario: Bash Copy-Item into a sentinel out_root passes (init, tool-face mirror)

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA` and the sentinel declares
  `out_roots:["D:\custom\out"]` (a customized `--out` absolute root), and the model issues `Bash`
  `Copy-Item x.json D:\custom\out\x.json`
- **THEN** the guard consults `out_roots` on the out-of-tree destination (the same query the Write/Edit tool
  layer's allowlist makes), finds it inside a sanctioned write root, and passes (exit 0) — the three write
  entry points (Write/Edit tool, Bash write verb, redirect) reach the SAME verdict for the same destination

#### Scenario: Bash write verb with no path and cwd outside target is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, the model's cwd is `D:\parent`
  (outside the target tree), and the model issues `Bash` `Set-Content evil.txt "x"` (relative path resolves under
  cwd, i.e. the parent tree)
- **THEN** the guard finds no explicit absolute path, resolves the implicit cwd anchor outside the target tree, and
  blocks with exit 2 + the write-side recipe — the cwd-drift write leak is caught

#### Scenario: Bash write verb anchored inside the target tree passes

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `Set-Content D:\parent\sonA\.mgh-init\report\out.json "x"` (inside a sanctioned init subtree)
- **THEN** the guard passes (exit 0); legitimate in-tree writes via Bash (inside sanctioned subtrees for init/ut-init)
  are unaffected

#### Scenario: Bash write into a declared read root is blocked (read roots are never writable)

- **WHEN** an `mgh-sdr` run-domain is active with sentinel `read_roots:["D:\work\front"]`, and the model issues
  `Bash` `Set-Content D:\work\front\x.js "v"`
- **THEN** the write destination judgment consults only `MGH_TARGET` (+ allowlist `out_roots` where applicable),
  finds the declared read root outside both, and blocks with exit 2 + the write-side recipe — a declared read-only
  root NEVER becomes writable on any write face

#### Scenario: Bash non-write command is not affected by the write-verb rule

- **WHEN** an `mgh-init` run-domain is active and the model issues `Bash` `py "…list_clusters.py" --out
  "D:\parent\sonA\.mgh-init\clusters.json"` (no write verb; the `.json` path is a `--flag` argument to a
  producer, which writes inside the sanctioned subtree itself)
- **THEN** the guard does not apply the write-verb rule (other Bash rules — script-as-arg — still apply as before);
  a path that is only a `--flag` argument to a non-write-verb command is not a write-verb hit

#### Scenario: Active domain with no pinned target degrades the write-verb check

- **WHEN** the guard is active but `MGH_TARGET` env is unset AND the sentinel carries no `target`, and the model
  issues `Bash` `Set-Content D:\out\f.json "x"`
- **THEN** the script-extension write block / `py -c` introspection block / temp-I/O / file-association /
  aggregate-read blocks still fire (exit 2) where applicable; the write-verb out-of-tree check **degrades to pass**
  (NEVER use cwd as a hard block target when no target was pinned, consistent with the read/write sides' degrade rule)

#### Scenario: Inactive session passes Bash write verbs

- **WHEN** neither any `MGH_*_ACTIVE` env nor any `<run-root>/.active` sentinel is present and the model issues
  `Bash` `Set-Content D:\anywhere\f.json "x"`
- **THEN** the guard exits 0 silently (zero day-to-day noise; install/CI/dev unaffected)

### Requirement: Bash redirect confinement to the MGH_TARGET tree

When active, the guard SHALL detect a `>`/`>>` redirect in a `Bash` command whose target resolves OUTSIDE the
`MGH_TARGET` tree (generalizing the prior temp-only redirect rule, which matched only known temp-dir prefixes) and
SHALL block it (exit 2) + the write-side recipe — **对全部六域生效**:无 allowlist 的 sast/sra/srr/sdr 与
init/ut-init 同判(树外 redirect 从非「无白名单即放行」;该形态曾是树外拦截分支上的不可达死代码)。
对 `mgh-init` AND `mgh-ut-init`,树外目的地经哨兵 `out_roots[]` 豁免(与 Write/Edit 工具层 allowlist 同
一查询)、树内目的地 SHALL additionally land inside a sanctioned subtree (positive allowlist), mirroring the
Write/Edit tool-layer rule — so a redirect that pollutes the target root (`echo x > D:\parent\sonA\evil.txt`) fails
loud too. The prior temp-dir write + read-back defense (`_detect_temp_io`) is retained as an independent defense;
this rule adds the out-of-tree / non-sanctioned-subtree axis. `MGH_TARGET` resolves with the same precedence
(env > sentinel.`target` > degrade-pass). **`read_roots` 永不豁免 redirect 目的地**(写入声明只读根 =
拦 + 写侧 recipe)。

#### Scenario: Bash redirect to an out-of-tree non-temp path is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `echo x > D:\out\f.json` (a non-temp out-of-tree redirect the prior temp-only rule did not match)
- **THEN** the guard resolves the redirect target `D:\out\f.json` outside the target tree and blocks with exit 2 +
  the write-side recipe

#### Scenario: Bash append redirect to an out-of-tree path is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `echo x >> D:\out\f.json`
- **THEN** the guard blocks with exit 2 + the write-side recipe

#### Scenario: Bash redirect to an out-of-tree path is blocked in a no-allowlist domain too

- **WHEN** an `mgh-sdr`(或 sast/sra/srr)`run-domain` is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash` `echo x > D:\out\f.json`
- **THEN** the guard resolves the redirect target outside the target tree and blocks with exit 2 + the write-side
  recipe(修复前 `_redirect_in_sanctioned` 对无 allowlist 域早真放行,该分支不可达——四域 redirect 越树
  整体无拦截,兜底净网报的还是读侧 recipe)

#### Scenario: Bash redirect into a declared read root is blocked (read roots never writable)

- **WHEN** an `mgh-sdr` run-domain is active with sentinel `read_roots:["D:\work\front"]`, and the model issues
  `Bash` `echo x > D:\work\front\f.js`(目的地在声明的只读根内——兜底净网也在允许集内)
- **THEN** the guard blocks with exit 2 + the write-side recipe(修复前该形态全链路 exit 0 放行,直接违反
  「声明只读根永不可写」)

#### Scenario: Bash redirect to a sentinel out_root passes (init)

- **WHEN** an `mgh-init` run-domain is active with the sentinel declaring `out_roots:["D:\custom\out"]`, and the
  model issues `Bash` `echo x > D:\custom\out\f.json`
- **THEN** the guard consults the allowlist (subtrees ∪ out_roots), finds the destination inside a sanctioned
  write root, and passes (exit 0) — 与 Write/Edit 工具面对同一目的地同一结论

#### Scenario: Bash redirect polluting the target root is blocked (init allowlist)

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `echo x > D:\parent\sonA\evil.txt` (in-tree but at the target root, outside the sanctioned init subtrees)
- **THEN** the guard applies the init positive allowlist to the redirect target, finds it outside the sanctioned
  subtrees, and blocks with exit 2 + the write-side recipe — Bash-side root pollution is caught like the Write-tool
  allowlist catches it

#### Scenario: Bash redirect to a sanctioned in-tree path passes

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model issues `Bash`
  `echo x > D:\parent\sonA\.mgh-init\report\out.json` (inside a sanctioned init subtree)
- **THEN** the guard passes (exit 0); legitimate in-tree redirects are unaffected

#### Scenario: Bash temp write + read-back still blocked by the retained temp-I/O rule

- **WHEN** an `mgh-init` run-domain is active and the model issues `Bash` `echo x > $env:TEMP\t.json; Get-Content
  $env:TEMP\t.json`
- **THEN** the retained `_detect_temp_io` defense still fires (exit 2 + the temp-I/O recipe), independent of the
  generalized redirect rule

### Requirement: Bash interpreter script-execution confinement to the MGH_TARGET tree

When active with a pinned target, the guard SHALL block a `Bash` command that invokes an
**interpreter** (`py`, `py3`, `python`, `python3`, `python2`) leading a simple command (FIRST
token or after a delimiter) where the **first script-extension argument** (any `_SCRIPT_EXTS`
member) resolves **outside** the `MGH_TARGET` tree. The script path is judged at the
**positional-argument** face only — `--flag <path>` arguments (e.g. `--checkpoints <in-tree>`)
are NOT the executed script and SHALL NOT trip; a `py -c`/`py -m` body is NOT judged here (its
read/write shapes are already governed by the existing introspection/write-relabel rules) —
**该排除对带空格与粘连两种形态一律生效**:解释器名后出现 `-c` 或 `-m`(无论 `py -c "…"` 的空格形还是
`py-c` 粘连形)即非「执行脚本」形态,本规则 SHALL 退出,其后的 token(内联 body 的参数,如
`py -m pytest <树外 test_x.py>` 或 `py -c "…" <路径>`)SHALL NOT 被当作被执行脚本判定(修复前仅无空格
粘连形被负向前瞻排除,空格形下尾随 `.py` 参数被误当执行脚本拦截——误拦面,非漏拦面)。
This closes the bypass where `py /home/user/other/repo/script.py` (or any interpreter-run script
outside the project) executes while the no-launcher file-association rule passes it for carrying
an explicit interpreter prefix. A hit SHALL fail-loud (exit 2) + a recipe pointing at the
in-tree installed script path (`py .claude/mgh-core/scripts/<script>.py …`); in-tree interpreter
executions are unaffected. Target absent => degrade to pass.

#### Scenario: interpreter running an out-of-tree script is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=/adhome/u/proj/sub_proj`, and the
  agent issues `py /home/someone/other/run.py` or `python3 ~/tools/scan.py`
- **THEN** the guard resolves the first script-extension argument outside the target tree and
  blocks with exit 2 + the interpreter-exec recipe (previously passed — the explicit launcher
  prefix exempted it from the file-association rule and no other rule judged the script location)

#### Scenario: interpreter running an in-tree script passes

- **WHEN** the guard is active with a pinned target and the command is
  `py .claude/mgh-core/scripts/resume_state.py --target .` (script arg resolves in-tree)
- **THEN** the guard passes (exit 0); all sanctioned deterministic-script invocations are
  unaffected

#### Scenario: --flag path arguments are not judged as the executed script

- **WHEN** the guard is active with a pinned target and the command is
  `py <target>/.mgh-core/scripts/list_clusters.py --clusters <in-tree>.json`
- **THEN** the guard judges the first positional script-extension argument (the script itself,
  in-tree) and passes — a `--flag <in-tree path>` never trips even though it names a path

#### Scenario: py -c bodies are not judged by this rule

- **WHEN** the guard is active with a pinned target and the command is
  `py -c "import json; open('/home/x/f.json').read()"`
- **THEN** this rule does not fire (no script-extension positional argument); the existing
  introspection rule blocks it with its own recipe

#### Scenario: trailing arguments after a spaced -m are not the executed script

- **WHEN** the guard is active with a pinned target, and the command is
  `py -m pytest D:\out\test_something.py`(模块调用,`.py` 是 pytest 的参数)或
  `py -c "import x" /home/x/helper.py`(内联 body 的数据参数)
- **THEN** this rule does not fire(修复前空格形 `-m`/`-c` 未被排除,尾随 `.py` 被误当执行脚本,
  树外即误拦;内省/写重标记规则照常拥有这些 body)

### Requirement: mgh-core missing-install detection stops all tasks

When active, the guard SHALL intercept a `Bash` command that references an installed mgh-core
script path (a path segment `mgh-core/scripts/` AND a script extension) whose resolved location
is **absent on disk** or **outside the `MGH_TARGET` tree**, and fail-loud (exit 2) with a
**stop-all recipe**: `mgh-core is not installed in this target — STOP ALL TASKS (do not
continue the run), report to the USER that mgh-init must be installed in the CURRENT project
directory (run install), and NEVER search other directories (parent project, /home, /adhome,
siblings) for scripts or prompts.` This encodes the observed multi-project failure shape: mgh-core
installed only in the root project while the run executes in an independent sub-project — scripts
404, and the model's natural response is cross-directory wandering. The rule SHALL fire on the
first such reference in any Bash command (the missing-install face is terminal for the run; there
is no sanctioned continuation). Non-script or non-mgh-core references are unaffected; the guard
SHALL NOT probe the filesystem beyond the referenced paths themselves.
**搜索动词的模式操作数豁免**:文件搜索动词(rg/ripgrep/grep/egrep/fgrep/findstr/find/fd/ag/ack)引导的
简单命令中,其**首个非旗标操作数**是搜索模式而非磁盘引用——`grep -n "mgh-core/scripts/run.py" notes.md`
的引号内字符串是 pattern,SHALL NOT 触发本规则(stop-all 是最重阻断,不得被字符串字面量误触);读动词
(cat/type/Get-Content/gc)的操作数是磁盘路径,照常判定(读侧不走此豁免)。

#### Scenario: mgh-core script referenced but not installed under the target is blocked with stop-all recipe

- **WHEN** mgh-core is installed only in the root project while the run's target is an
  independent sub-project (no `mgh-core/` anywhere under the target), and the agent issues
  `py .claude/mgh-core/scripts/resume_state.py --target .`
- **THEN** the guard resolves the referenced mgh-core script path, finds it absent (or outside the
  target), and blocks with exit 2 + the stop-all recipe (stop all tasks; ask the user to install
  in the current project directory; NEVER search other directories)

#### Scenario: installed mgh-core script reference passes

- **WHEN** mgh-core is installed under the target and the agent issues
  `py .claude/mgh-core/scripts/list_clusters.py …`
- **THEN** the guard passes (exit 0); the normal deterministic-script workflow is unaffected

#### Scenario: non-mgh-core missing paths do not trip this rule

- **WHEN** the guard is active and the command references an in-tree user script that happens not
  to exist (no `mgh-core/scripts` segment), or a project source file
- **THEN** this rule does not fire (existence of arbitrary non-product paths is the caller's
  concern, not the guard's)

#### Scenario: a search verb's pattern operand does not trip the stop-all rule

- **WHEN** the guard is active and the command is `grep -n "mgh-core/scripts/run.py" notes.md`
  (the quoted string is grep's PATTERN; notes.md is an in-tree operand)
- **THEN** this rule does not fire(修复前引号剥离后该字符串被当磁盘引用 → 解析缺失 → stop-all 误拦,
  最重阻断被字符串字面量触发);`notes.md` 等真实操作数照常由其它规则判定

### Requirement: Bash path-token allowlist judgment (verb-independent fail-closed net)

When active with a pinned target, the guard SHALL judge EVERY path-like token in each `Bash`
command against the unified read allow-set — the resolved `MGH_TARGET` tree ∪ sentinel
`read_roots[]` ∪ project config `read_roots[]` — **regardless of which verb (if any) leads the
command**: any token that resolves outside ALL of them SHALL block (exit 2) with a recipe naming
the allowed read roots. Path-like tokens are: Windows drive-letter absolute (`C:\…`/`C:/…`), UNC
(`\\…`), POSIX absolute (`/…`), `..`-leading relative tokens (resolved against the guard's cwd),
and `~`-leading path tokens (bare `~` alone is not judged); tokens that are part of a URL
(`<word>://…`) SHALL be excluded from judgment. **Glob-form tokens**: a path-like token
containing glob metacharacters (`*`/`?`) SHALL be judged by its **glob-free prefix** (everything
before the first metacharacter); a glob segment that **directly abuts a quote-closed absolute
path** (`"C:\t"/*.html` or `"C:\t"\*.log`) SHALL be joined with that path into one logical token
before extraction (without the join, the closing quote ends the token and the glob fragment is
misread as a bare `/…` absolute path that resolves to the drive root — a false out-of-tree hit);
a glob whose prefix resolves outside the allow-set (`D:\other\*.log`) remains a block. This
glob-form semantics SHALL apply to EVERY Bash absolute-path-token judgment in the guard
(file-search, directory-listing, write/delete/redirect, and this net), so all rules judge the
same normalized token stream. **token 的左边界字符集含重定向字符 `<` 与 `>`**:无空格
重定向形态(`echo x >D:/out/f`)的路径 token SHALL 可被提取判定(修复前边界类缺这两个字符,紧贴 `>` 的
路径提取不到 → 净网漏拦,与 redirect 规则联动时彻底无拦截)。A command carrying no path-like token SHALL
pass this rule (all other rules still apply to it). This judgment SHALL run AFTER the mutation rules
(write/delete verbs, redirects, `py -c` write-shape relabel) so mutation-shaped hits surface
their specific write/delete recipes, and alongside/after the existing verb-triggered read rules
(file-search, listing, interpreter-exec, mgh-core missing-install), which REMAIN IN FORCE as
refinements — this rule is the structural fail-closed net under them, closing the
"verb not in the enumeration table" escape class (`robocopy`, `curl -o`, `.NET` static write
methods, `Get-Content <out-of-tree file>`, `Expand-Archive`, …). Target unpinned => this rule
degrades to pass (mirror of every other path rule; never a hard block when no target was pinned).

#### Scenario: Unknown mutation verb with an out-of-tree destination is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash: robocopy D:\parent\sonA\docs D:\backup` (the write verb `robocopy` is in NO
  enumeration table)
- **THEN** the guard judges the path tokens, finds `D:\backup` outside the target tree, and
  blocks with exit 2 + a recipe naming the allowed roots (previously passed — no enumerated verb
  matched)

#### Scenario: Direct read of an out-of-tree file is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash: Get-Content D:\parent\sonB\notes.json` (a plain read verb, not a search/listing
  verb; previously passed every rule)
- **THEN** the guard resolves the path token outside the target tree and blocks with exit 2 +
  the recipe

#### Scenario: In-tree command passes untouched

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash: py .claude/mgh-core/scripts/list_clusters.py --out D:\parent\sonA\.mgh-init\c.json`
- **THEN** the guard passes (exit 0) — every path token resolves inside the target tree; the
  sanctioned deterministic-script workflow is unaffected

#### Scenario: no-space redirect form extracts its path token

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and the model
  issues `Bash: echo x >D:/out/f`(重定向符与路径间无空格)
- **THEN** the guard extracts `D:/out/f` as a path token(左边界含 `>`),resolves it outside the
  target tree and read allow-set, and blocks with exit 2 + the recipe(修复前该形态提取不到
  token,净网漏拦)

#### Scenario: `..`-climbing relative token is blocked

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA` (guard cwd inside
  the tree), and the model issues `Bash: type ..\..\secret.txt` (cwd-relative resolution climbs
  out of the tree)
- **THEN** the guard resolves the `..`-leading token against the cwd, finds it outside the tree,
  and blocks with exit 2 + the recipe

#### Scenario: URL token does not false-trip

- **WHEN** an `mgh-init` run-domain is active with a pinned target, and the model issues
  `Bash: py .claude/mgh-core/scripts/tool.py --doc https://example.com/a/b`
- **THEN** the guard passes (exit 0) — the `s://…` fragment of the URL is excluded from
  path-token judgment (URL-scheme exclusion), so no false block

#### Scenario: Write-shaped hit into a declared read root surfaces the write recipe, not the read net

- **WHEN** an `mgh-sdr` run-domain is active with sentinel `read_roots:["D:/work/front"]`, and
  the model issues `Bash: Set-Content D:/work/front/x.js "v"` (a known write verb targeting a
  declared read-only root)
- **THEN** the mutation rules run FIRST, judge the destination against `MGH_TARGET` alone, and
  block with exit 2 + the write-side recipe (the read-net's allow-set never relaxes a write)

#### Scenario: Unpinned target degrades the token judgment to pass

- **WHEN** the guard is active but neither env nor sentinel pins a target, and the model issues
  `Bash: cat D:\anywhere\f.txt`
- **THEN** the token judgment degrades to pass (exit 0); the script-extension write block,
  `py -c` introspection block, temp-I/O, file-association, and mgh-core missing-install rules
  still fire where applicable

#### Scenario: Quoted in-tree path abutting a glob fragment passes

- **WHEN** an `mgh-sdr` run-domain is active with `MGH_TARGET=C:\DEV\springBootTemplate`, and
  the model issues the repo-root report-discovery command
  `ls -la "C:\DEV\springBootTemplate" | grep -i "mgh-sdr" ; ls "C:\DEV\springBootTemplate"/*.html`
- **THEN** the guard passes (exit 0): the glob segment `/*.html` abuts the quote-closed in-tree
  path and is joined with it before judgment (joined prefix in-tree), and the pipe/sub-command
  tokens all resolve inside the target tree — previously this exact form was a false
  out-of-tree block that burned host retry rounds

#### Scenario: Out-of-tree glob prefix is still blocked

- **WHEN** an `mgh-sdr` run-domain is active with `MGH_TARGET=C:\DEV\springBootTemplate`, and
  the model issues `Bash: ls "D:\other\repo"/*.html` (glob abutting an out-of-tree quoted path)
- **THEN** the guard joins the glob with its quoted prefix, resolves the prefix outside the
  target tree, and blocks with exit 2 + the recipe (the join is a false-positive fix, NEVER a
  read-side relaxation)

### Requirement: Leaf script source read blocked (read-side peer of scripts read-only)

When active in an mgh run-domain, the guard SHALL block a `Read` whose resolved `file_path` is a
script-extension file (extension in `{.py, .ps1, .sh, .bash, .zsh, .bat, .cmd, .ts, .js, .mjs, .cjs}`)
located under the installed `<mgh-core>/scripts/` mirror of the target project (both
`.claude/mgh-core/scripts/` and `.opencode/mgh-core/scripts/` install layouts) — fail-loud (exit 2)
+ a recipe pointing at "report errors from stderr, NEVER Read leaf script source". This is the
read-side peer of the existing "leaf scripts read-only" write rule: leaf scripts are already
write-blocked at runtime; this closes the remaining context-bloat path where the orchestrator or a
subagent pulls a leaf `.py` (200–900 lines ≈ 3–10K tokens) into their context to "debug" a `--check`
failure, which accelerates compaction and risks the agent reasoning about internals. The block
SHALL NOT apply to the target project's own `.py` source (only the installed mgh-core leaf scripts,
identified by the `mgh-core/scripts` path segment); it SHALL NOT apply to `Read` of non-script
artifacts (`.json`/`.md`). **路径段比较 SHALL 大小写不敏感**(Windows 文件系统大小写不敏感;
`.CLAUDE/Mgh-Core/Scripts/…` 变体与规则 l 的 IGNORECASE 正则同判,SHALL NOT 经大小写变体绕过)。
When the guard is inactive (no env, no sentinel), the read SHALL pass
(install/CI/dev unaffected).

#### Scenario: Reading a leaf .py during a run is blocked

- **WHEN** an `mgh-init` run-domain is active (env `MGH_INIT_ACTIVE=1` OR `<cwd>/.mgh-init/.active`
  sentinel present), and the model issues `Read`
  `file_path=D:\parent\sonA\.claude\mgh-core\scripts\list_clusters.py`
- **THEN** the guard resolves the path under `mgh-core/scripts/` with a script extension and blocks
  with exit 2 + a recipe ("report errors from stderr, NEVER Read leaf script source") — the leaf
  source does not enter context

#### Scenario: Reading a leaf .py via a Windows case variant is blocked

- **WHEN** an `mgh-init` run-domain is active, and the model issues `Read`
  `file_path=D:\parent\sonA\.CLAUDE\Mgh-Core\Scripts\list_clusters.py`(同一文件的 casing 变体)
- **THEN** the guard compares the path segments case-insensitively, still identifies the
  `mgh-core/scripts` segment + script extension, and blocks with exit 2 + the same recipe
  (修复前大小写敏感比较使该变体绕过)

#### Scenario: Reading the target project's own .py passes

- **WHEN** an `mgh-init` run-domain is active with `MGH_TARGET=D:\parent\sonA`, and a reader issues
  `Read` `file_path=D:\parent\sonA\src\auth\PermGuard.java` or `D:\parent\sonA\src\auth\PermGuard.py`
- **THEN** the guard passes (exit 0) — the block targets only installed mgh-core leaf scripts, not
  the working project's source

#### Scenario: Reading a script-extension file outside mgh-core passes

- **WHEN** an `mgh-init` run-domain is active, and the model issues `Read` of a `.py` that is NOT
  under a `mgh-core/scripts` path segment (e.g. a vendored `D:\parent\sonA\tools\helper.py`)
- **THEN** the guard passes (exit 0) — the path-segment condition is the discriminator, not the
  extension alone

#### Scenario: Inactive session passes leaf-script reads

- **WHEN** neither any `MGH_*_ACTIVE` env nor any `<run-root>/.active` sentinel is present and the
  model issues `Read` of `mgh-core/scripts/list_clusters.py`
- **THEN** the guard exits 0 silently (zero day-to-day noise; install/CI/dev unaffected)

### Requirement: Bash inline interpreter code blocked in all feeding forms (heredoc / here-string)

The guard's inline-code introspection judgment SHALL cover **every** form that feeds interpreter
code inline through a `Bash` command, not only the `-c` flag:

- interpreter token (`py`/`python`/`python2`/`python3`, start- or delimiter-bound) followed by
  `-c` (existing shape, unchanged);
- the same interpreter token followed by a **standalone `-`** argument (code on stdin — the
  heredoc shape `python3 - <<'EOF' … EOF`);
- the same interpreter token followed by a **here-string** (`- <<<` or `< <<` feeding stdin).

**解释器 token 的版本段 SHALL 覆盖带点形态**:`python3.11`/`python3.12`/`py3.13` 等带点(或多位)
版本号跟在 `py`/`python` 之后时,仍是同一个解释器 token——`python3.11 -c "<内省>"` 与
`python3.11 - <<'EOF'` SHALL 与无版本形态同判(修复前版本段正则不含点,带点版本绕过全部内省与
heredoc 检测)。

A hit SHALL fail-loud (exit 2) with the SAME sanctioned-primitive recipe as the `-c` shape (work
list / `describe_artifact.py --keys/--field` / producer stdout). The rule SHALL fire regardless
of whether the inline body contains introspection tokens in the heredoc form — an inline
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

- **WHEN** the agent issues `py - <<<"import json; print(json.load(open('x.json')))"` inside an active
  run-domain
- **THEN** the guard blocks with exit 2 + the same recipe

#### Scenario: dotted-version interpreter token is covered

- **WHEN** the agent issues `python3.11 -c "import json; json.load(open('x.json'))"`(或
  `python3.12 - <<'EOF' …`)inside an active run-domain
- **THEN** the guard recognizes the interpreter token including its dotted version segment and
  blocks with exit 2 + the same recipe(修复前 `python3.11 -c` 绕过内省与 heredoc 检测)

#### Scenario: -c token discrimination unchanged

- **WHEN** the agent issues `py -c "print('hello')"` (no introspection tokens) inside an active
  run-domain
- **THEN** behavior is exactly as before this requirement (token-based rule unchanged; no new
  false positive on benign `-c` bodies)

#### Scenario: pipe to a shell utility is not an inline interpreter

- **WHEN** the agent issues `py <in-tree script> --summary | tail -5` inside an active run-domain
- **THEN** this rule does not fire (`tail` is not an interpreter receiving code); path-side rules
  still judge any path tokens as before

### Requirement: opencode shim feeds the guard payload via a Bun-compatible stdin

The opencode `.ts` shim SHALL feed the guard subprocess its JSON payload via a Bun-compatible
`stdin` form — `new Blob([<stringified payload>])` (or the `"pipe"` + `proc.stdin.write/end`
form). The shim MUST NOT pass a bare string to `Bun.spawn`'s `stdin`: opencode's bundled Bun
rejects a string stdin (`TypeError: stdio must be 'inherit'|'pipe'|'ignore'|Bun.file|number|null`),
which throws inside the shim's guard-invocation path; the shim's fail-soft handling then returns a
pass and the guard silently never blocks (the D7 incident — a `py -c` introspection one-liner ran
unblocked and zeroed 25 T1 checkpoints). The Python guard (single decision source) is unchanged.
**守卫脚本缺失时 SHALL fail-soft 放行**:shim 在 spawn 前做守卫文件存在性预检(缺失 → 放行 +
一条诊断日志,不 spawn)——python 对不存在的脚本文件以退出码 2 退出(`can't open file`),与守卫的
阻断退出码同值;无预检时一次守卫文件缺失/错位会被误判为 deny(与 fail-soft 契约「守卫不在 → PASS」
矛盾)。stderr 含 python「can't open file」签名的退出码 2 亦 SHALL 按 fail-soft 处理(存在性预检的
兜底)。

#### Scenario: a py -c introspection one-liner is blocked in opencode

- **WHEN** an opencode session is inside an mgh run-domain (env `MGH_*_ACTIVE=1` at opencode launch
  OR the `<cwd>/<run-root>/.active` sentinel present) and the model issues a Bash `py -c` command
  carrying introspection tokens (`import json` / `open(` / `load(` / `.json`)
- **THEN** the shim feeds the normalized payload to the guard as `new Blob([stdin])`, the guard
  exits 2, the shim throws and the tool call is blocked (the model sees the sanctioned-primitive
  recipe) — the guard is NOT silently disabled by a stdin-delivery throw

#### Scenario: missing guard file degrades to a pass, not a deny

- **WHEN** the guard script file is absent/moved at the shim's resolved path(an incomplete or
  skewed install), and a handled tool call occurs inside a run-domain
- **THEN** the existence pre-check fails → the shim passes the call + logs one diagnostic
  (fail-soft);python's can't-open-file exit 2 is NEVER interpreted as a deny(修复前该形态 =
  误判 deny,与「守卫不在 → PASS」契约矛盾)

#### Scenario: the shim source form is regression-guarded in CI

- **WHEN** the shim source is checked in CI (no Bun runtime available)
- **THEN** a parity-test source-form assertion requires `new Blob([stdin])` to be present AND the
  guard-file existence pre-check to be present, preventing a silent revert to a bare string stdin
  or to exit-code-conflating deny logic (the runtime delivery itself is verified manually in opencode)

## ADDED Requirements

### Requirement: Guard payload 解码强制 UTF-8(与控制台代码页无关)

守卫读取 stdin payload SHALL 强制按 UTF-8 解码(`sys.stdin.buffer.read()` 后
`decode("utf-8", "replace")`),SHALL NOT 依赖 `sys.stdin` 的默认编码(随控制台/区域设置漂移——
中文 Windows 管道下为 cp936)。三端宿主(claude PreToolUse / opencode 插件 / dsh shim)发送的都是
UTF-8 字节;守卫按本地代码页解码会把 payload 解成乱码 → `cwd` 锚点损坏 → 哨兵向上发现失败 →
`domain is None` → **六域全部规则对该会话每次调用静默放行**(实机 A/B:同一份 UTF-8 字节,utf-8
stdin 下 exit 2 拦截、gbk stdin 下 exit 0)。解码出的 payload 仍不可解析(JSON 语法损坏)时维持既有
fail-soft(exit 0,never block);`replace` 降级只发生在 payload 本身非 UTF-8 的病态输入上
(此时锚点可能失效 → 休眠,如实披露为残余边界,优于按错误代码页静默错解)。

#### Scenario: GBK 控制台代码页下 UTF-8 payload 正确解码并拦截

- **WHEN** 中文 Windows 会话(管道编码 cp936)下,claude/dsh 面发来 UTF-8 编码的 payload
  (`cwd` 含中文用户名路径、命中运行域哨兵链),命令为应拦形态(如越树 Write)
- **THEN** 守卫按 UTF-8 解码 → 锚点正确 → 域激活 → exit 2 拦截 + recipe(修复前按 cp936 解码 →
  锚点乱码 → 哨兵未发现 → exit 0 静默放行——六域整场 run 无守卫)

#### Scenario: 无法解析的 payload 维持 fail-soft

- **WHEN** stdin 字节不是合法 JSON(空管道 / 截断)
- **THEN** 守卫 exit 0 不拦截(既有 fail-soft 语义不变;解码层修复不改变「无法检视 → 永不拦截」)

### Requirement: 哨兵发现与路径判定共用单一 cwd 源

守卫内**判定用 cwd**(`..` 相对 token 解析、listing/mutation 的 cwd 缺省锚、`Glob`/`Grep` 无 `path`
时的锚)SHALL 与**哨兵发现的锚**同源:payload `cwd` 字段(host 携带会话/工具上下文 cwd 时)优先,
回退守卫进程 cwd(opencode 插件进程,其 normalize 不构造 cwd 字段)。SHALL NOT 判定走 `Path.cwd()`
而发现走 payload `cwd` 的双源形态——两源可错根(claude 面 payload cwd = 发起调用的会话上下文,守卫
进程 cwd 可在别处),错根时相对路径按错误根解析、无 `path` 的读面按错误锚判定,产生系统性误判
(该拦不拦 / 误拦)。payload `cwd` 存在但不可解析时回退进程 cwd(NEVER 因锚不可用而崩溃)。

#### Scenario: claude 面 payload cwd 同时驱动哨兵发现与相对 token 判定

- **WHEN** claude 面 payload 携带 `cwd=D:\parent\sonA\sub`(守卫进程 cwd 在别处),命令为
  `type ..\..\secret.txt` 且 `MGH_TARGET=D:\parent\sonA`
- **THEN** 守卫以 payload `cwd` 解析 `..` 相对 token(与哨兵发现同一锚)→ 落在树外 → exit 2 +
  recipe(修复前按进程 cwd 解析,错根时误判)

#### Scenario: 无 payload cwd 的面回退进程 cwd(行为不变)

- **WHEN** opencode 插件进程发来的 payload 无 `cwd` 字段
- **THEN** 判定与发现均以守卫进程 cwd 为锚(既有行为;单一来源,无双源错根面)
