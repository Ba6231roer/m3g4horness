# tasks — add-mgh-dsh-host-foundation

## 1. 真机 spike(关闭 design D2/Open Questions,先行)

- [x] 1.1 读维护者本机 dsh 源码检出,钉死三事实并回填 design.md:① `tools/pre-execute`
      事件 payload 字段名(工具 id 字段、参数容器字段);② 监听者 deny 的返回形状与
      reason 是否原样进入模型可见工具结果;③ `$DSH_HOME` Windows 默认落点与 profile
      目录自动创建行为
- [x] 1.2 最小实验验证装载两候选:(a) 生成最小 npm 包目录 + `dsh plugin add` 进 profile;
      (b) `cordis.patch.yml` 直接文件路径挂载。记录哪条可用;均不可用则启用降级预案
      (独立 `mgh` profile,`--from-default-profile` 派生)并回填 D2
- [x] 1.3 探测确认 dsh 会话内 shell 工具执行 `py`/`python` 的实际解释器可用性链路
      (Windows 下 dsh bash 面走的 shell 方言),记录 shim 的解释器回退顺序

## 2. 守卫判定面扩展(单源仍在 Python)

- [x] 2.1 `core/scripts/block_adhoc_scripts.py` 新增分派分支:`RunCode`(= 内联解释器违例
      同形,deny + recipe 指向「跑声明叶脚本」合法出口)、`TerminalIO`/`JobCtl`(运行域内
      deny + recipe),仅认映射后的守卫规范名,不感知 dsh 字段名
- [x] 2.2 既有规则族挂接:`pwsh` 经 shim 归一化为 `Bash` 后自动命中五张动词表 + 净网规则(m)
      ——守卫侧零新代码,加断言用例证明同命中
- [x] 2.3 `tests/test_block_adhoc_scripts.py` 新用例:域内 RunCode 拒/域外放行、TerminalIO
      与 JobCtl 域内拒、写侧越树经新名仍 fail-loud、双端 payload 零回归(既有基线全绿)

## 3. dsh shim 插件

- [x] 3.1 新建 `releases/dsh/plugins/mgh-guard.ts`:订阅 pre-execute → 按 D3 映射表归一化
      为 `{tool_name, tool_input, cwd}` → spawn 同目录兄弟 `block_adhoc_scripts.py`
      (stdin 一次性 Buffer 注入)→ 退出码 2 时 deny 并回传守卫 stderr 为 reason;
      其余退出码/找不到 Python 一律放行 + 日志一条
- [x] 3.2 未映射工具 id 透传不处理;`str_replace_editor` 从 patch 主体抽路径进写侧越树判定
- [x] 3.3 shim 内映射表以「可被测试静态解析」的常量形状落笔(镜像 opencode `HANDLED` 惯例)

## 4. 三端接线覆盖与 parity

- [x] 4.1 `TestWiringCoverage` 扩展:守卫分派集(含新分支名)⊆ claude matcher ∧ ⊆ opencode
      `HANDLED` ∧ ⊆ dsh shim 映射表值域(静态解析 3.3 的常量)
- [x] 4.2 新增三面同 fixture 用例:同一违规(claude `Write` / opencode `write` / dsh
      `write`)直接喂守卫,断言三端退出码与 recipe 同源一致
- [x] 4.3 定向跑:命中「`block_adhoc_scripts.py` / hook 双端接线」映射行的全部测试文件
      (本面改动的默认姿势,不跑全量)

## 5. install 第三方言

- [x] 5.1 `install.sh` 新增 `--dsh`:镜像 `core/` → `<dest>/mgh-core/`;shim 落
      `<dest>/mgh-core/dsh/`;按 1.2 结论执行 profile 接线(受管块 marker 锚定、幂等、
      二次安装跳过并提示);`$DSH_HOME` 定位失败 → fail-loud 退出非零且不落半成品
- [x] 5.2 `--no-enforce-hook` 对 `--dsh` 生效(仅镜像不接线,自检 warn)
- [x] 5.3 `install.ps1` 对等镜像 5.1–5.2
- [x] 5.4 安装自检扩展:shim 与守卫脚本 co-location 断言 + 三端接线存在性断言;
      `tests/` 新增同型 `test_install_dsh`(参照 `test_install_hook` /
      `test_install_opencode_plugin`)

## 6. 契约与手册收口

- [x] 6.1 守卫运行时契约(`core/contracts/hooks/runtime-enforcement.md`)补 dsh 端:
      激活 = 哨兵(env 边界与宿主进程模型段扩为三端同形表述)、归一化映射表、fail-soft 条款
- [x] 6.2 研发手册「改动面 → 测试文件」映射表把 hook 行扩为三端(文件清单增
      `test_install_dsh`);版本号 bump(承「任何 md/脚本改动 bump」)
- [x] 6.3 `py tools/check_distributed_purity.py` + `py tools/check_contracts.py` 全绿
      (新分发文件入扫描面即受检;dsh 方言文件不得携带本研发仓私有引用)

## 7. 真机首跑验收(本 change 的 done 判据)

- [x] 7.1 在装有 dsh 的机器 `install.sh --dsh <scratch-target>`,dsh 会话跑一次 init 域
      起步(叶脚本写哨兵)后验证四连拒:树外 `write`、树外 `read`、`run_code` 内联片段、
      `pwsh` 树外写;每条 deny reason 含合法出口 recipe 且模型可见
- [x] 7.2 无哨兵仓库正常使用 dsh(写/读/`run_code`)零打扰
- [x] 7.3 重复 install 幂等验证(接线不重复追加);`--no-enforce-hook` 路径复验
- [x] 7.4 观察期清单:首跑日志中出现的「未映射但携带路径」的工具 id 逐个裁决是否入表
      (design Open Question 3 的收口动作)
