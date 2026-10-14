# add-mgh-sdr-inline-branch-list

> **人话序**:launcher(人/cron 一条命令入口)目前跑多个分支只有一种喂法——`--multi-branch`
> 传一个**清单文件**(一行一个分支名)。临时比两三个分支时,得先开编辑器建文件再传路径,
> 顺手的事变成三步。本 change 给 launcher 新增**内联清单**参数 `--branch-list "a,b,c"`:
> 逗号分隔、引号包住直接写在命令行上,与 `--multi-branch` 二选一(同时给出 → 退出码 2
> fail-loud,不猜不静默取其一);解析规则 = 按逗号切分、逐项去空白、重复分支只跑一次、
> 空项(如 `a,,b` 或结尾多逗号)拒识退出码 2——逗号在 git 分支名里合法,所以**不做**
> 「含逗号即列表」的 `--multi-branch` 双重语义,独立参数消除歧义。两种喂法汇入同一条
> 串行逐分支流程(每分支独立 run 目录 + 独立报告,单分支失败记录后继续,退出码语义
> 0/1/2 不变)。验证 = 先红后绿单测(内联串行/互斥拒识/空项拒识/去重去空白/`--help`
> 契约面)+ `test_mgh_sdr_launch` 定向面全绿 + lint 四件套不回归。

## Why

launcher 的多分支入口 `--multi-branch <file>` 只收文件。真实使用里高频形态是「临时比
2–3 个分支」:为三个名字建一个文件、再传路径,摩擦大于收益(2026-10-14 真仓回归时,
维护者即现场问出「能不能直接 `--branch-list "a,b,c"`」——需求来自第一次真实使用)。
现有 `--branch` 参数只收单个分支,补一个内联多分支形态即可覆盖全部三种喂法:
单分支 `--branch` / 内联多分支 `--branch-list` / 文件多分支 `--multi-branch`。

**为什么是新参数而不是 `--multi-branch` 兼容逗号**:逗号是 git 分支名的合法字符
(`foo,bar` 可为真实分支),「值含逗号 = 内联列表、否则 = 文件路径」的双重语义对合法
分支名有歧义;独立参数 + 显式互斥(同给退出码 2)消除歧义,误用即报错不猜。

## What Changes

全部改动集中在 launcher `core/scripts/mgh_sdr_launch.py`(单文件)+ 其测试 + 规格 +
README(人类面文档);零三面壳改动(壳只把 launcher 当优选入口指认,不展 flag 表;
`--help` 是唯一契约面,R5.1 超集兼容)。

1. **新参数 `--branch-list "<b1,b2,...>"`**:argparse 新增;值为逗号分隔分支名内联清单。
2. **解析规则**(`_split_branch_list` 纯函数):按 `,` 切分 → 逐项 `strip()` → **空项拒识**
   (退出码 2 + 可操作 stderr 报出第几项)→ 保序去重(重复分支只跑一次,与
   `_read_multi_branch` 行为一致);整体为空/全空白 → 退出码 2。内联模式**无注释语法**
   (每个逗号项都是分支名,`#` 开头项不特判)。
3. **互斥**:`--branch-list` 与 `--multi-branch` 同时给出 → 退出码 2 + recipe(二选一,
   NEVER 静默取优先级);`--branch-list` 与 `--branch` 同给时内联清单优先(`--branch`
   被忽略,与现行 `--multi-branch` 压过 `--branch` 的行为同形)。
4. **语义同源**:内联清单汇入与 `--multi-branch` 完全相同的串行逐分支流程(每分支独立
   run 目录 + 独立报告;单分支失败记录后继续;launcher 退出码 0 全成功 / 1 任一分支
   FAILED / 2 误用,一字不变)。
5. **文档同步**:launcher 头注 usage 行、`--help`、README `/mgh-sdr` 多分支段补第三种
   喂法;CHANGELOG/VERSION 收尾。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

(无——本 change 以 **ADDED requirement** 落规格:新增独立要求「launcher 内联多分支清单」,
不改写既有 launcher 要求块。理由:主规格上尚有未归档的同能力 delta
(`fix-mgh-sdr-host-error-capture`,已实现待归档)改写同一要求块,本 change 若再 MODIFIED
同一块会形成双 delta 叠写;ADDED 独立要求与归档顺序无关,两 change 任意顺序归档都安全。)

## Impact

- **代码**:`core/scripts/mgh_sdr_launch.py`(argparse + `_split_branch_list` 纯函数 +
  `main()` 分支清单选择段,约 +30/-3 行);随 install 分发副本由 install 机制自然更新。
- **测试**:`tests/test_mgh_sdr_launch.py` 新增一组(内联串行复用 `_FakeHostMixin`;
  互斥/空项/空串拒识;去重去空格;`--help` 含 flag——真子进程,镜像既有
  `test_help_documents_model_flag` 形态)。
- **规格**:`openspec/specs/security-design-review/` 新增 1 个 requirement(经本 change
  delta,3 个 scenario:内联串行同语义 / 双参数互斥拒识 / 空项拒识)。
- **文档**:README(研发仓人类面)多分支段补第三种喂法;命令的维护者 man 通俗说明
  (维护者私有文档区)与三面壳零触碰。
- **诚实边界**:`--branch-list` 是启动器人/cron 入口的参数,宿主会话内(三面壳)的
  `/mgh-sdr` 命令不受影响也不感知该参数。
