# tasks — add-mgh-dsh-command-surface

## 1. 前置确认

- [x] 1.1 确认地基 change 已 apply:守卫三端接线测全绿,`install.sh --dsh` 可完成 core/ 镜像
      与 shim 接线(未就绪则本 change 暂停——无守卫执法的命令壳不得分发)
- [x] 1.2 读 dsh skill 装载面实测两事实(维护者本机 dsh 源码检出,apply 时读):
      ① `user-invocable`/`disable-model-invocation` 的 frontmatter 解析键名与语义;
      ② skill 正文注入是否受宿主字节预算截断(design Open Question 1)
      ——实测:键名 kebab-case(camelCase 被拒);skill 正文无尺寸上限,仅目录 description 截断

## 2. 五份 dsh 壳

- [x] 2.1 建 `releases/dsh/skills/mgh-sdr/SKILL.md`:frontmatter 四字段(name/description/
      user-invocable/disable-model-invocation)+ opencode 壳为基的逐字镜像 + 方言白名单段
      (召唤语义、边界披露、fan-out 降级段 D4)
- [x] 2.2 同法建 `mgh-sast` / `mgh-init` / `mgh-sra` / `mgh-srr` 四壳(sra/srr 无扇出段的
      部分不加 D4 披露,按各自壳实际 step 判定)
- [x] 2.3 三面 shell 对等自查:每壳与 claude/opencode 对应用 `diff` 过一遍,差异行仅落
      design D3 白名单四类(spec 场景「delta whitelist is exhaustive」)
      ——apply 期白名单扩为五类:新增 (e) 主机机制事实按 dsh 实测改写(批量问通道
      `ask_user_question`、哨兵 shim 继承边界、per-call `timeout` 入参),spec/design 已同步

## 3. lint 与测三面化

- [x] 3.1 `tools/check_contracts.py` 扫描集纳入 `releases/dsh/skills/**`(flag 存在断言
      三面跑);人为注入一个单壳漂移验证 lint fail(用完回退)
      ——459 flags × 17 shells 全绿;漂移注入 fail/回退均已验证
- [x] 3.2 编排器壳 token 预算 lint 入扫 dsh 壳;`py tools/measure_prompts.py` 记录五壳
      `mid_tokens` 基线(应自然落 ~4.5–5K 经验带,超带即评审冗余)
      ——新建 `tools/check_distributed_prompt_budget.py`(17 壳 ≤5000 全绿)。
      五 dsh 壳基线:sdr 4794 / sast 4584 / init 3623 / sra 3426 / srr 3548。
      存量超债经维护者拍板在本 change 内 shard-to-fit:mgh-sra/mgh-srr 三端壳
      「## Orchestration flow」段整段逐字搬入 lazy fragment
      (`core/prompts/fragments/{sra,srr}-flow-{claude,opencode,dsh}.md`,各 ~1.7–2.2K tok),
      壳留 REQUIRED SUB-SKILL 指针 + 骨架行;六 fragment 与 HEAD 壳段逐字比对通过
- [x] 3.3 新增 `tests/test_dsh_command_surface.py`:frontmatter 形状断言(四字段 +
      name=目录名 + description ≤1536 字符)、引用路径根白名单断言(仅
      `<target>/mgh-core/` 与受信根)
- [x] 3.4 分发纯净 lint 确认自动覆盖新文件(加一条 dsh 壳内注入私有引用样例 → 断言被扫出
      → 回退);`py tools/check_plain_language.py` 全绿
      ——`releases/dsh/skills` 已加入 purity SCAN_DIRS;注入私有引用样例(铁律编号 token +
      本仓私有词典文档路径)被扫出 rc=2、回退后 rc=0;新 fragment 落 core/prompts 扫描面内。
      **遗留待拍板**:`check_plain_language.py` rc=2 系四个**与本 change 无关的存量活跃变更**
      (add-mgh-telemetry-seam / add-mgh-ut / add-skill-dev-experience-doc /
      extract-ut-shared-helpers)proposal 缺人话序(HEAD 即如此,非本次引入);本 change
      自身产物全绿

## 4. install 扩面

- [x] 4.1 `install.sh --dsh`:新增 skills 落位(复制 5 壳 → `<target>/.dsh/skills/`,
      幂等覆盖);`install.ps1` 对等
      ——step 3 dsh 分支复制 `releases/dsh/skills/.` → `<target>/.dsh/skills/`;ps1 同形;
      scratch 真机幂等二跑无重复目录
- [x] 4.2 安装自检:五壳齐全 + frontmatter 必含字段 + 缺壳 fail-soft(CI fail);
      `--no-enforce-hook` 语义不变(skills 照常落位——壳与执法解耦)
      ——5c 自检块:五壳存在 + name/description/user-invocable/disable-model-invocation
      四字段 + 引用根污染检查;缺壳仅 warn 不阻断(fail-soft);`--no-enforce-hook` 下
      skills 照常落位的断言见 4.3 测
- [x] 4.3 定向跑 `test_install_dsh`(change 1 建的同型文件)扩用例覆盖 skills 断言
      ——新增 `TestDshSkillsPlacement`(bash/ps1 双脚本静态断言)+ `TestDshSkillsInstall`
      (真跑 install 到隔离 DSH_HOME scratch:五壳落位/frontmatter、重装刷新幂等、
      no-enforce-hook 照常落位、自检块抽取执行 fail-soft 分支);14 测全绿 ~33s

## 5. 手册收口

- [x] 5.1 研发手册:测试映射表「命令壳/提示词/分发产物」行加入 `test_dsh_command_surface`;
      「双壳同改」纪律措辞扩为三镜像(改任一壳须同查三端);版本号 bump
      ——AGENTS.md:宿主矩阵段(白名单五类)、R5.1 三面、映射表行、hook 三端接线 ×2、
      慢测表加 `test_install_dsh::TestDshSkillsInstall`;VERSION 0.1.53 → 0.1.54 + CHANGELOG 条目
- [x] 5.2 本 change 目录内留一条 change 3 关联备忘:D4 降级段的删除动作挂到
      add-mgh-dsh-subagent-fanout 收尾(不建 docs/ 指针)
      ——design.md D4 段内联交接备忘(删除动作归 change 3 收尾任务,不另建指针文件);
      同文件 Open Question 1 已标注关闭(正文无尺寸上限,实测)

## 6. 真机验收

- [ ] 6.1 `install.sh --dsh <scratch>` 后,dsh 会话 `/mgh-sdr --help` → 参数表 STOP;
      裸 `/mgh-sdr` 默认集进编排,step 1–2(纯确定性段:分组 + 上下文投影)跑通并落盘产物
- [ ] 6.2 运行至扇出步 → 按 D4 披露停止并报告 resume 状态(磁盘 marker 可续),无静默死循环
- [ ] 6.3 越界抽查:该 run 域激活下,dsh 会话尝试树外 `read`/`write` → 守卫 deny + recipe
      (证明命令面与地基联动)
- [ ] 6.4 模型自触发反例验证:普通编码任务中确认 mgh-* 不出现在模型可召唤 skill 集
