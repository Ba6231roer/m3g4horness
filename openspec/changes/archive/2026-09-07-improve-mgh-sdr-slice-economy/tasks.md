## 1. diff_group.py 排除过滤器(D1)

- [x] 1.1 实现确定性排除过滤器(闭集常量表,每条带 reason 标签:test-tree / build-output / generated / static-asset / lockfile / build-script),在 `parse_diff` 之后、`_build_units*` 之前过滤 `file_diffs`;SQL/`*Mapper.xml`/`application*.yml`/`*.properties`/`logback*.xml` 不排除(docstring 显式白名单语义)
- [x] 1.2 新增 CLI flag `--include-excluded`(store_true,兜底开关)与 `--max-interface-bytes`(默认 262144);`--help` 契约同步
- [x] 1.3 stdout/grouping.json 增 `excluded{count, by_reason{}}`;stderr 摘要行追加排除计数;纯排除 diff(非零文件、零单元)与零 diff 在 stderr 与 `empty` 语义上可区分
- [x] 1.4 `--check` 扩展:`excluded` 结构类型校验(part 单元 input_path 齐备、`route` 多值 `;` 形态合法);旧 grouping.json 缺新字段不报错(向后兼容)

## 2. diff_group.py 向上锚定 + 共享链合并 + 残余聚簇(D2/D3/D4)

- [x] 2.1 `_cg_edges` callers 侧原样留存(含未变更端点,`filePath::name` 键,`\`→`/` 归一沿用);`codegraph_stats` 计数埋点(symbols_queried / edges_captured / edges_in_changed_set)
- [x] 2.2 实现向上锚定:无变更路由可归属的变更符号沿 callers BFS ≤2 跳(visited 防环,途经符号不向下扩展),途经/终点符号经确定性本地注解扫描(复用 `_base_route`/`_method_mappings`/`_java_symbols`,读 branch 内容)识别路由方法;命中 → 并入该路由 interface 单元,`anchors_upstream` 计数;≤2 跳无路由 → 落残余
- [x] 2.3 向上锚定 slice 上下文:路由方法有界源码片段(`_brace_end` 域 + 权限注解块,复用 `_anno_block`,~60 行截断标注),走 `ann_ctx` 渲染,新增 `upstream-route` 上下文类型
- [x] 2.4 实现共享链合并:同 controller 文件内 route 闭包可达集指纹相同或互为子集 → 合一单元(`route` 分号连接,`chain_merged` 计数);跨 controller 不合并;多锚定冲突按接口拆(hunk 重复,render 去重)
- [x] 2.5 实现 `--max-interface-bytes` 预算:合并后超限按 route 组确定性拆 part 单元(`unit_id` 带 `-partN` 后缀,`route` 保留本 part 路由串,`pending[]` 各 part 独立路径)
- [x] 2.6 java 残余回归目录聚簇:callchain 第 5 步 java 残余改走 `_cluster_standalone_sel` + `--max-standalone-bytes`(与非 java 残余同路径);合并 slice 首部列文件清单 + 各文件符号表(方法名 + 行域,有界)
- [x] 2.7 codegraph probe 失败时 stderr 给原因(`no .codegraph dir` / `no binary`);`codegraph_stats` 全零结构恒在

## 3. 渲染与壳契约(D5/D6)

- [x] 3.1 `render_sdr_report.py`:manifest `counts.excluded_files` 透传;报告头部「分组概览」小节(interface/standalone 单元数、anchors_changed/anchors_upstream/chain_merged、excluded 计数);诚实边界第 ② 条措辞更新 + 新增第 ⑦ 条排除集披露
- [x] 3.2 双壳 `releases/{claude-code/commands,opencode/command}/mgh-sdr.md`:flag 表同步 `--include-excluded`/`--max-interface-bytes`(逐字镜像调用示例);纪律段增排除集/兜底/统计诊断各 ≤2 行(R5.6 预算内)
- [x] 3.3 `core/prompts/fragments/fanout/sdr-task.md`:多路由单元逐路由判定 + `upstream-route` 上下文段语义,各 1–2 行
- [x] 3.4 `tools/check_contracts.py` `DIFF_GROUP_REQUIRED_FLAGS` 追加两个新 flag;`py tools/check_contracts.py` 通过

## 4. 测试与验收

- [x] 4.1 `tests/test_diff_group.py` 新增:排除集各 reason 分类命中(测试树/构建产物/静态资源/锁文件/构建脚本)、SQL+mapper XML 不排除、`--include-excluded` 兜底、排除后 `excluded` 计数正确
- [x] 4.2 新增用例:controller 未变更经 callers 向上锚定归链(slice 含路由方法片段)、≤2 跳无路由落残余聚簇、同 controller 共享链合并(`route` 多值)、跨 controller 不合并、超 `--max-interface-bytes` 拆 part、`codegraph_stats` 字段形态(off 时全零)
- [x] 4.3 全量回归:`py tests/test_diff_group.py` + `py tests/test_deterministic.py` + `py tools/check_contracts.py` + `py tools/check_distributed_purity.py` 通过;旧用例(零 diff/ADS 安全/done marker/`--check`)非回归
- [ ] 4.4 真仓验收(另一环境):重装后同 base/branch 重跑 `/mgh-sdr`,对比单元数(基线 401)与 `codegraph_stats`;报告含排除披露与分组概览;结果回填本 change 报告节
