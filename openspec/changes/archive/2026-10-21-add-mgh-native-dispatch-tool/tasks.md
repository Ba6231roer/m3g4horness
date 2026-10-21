## 1. 派发插件(releases/opencode/plugins/mgh_dispatch.ts)

- [x] 1.1 骨架:default 导出 `{id, async setup(ctx)}`;`setup` 内 `await` 注册两件事——自定
  义工具 `mgh_dispatch`(`ctx.tool.transform` + `editor.add`)与 `execute.before` 令牌展开
  钩子;项目根 = `ctx.location.directory` 捕获;验证:源码含双注册且均被 await,无 1.x 形
  态
- [x] 1.2 输入契约与校验:`plan`(绝对或项目相对)/`wave`/`units` 闭集;互斥校验;计划读
  取/解析/短号归属失败 → Tool.Error + recipe,零会话创建;验证:校验分支形状锚 + 假对象单
  测(若可独立导出纯校验函数)
- [x] 1.3 派发语义对齐:每次创建前 `permission.assert`(subagent 动作/目标 agent);沿
  parentID 链深度计数 + 上限拒绝(配置不可达时保守缺省 1,注释披露);agent 模式校验拒绝
  primary;`description` = 短号;任务消息 = 任务文件内容逐字读取注入;波内并发 =
  `wave_size`、波间顺序;验证:三分支(断言/深度/模式)形状锚在场
- [x] 1.4 收割与摘要:磁盘标记三分(done/failed/no-marker);会话终态触发查标记不判成
  败;幂等(终态标记单元跳过);摘要 = 计数 + failed/no-marker 短号清单 + 单元↔会话 id +
  实跑波次,零 findings/零任务文本;验证:摘要形状锚 + NEVER 写标记断言(源码无
  marker 写入面)
- [x] 1.5 取消级联:工具 `signal` 中止时逐个 `interrupt` 仍活跃的已建子会话后返回;验证:
  级联分支形状锚(interrupt 调用在中止路径内)
- [x] 1.6 配额自限:直读 `<项目根>/.mgh/env-profile.json`(缺省/坏文件按其 fail-closed 语
  义放行——本插件不重复判定,只读已校验形态;不可解析 = 零节流并计数披露);波间准入算术
  (K×已派+K≤N)与等待;等待事实入摘要;验证:算术用例(窗口边界)+ 无画像零节流用例
- [x] 1.7 令牌展开钩子:`execute.before` 对内置子代理工具任务文本识别固定前缀令牌行(计
  划引用 + 短号),读计划展开为任务文件全文替换 `event.input` 后放行;非令牌文本零干扰;
  未知短号/计划不可读 → Tool.Error + recipe;验证:前缀常量形状锚 + 展开分支锚

## 2. 分发面

- [x] 2.1 `tools/install_opencode_plugin.py`:单文件名 → 固定文件集(守卫 + 派发),幂等放
  置,stdout 契约同步(每文件 action);仍 NEVER 触碰用户其它插件;验证:
  `test_install_opencode_plugin` 扩展用例(两文件齐/幂等重装/用户插件不动)
- [x] 2.2 `core/prompts/fragments/sdr-native-dispatch.md`:任务中继行换令牌形(固定句 +
  令牌行,纪律语义不变);与钩子前缀常量同形;验证:fragment 形状锚(令牌前缀与插件常量
  一致)
- [x] 2.3 契约同步:`core/contracts/fanout/runtime.md` native 段增「dispatch tool」子节(输
  入契约/语义对齐表/幂等/取消/自限/令牌展开/版本矩阵);install 自检清单补第二插件;验证:
  契约与实现逐项对得上

## 3. 测试(先红后绿)

- [x] 3.1 `tests/test_opencode_hook_parity.py`(或新形状锚测试类):派发插件形状锚——双注
  册被 await、断言/深度/模式三分支、取消级联分支、短号校验分支、令牌前缀常量、NEVER 写标
  记(无 marker 写入面)、零第三方 import;守卫插件既有锚不受影响;验证:移除任一分支即红
- [x] 3.2 `tests/test_install_opencode_plugin.py` 扩展(2.1 的用例);验证:全绿
- [x] 3.3 定向回归:`test_opencode_hook_parity` `test_install_opencode_plugin`
  `test_distributed_md_purity` `test_block_adhoc_scripts` + `test_zero_deps` +
  `test_no_compile_warnings`;验证:逐一跑过无失败
- [x] 3.4 lint 四件套 + `openspec validate "add-mgh-native-dispatch-tool" --strict`;验证:与
  基线一致(无新增违例)

## 4. 实机闸门(本机 2.1.0)

- [x] 4.1 小计划全链:隔离小仓物化 ≥2 波计划 → 一次 `mgh_dispatch` 调用跑完全部波次 → 磁
  盘标记与摘要一致、编排器上下文只进摘要;验证:命令与摘要摘录入本 change 实机笔记
- [x] 4.2 幂等与故障面:再调用一次(终态零重派);`units` 传错抄短号(fail-loud 零会话);
  中途 abort(级联中断、无孤儿子会话);令牌展开端到端(令牌行调用内置子代理工具,子代理
  收到全文);验证:五项结果入实机笔记
- [ ] 4.3 企业 2.0.32 只读探测(交接内网,不阻塞归档):确认插件加载 + 工具注册 + 会话域
  API 面可用(一次 dry 形调用或探测脚本);验证:内网回执或差异清单回填契约版本矩阵

## 5. 收尾

- [x] 5.1 VERSION bump + CHANGELOG 分组条目(派发插件/输入契约/语义对齐/令牌展开与
  fragment 换形/安装器文件集)
- [x] 5.2 根 AGENTS.md 诚实边界补「通道 B 派发工具(opencode,插件形态)」一句;实机笔记归
  位本 change 目录;验证:`test_distributed_md_purity` 复跑绿
