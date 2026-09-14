## 1. 守卫判定核心（claude twin）

- [x] 1.1 新增路径 token 提取器：单遍扫描 Bash 命令串，产出 Windows 盘符绝对 / UNC / POSIX 绝对 / `..` 引导 / `~/` 引导 token（引号剥离、含 `://` 的 token 排除、裸 `~` 不判），返回 token 列表
- [x] 1.2 新增配置读取：`<target>/.mgh/read-roots.json`，schema `{"v":1,"read_roots":[…]}`，未知字段忽略；缺文件 → 空元组；坏 JSON / `read_roots` 非列表 → 空元组且不报错；复用 `_in_read_root` 同款「存在 ∧ 是目录」包含语义
- [x] 1.3 新增 catch-all 判定函数：允许集 = target ∪ 哨兵 `read_roots[]` ∪ 配置 `read_roots[]`；未钉 target → 放行；任一 token resolve 后全集外 → 命中；无路径 token → 放行
- [x] 1.4 `main()` Bash 分支接线：在 redirect 规则之后追加 catch-all（命中 → 退出码 2 + stderr recipe 列出三类允许根）；同时把配置 `read_roots[]` 并入既有工具面 `_read_out_of_tree` 与 Bash 搜索/列目录规则的 `read_roots` 入参（D1 统一）

## 2. 双端同步

- [x] 2.1 将 claude twin 字节级镜像到 `releases/opencode/hooks/block_adhoc_scripts.py`
- [x] 2.2 运行 `tests/test_opencode_hook_parity.py` 确认 twin parity 仍绿（shim/matcher 零改动）

## 3. 回归测试（tests/test_block_adhoc_scripts.py）

- [x] 3.1 catch-all 用例：`robocopy` 树外目的拦；`Get-Content <树外文件>` 拦（此前放行的形状）；`type ..\..\x` 爬升拦；`--doc https://…` 不误伤；全 in-tree 命令放行；未钉 target 降级放行且其余规则照常
- [x] 3.2 读允许集统一用例：`rg <树外已声明根>` 放行（语义反转）；`rg <target 与声明根之外>` 拦；`Set-Content <已声明根>/x` 仍拦且浮出写侧 recipe（变异规则先行）
- [x] 3.3 配置用例：sast 域配置根 Read + Bash rg 双放行；Write 进配置根拦；坏 JSON fail-closed 不崩；缺文件行为不变；配置 ∪ 哨兵并集；不存在条目零授权
- [x] 3.4 既有用例全量回归：五张动词表规则、init/ut-init P1、redirect、`py -c`、file-assoc、聚合整读、missing-install 的既有断言不回退

## 4. 契约与文档

- [x] 4.1 `core/contracts/hooks/runtime-enforcement.md` 同步：读/写允许集决策模型表、catch-all 规则条目、配置文件契约（路径/schema/fail-closed）、语义反转注记（`read_roots[]` 现及 Bash 面）
- [x] 4.2 AGENTS.md R5.7 段措辞同步：Bash 面「动词枚举 + 路径允许集净网」双层描述、`.mgh/read-roots.json` 载体、诚实边界补 D6 残余两条
- [x] 4.3 CHANGELOG.md / VERSION bump（R5.8：任何脚本/契约改动 bump）

## 5. 全量校验

- [x] 5.1 `py tests/test_block_adhoc_scripts.py` 全绿；`py tools/check_contracts.py`、`py tools/check_distributed_purity.py` 无新违例
- [x] 5.2 install 冒烟：`install.sh --claude` 镜像后 twin 共存校验通过（fail-soft 自检无 warn）
