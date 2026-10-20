## 1. 插件闸门(releases/opencode/plugins/block_adhoc_scripts.ts)

- [x] 1.1 `setup` 内增注册 `await ctx.permission.hook("evaluate", cb)`(注册被 await,先于
  setup 返回);回调读 `event.action/resources/effect`,原地改写 `event.effect`/`event.message`;
  验证:源码含该注册且与工具面钩子同在 default 导出的 setup 内
- [x] 1.2 运行域识别:六运行根(`.mgh-init`/`security-scan`/`.mgh-sra`/`.mgh-srr`/
  `.mgh-ut-init`/`.mgh-sdr`)下 `.active` 存在性直查(projectRoot = setup 已捕获的
  `ctx.location.directory`,不向上走链);域外原样返回;验证:六运行根常量在场,无祖先走链
  逻辑
- [x] 1.3 哨兵读取:命中即读 `.active` JSON 取 `read_roots[]`(解析失败/缺字段按空处理,
  fail-closed);资源归属判断做大小写与路径分隔符归一 + 剥尾缀前缀匹配(纯函数);
  验证:归一化函数覆盖 Windows 反斜杠/正斜杠/大小写混合样例
- [x] 1.4 三条改写规则:①`effect==="ask"` → `deny` + 替代提示,例外
  `action==="external_directory"` 且全部资源落在 `read_roots[]` → `allow`;②
  `action==="question"` 且 `effect!=="deny"` → `deny` + 澄清/续跑提示;③其余不动;
  验证:规则实现与 spec 闸门 requirement 逐条对得上,无额外分支
- [x] 1.5 异常面:钩子内任何异常捕获后按域外原样返回(NEVER 影响宿主权限判定)+
  best-effort `console.warn` 诊断;改写无状态无缓存;验证:人为抛错的样例分支(测试替身)
  下回调不向宿主传播异常

## 2. agent 定义兜底层(releases/opencode/agent/*.md)

- [x] 2.1 opencode 面 mgh agent 定义全量补 `question: deny`(现状零覆盖);fanout 孪生之外的
  需隔离 agent 补漏 `external_directory: deny`(以既有孪生为准);验证:源面检查脚本断言
  opencode 面 agent 100% 含 `question:` 条目(缺一即红)
- [x] 2.2 兜底层与闸门层不冲突确认:规则级 deny 短路在钩子前,双层并存语义按 design D4;
  验证:实机抽查一个补过的 agent(question 调用被规则级拒绝,提示文案可见)

## 3. 契约与测试(先红后绿)

- [x] 3.1 同步 `core/contracts/hooks/runtime-enforcement.md`:增权限闸门节(三条改写规则表、
  read_roots 全属放行例外、六运行根直查与「不向上走链」的窄激活声明、域外零影响、
  Form/MCP/provider-executed/无断言自定义工具四类残余披露、版本矩阵);验证:契约与插件实现
  逐项对得上
- [x] 3.2 `tests/test_opencode_hook_parity.py` 增闸门形状断言组:`await
  ctx.permission.hook("evaluate"` 注册在场;ask→deny、read_roots 全属→allow、question 拒绝
  三分支标记在场;六运行根常量在场;既有 `TestShimV2ModuleShape` 断言扩展为双钩子注册均被
  await;验证:移除任一分支/把注册改成不带 await 的 fire-and-forget 即红(先红后绿)
- [x] 3.3 归一化/前缀匹配的纯函数若抽到可测位置(或以源面内联样例锚),补往返样例:反斜杠/
  正斜杠/大小写/尾 `/*` 通缀;验证:样例断言全绿
- [x] 3.4 agent 源面检查(2.1 的断言)落进 parity 测试或独立测试类,CI 强制;验证:删任一
  agent 的 `question:` 条目即红
- [x] 3.5 定向回归:hook 三端接线面全绿(`test_block_adhoc_scripts` / `test_opencode_hook_parity`
  / `test_dsh_hook_parity` / `test_install_hook` / `test_install_opencode_plugin` /
  `test_install_dsh` / `test_distributed_md_purity`),另带 `test_zero_deps` /
  `test_no_compile_warnings`;验证:逐一跑过无失败
- [x] 3.6 lint 四件套(`check_contracts` / `check_distributed_purity` /
  `check_distributed_prompt_budget` / `check_plain_language`)+
  `openspec validate "add-mgh-native-permission-gate" --strict`;验证:与基线一致(无新增违例)

## 4. 实机闸门(双版本)

- [x] 4.1 本机 2.1.0:scratch 项目装新插件 + 立哨兵 → 原 P11 复现场景(external_directory:
  ask 的 agent 越目录读)pending 恒为零、会话正常收尾、模型看到替代提示;read_roots 声明根
  内资源放行、根外拒绝;question 调用被拒;**拆掉哨兵后**同项目 ask 行为恢复(弹窗/默认)——
  域外零影响;验证:结果(命令 + 观测)记入本 change 实机笔记
- [ ] 4.2 企业 2.0.32(交接内网执行,不阻塞本仓归档,但 MUST 附复现步骤):同 4.1 样例集;
  记录 evaluate 事件字段与 2.1.0 的差异(回答 design 两个 Open Questions);验证:内网回执
  PASS 或差异清单回填契约版本矩阵
- [x] 4.3 无 mgh 项目抽查:任一普通项目触发 ask(如读 `.env`),确认闸门不介入(域外原样);
  验证:记录进实机笔记

## 5. 收尾

- [x] 5.1 VERSION bump + CHANGELOG 分组条目(权限闸门/agent 兜底/残余边界披露)
- [x] 5.2 诚实边界同步:根 AGENTS.md 诚实边界节补「权限询问闸门与其四类残余」一条;交接文档/
  实机笔记归位本 change 目录;验证:`test_distributed_md_purity` 复跑绿
