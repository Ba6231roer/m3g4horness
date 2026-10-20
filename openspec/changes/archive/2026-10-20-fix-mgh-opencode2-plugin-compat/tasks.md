## 1. 插件壳迁移(releases/opencode/plugins/block_adhoc_scripts.ts)

- [x] 1.1 改 2.x 模块契约:`export default { id, async setup(ctx) }`,钩子经
  `await ctx.tool.hook("execute.before", cb)` 注册(setup 内 await 完成再返回);回调改单事件
  对象取参(`event.tool` / `event.input`);验证:源码无 1.x 具名导出与 `(input, output)`
  双参形态
- [x] 1.2 锚点注入:setup 捕获 `ctx.location.directory` 为项目根,逐调用写入 payload
  `cwd` 字段(与 `{tool_name, tool_input}` 并列);验证:payload JSON 含 `cwd`,守卫 Python
  源零改动
- [x] 1.3 工具名双代收敛:HANDLED 与 normalize 增 `shell`(与 `bash` 同映射
  `{tool_name:"Bash", tool_input:{command}}`)与 2.x 补丁工具 id(与 `apply_patch` 同走
  patchText 提取,字段缺失按空提取);验证:两代 id 各自构造的 payload 归一后等价
- [x] 1.4 诊断通道降级:删除 `ctx.client.app.log` 调用,非阻断诊断改 `console.warn`
  best-effort;验证:阻断路径(退出码 2 → throw stderr)逐字不变,fail-soft 分支(守卫
  缺失/不可达/无解释器)行为不变
- [x] 1.5 实测 2.x 补丁工具形态(本机 2.1.0,scratch 项目触发一次补丁类调用,记录工具 id
  与参数字段),按实测收口 1.3 的字段映射;验证:记录写入本 change 目录的实机笔记,映射
  与记录一致〔收口方式改为源码钉扎 + 运行时暴露检查:维护者将 opencode 最新源码 clone 到
  本机,`patch`/`patchText` 同形由源码定位坐实;运行时样本实测该工具未暴露给默认模型
  工具集(TOOL_UNAVAILABLE),按边界记录——见实机笔记 §1/§2.4〕

## 2. 契约与安装面

- [x] 2.1 同步 `core/contracts/hooks/runtime-enforcement.md`:opencode 壳节改 2.x 形态
  (default 导出契约、单事件对象、两代工具 id 表、payload cwd 注入、诊断降级、版本矩阵
  2.0.32/2.1.0、1.x 断代披露);验证:契约描述与插件实现逐项对得上,无 1.x 双参残留
- [x] 2.2 install 自检与披露:`tools/install_opencode_plugin.py` 行为不变(纯拷贝、文件名
  不变)确认;install.sh 自检清单该条目不变;README/CHANGELOG 面向 opencode 1.x 用户的
  断代说明一句(插件面向 2.x);验证:`test_install_special_auth` 式三态收敛思路不适用时,
  以 `tests/test_install_opencode_plugin.py` 全绿 + install.sh 自检输出含该条目为准

## 3. 测试(先红后绿)

- [x] 3.1 `tests/test_opencode_hook_parity.py`:新增源码形状断言组——`export default` +
  `{ id` + `await ctx.tool.hook(` 在场;`export const BlockAdhocScripts` 缺席;双参回调
  形态缺席;`ctx.location.directory` 捕获 + payload `cwd` 注入在场;既有 Blob stdin/存在性
  预检查断言保留;验证:人为回退 1.x 形态时断言变红(先红后绿)
- [x] 3.2 同文件新增两代工具 id 断言:HANDLED 同时含 `bash`/`shell` 与两代补丁 id,且
  normalize 对两代 id 产出等价 `{tool_name, tool_input}`;验证:删任一代 id 断言红
- [x] 3.3 `tests/test_block_adhoc_scripts.py`:新增 payload `cwd` 锚点场景——payload 携带
  项目根 cwd、哨兵在该根 `<run-root>/.active` 时守卫激活(进程 cwd 在别处);payload 无
  cwd 回退进程 cwd 的既有场景保持绿;验证:守卫 Python 源零改动的前提下新旧场景全绿
- [x] 3.4 `tests/test_install_opencode_plugin.py`:安装后副本满足 2.x 形状断言(与 3.1 同
  源断言函数);验证:旧 1.x 形状源文件安装时该断言红
- [x] 3.5 定向回归:hook 三端接线面全绿(`test_block_adhoc_scripts` /
  `test_opencode_hook_parity` / `test_dsh_hook_parity` / `test_install_hook` /
  `test_install_opencode_plugin` / `test_install_dsh` / `test_distributed_md_purity`),另带
  `test_zero_deps` / `test_no_compile_warnings`;验证:以上文件逐一跑过无失败〔全量 66 文件随跨面改动一并跑:64 过;2 个失败文件
  (test_diff_group / test_fanout_runner)经 stash 对照为 HEAD 存量环境相关,不在此清单
  且与本 change 改动面零交集——见实机笔记 §5〕
- [x] 3.6 lint 四件套:`python tools/check_contracts.py`、
  `python tools/check_distributed_purity.py`、
  `python tools/check_distributed_prompt_budget.py`、`python tools/check_plain_language.py`,
  另跑 `openspec validate "fix-mgh-opencode2-plugin-compat" --strict`;验证:与改动前基线
  一致(无新增违例)

## 4. 实机闸门(双版本)

- [x] 4.1 本机 2.1.0 闸门:scratch 项目装新插件 → 服务日志无 `Plugin must export a default
  definition…` 拒载;同套越权样例(越树 write/read、`py -c` 内省、叶脚本写、`..` 相对
  token、补丁工具越树)全部被拦且 recipe 可见;服务进程 cwd 置于非项目目录时哨兵仍发现
  (锚点注入生效);验证:结果记入本 change 目录实机笔记(复现命令 + 拦截输出摘录)
- [ ] 4.2 企业 2.0.32 闸门(交接内网执行,不阻塞本仓归档,但 MUST 在归档前发出并附复现
  步骤):同 4.1 样例集 + 记录事件对象字段名与 2.1.0 的差异(若有);验证:内网回执
  PASS 或差异清单回填 design「Open Questions」
- [x] 4.3 agent frontmatter 抽查(随 4.1/4.2):装 `sdr-review-fanout` 与 `init-scout-fanout`
  后 `edit` 仍被拒、`bash/shell` 仍可用(2.x 迁移映射生效);惰性键(`doom_loop`/`list`)
  保留不动;验证:抽查记录进实机笔记

## 5. 收尾

- [x] 5.1 VERSION bump + CHANGELOG 分组条目(插件 2.x 迁移/锚点注入/两代工具 id/断代披露)
- [x] 5.2 诚实边界同步:根 AGENTS.md R5.7 段 opencode 侧描述如提及旧回调形态则更新一句;
  交接文档/实机笔记归位本 change 目录;验证:`test_distributed_md_purity` 复跑绿
