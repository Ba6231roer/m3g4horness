## 1. 前置拍板

- [x] 1.1 与维护者确认特殊授权文档是否随包(design D6,缺省不随包;若改随包:staging 拷贝一行语义 + 一个测试锚,并同步修订 proposal「非目标」表述)——按缺省「不随包」执行(apply 启动即对已披露缺省的确认);若后续要随包,增量见 5.4 同款一行语义 + 一个测试锚

## 2. 打包工具与静态资产

- [x] 2.1 新增 `tools/pack_release.py`(纯标准库 zipfile/pathlib/argparse):输入 `--staging` 与 `--out`;条目相对 staging 根、arcname 归一前向斜杠;压缩前对 staging 内 `__pycache__` 目录与散装 `.pyc/.pyo` 做确定性清除并断言为零;staging 缺失/输出路径不可写 → 退出码 2 fail-loud
- [x] 2.2 新增 `releases/opencode/SKILL.md`:frontmatter `name: m3g4horness` + 非空 description(一句功能概括);正文惰性声明(仅为 skillhub 上传格式要求、非功能入口、解压后可删除);确认 opencode 安装分支(只拷 command/agent/hooks 三子目录)零触它

## 3. install.sh 打包模式

- [x] 3.1 参数解析:`--pack`(缺省文件名)与 `--pack=<路径>`(显式路径)两形;`--help` 文本补打包模式与互斥说明
- [x] 3.2 fail-loud 互斥(design D7):`--pack` × `--claude`/`--dsh` → 退出码 2 + 原因;`--pack` × `--no-enforce-hook` → 退出码 2 + 说明;VERSION 文件缺失/空 → 退出码 2(显式路径同样拒);另拒位置参数目标(staging 内建,目标参数无意义)
- [x] 3.3 staging 流程(design D3):`mktemp -d` 后把安装目标指向 staging,既有安装步骤原样执行;成功删 staging,任一步失败保留 staging 并 stderr 打印路径(ERR trap 兜底)
- [x] 3.4 完整性硬闸(design D4):四组既有自检(脚本族共存/fan-out 资产/subagent 清单/分发纯净)在打包模式由 warn 升格为收集汇总后非空即退出码 2;补四处打包专属断言(plugins 恰两件、hooks 守卫脚本、staging 根 SKILL.md、`.mgh-sra` 敏感目录模板)+ 命令壳七件闭集
- [x] 3.5 压包与收尾:调 `tools/pack_release.py`;缺省输出 `m3g4horness-<版本>-opencode.zip`(版本取自 VERSION,去空白);成功输出包路径 + 「上传内网 skillhub」提示行
- [x] 3.6 字节码清理扩展(design D8):既有清理命令扩为 `__pycache__` 目录 + 散装 `*.py[cod]` 文件,对全部安装面生效

## 4. 测试

- [x] 4.1 新增 `tests/test_install_pack.py`(真跑 `install.sh --pack` 到 scratch 目标;harness 内置 py→sys.executable 垫片):zip 存在且文件名含 VERSION;顶层恰三闭集条目;`.opencode` 五树关键资产逐项在场(command 全部命令壳/agent 全部 subagent 定义〔含五原生孪生 spot〕/hooks 守卫脚本/plugins 恰两件/mgh-core 的 scripts+prompts+contracts);`.mgh-sra` 模板在场;SKILL.md frontmatter 形状;zip 内零字节码条目——21 用例全绿(~35s)
- [x] 4.2 fail-loud 用例:`--pack --claude`、`--pack --dsh`、`--pack --no-enforce-hook`、位置参数目标、`--pack=` 空值、VERSION 置空、VERSION 移除——均退出码 2 且无 zip 产出;缺件形态(repo-lite 动态抽插件)stderr 含缺失资产名且 staging 保留
- [x] 4.3 解压等价用例:同一干净目录分别「解压包内容」与「install.sh --opencode 安装」,落地树逐字节比对一致,差集恰为根上 SKILL.md
- [x] 4.4 普通安装零影响用例:不带 `--pack` 安装的落地树无 SKILL.md;发行树预置散装 `.pyc` 后普通安装,目标树零字节码(覆盖 3.6 对普通安装的生效)
- [x] 4.5 `test_zero_deps`/`test_no_compile_warnings` 覆盖新脚本通过;lint 四件套零新增违例(check_contracts 498 flag OK/check_distributed_purity 350 文件 clean 含新 SKILL.md/check_distributed_prompt_budget 17 壳内/check_plain_language 存量三旧 proposal 缺人话序,本 change 不在名单);定向回归 test_install_hook / test_install_opencode_plugin / test_install_special_auth / test_distributed_md_purity / test_install_dsh(65s,27 测)全绿

## 5. 文档与版本

- [x] 5.1 VERSION bump 0.1.96 → 0.1.97 + CHANGELOG 条目(Keep a Changelog 格式,[Unreleased] 顶部)
- [x] 5.2 根 AGENTS.md:快速命令补打包一行;目录布局 install.sh 行补 --pack;「改动面 → 测试文件」映射表补 `install.sh --pack` → `test_install_pack` 一行;诚实边界补「zip 分发通道」一条(解压根层级风险由发布说明页承载/解压覆盖不清理旧文件/包内容为顶层三闭集)
- [x] 5.3 README 补发布渠道一段:企业用户经内网 skillhub 获取 zip 包,解压到项目根即完成安装;使用方式见发布说明页;明确「解压包内容、勿套同名文件夹」
- [x] 5.4 不适用——1.1 拍板为不随包(缺省),无随包语义需落地

## 6. 实机闸门

- [x] 6.1 本机真跑一次 `install.sh --pack`(垫 py 转发),人工抽查:zip 顶层恰三闭集(`.mgh-sra`/`.opencode`/`SKILL.md`)、224 文件、零字节码、staging 成功即删
- [x] 6.2 包内容与一次普通安装落地树 `diff -r` 逐字节比对:唯一差异 = 解压侧多出根上 SKILL.md,其余 223 文件全同

## 7. apply 期补充(维护者拍板:多开发机 py/python 各有真身,仓库自适应)

- [x] 7.1 install.sh / install.ps1 补 step 0 解释器探测(py/python/python3 取第一个 ≥3.10 真解释器,与分发壳 step 0 同款;全缺 fail-loud 退出码 1),全部解释器调用点换用探测结果(install.sh 10 处/ps1 4 处);smoke 三形态过(真 py 优先/坏 py 回退 python/全坏 fail-loud);test_install_pack + test_install_dsh 无手工垫片直跑全绿;根 AGENTS.md 两处「本机哪个是坏的」机器特定备注改为探测描述;proposal Impact 与 design 风险节同步(design D10)
