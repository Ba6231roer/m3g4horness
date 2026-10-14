# Tasks — add-mgh-telemetry-seam

> 实现顺序按依赖排：先写遥测模块（采集链 + 冷却 + 中文映射单源）→ 再挂七个启动路径脚本（壳零改动）→ 再补测试 → 再过 install/lint 与披露面 → 收尾接口文档落地与版本。
> 每条均可独立验收。服务端不在本仓实现——维护者拿本 change 的 `interface.md` 去实现，客户端默认惰性、可先行合入。

## 1. 遥测模块

- [x] 1.1 新增 `core/scripts/mgh_telemetry.py`（仅标准库，**导入 + CLI 双形态**）：`fire(method, params, marker_dir)` 内部吞掉一切异常；CLI flags `--method`/`--params`/`--marker-dir`，退出码一切结果 0、argparse 误用 2（docstring Exit codes 段显式声明该 R5.3 偏差及理由，见 design D5）
- [x] 1.2 采集链实现：username 五级链与 `\` 剥域、ip 三级 UDP-connect 链、params 500 字符截断、time 恒 10、operation 闭集中文映射（模块内字典单源，见 design D7；映射外 method 回退原文）
- [x] 1.3 上报实现：端点解析（env `MGH_TELEMETRY_URL` > 内置默认常量（初始空）> 静默跳过）、显式空 `ProxyHandler` 直连、内部超时约 2s、`urllib` 单次 POST、stdout 恒一行 `{"sent":bool,"reason":str}`
- [x] 1.4 冷却标记（见 design D6）：`<marker_dir>/telemetry_last.json`（时间戳 + method），距上次上报不足冷却阈值（模块常量，默认 30 分钟）静默跳过；标记不可读写视同无标记（不阻塞）

## 2. 挂载（七个既有脚本；壳零改动）

- [x] 2.1 `write_runconfig.py`（mgh-init fresh）：末尾 try 包裹 import+fire（design D5 四行模式），params=真实 argv，marker_dir=`<target>/.mgh-init`
- [x] 2.2 `resume_state.py`（mgh-init resume/查询）：derive 主路径同型挂载，params=`--resume` + run_config.json 用户 flag 重建（尽力而为，缺失不阻塞）
- [x] 2.3 `write_ut_runconfig.py` + `resume_ut_init_state.py`（mgh-ut-init）：同 2.1/2.2 同构
- [x] 2.4 `sdr_context.py`（mgh-sdr fresh step 1）+ `resume_sdr_state.py`（derive 路径；`--arm-sentinel` 路径**不**挂，见 design D2）：marker_dir=`<run-dir>`
- [x] 2.5 `prepare_augment.py`（mgh-sra）：marker_dir=change 根；`ingest_requirements.py`（mgh-srr）：marker_dir=`<out-dir>`
- [x] 2.6 逐脚本核对：挂载后该脚本的既有 stdout/stderr/退出码/产物 schema/`--check` 行为零变化（含遥测模块被删除/网络死亡两种模拟）

## 3. 测试

- [x] 3.1 新增 `tests/test_mgh_telemetry.py`：operation 映射闭集内容锚（六条精确中文）、域名剥离、username/ip 链逐级降级（mock）、全败 `unknown`、载荷恰六键且 time==10、params 500 截断、env 与常量皆空时 `urlopen` 零调用、不可达端点 sent=false 且不抛、冷却窗口（首次报/窗口内抑制/过窗再报）、标记损坏不阻塞、缺 `--method` exit 2
- [x] 3.2 挂载点测试：七个脚本各自的既有测试文件各补一条——monkeypatch `mgh_telemetry.fire` 断言被调且参数形状正确；再断言 fire 抛异常/模块缺失时宿主脚本退出码与产物不变（2.6 的自动化面）
- [x] 3.3 挂载点存在性锚测：七个脚本源码各含 `import mgh_telemetry` 与 `fire("` 调用行（防后续重构静默脱落）

## 4. 安装、lint 与披露

- [x] 4.1 `install.sh` 共定位自检清单续行 +`mgh_telemetry`，同步 ✓ 提示文案（真跑一次 install 验证消息含新名）
- [x] 4.2 `py tools/check_distributed_purity.py` 过（新模块与挂载行无 dev-meta、无研发私档指针——模块 NEVER 引用接口文档，见 design D9）
- [x] 4.3 `py tests/test_zero_deps.py` 与 `py tests/test_no_compile_warnings.py` 过（urllib/socket/getpass 属 `sys.stdlib_module_names`，无需扩白名单）
- [x] 4.4 披露面：AGENTS.md——R2 段 stdlib 模块列举补 `urllib/socket/getpass`（注明仅遥测模块使用、发往内网端点）、「改动面→测试」映射表 +`mgh_telemetry.py` 行、诚实边界 +一条（启动遥测尽力而为 / 未配置端点零网络 / resume 计数为冷却窗口近似 / params 可能含内网路径）；README 使用统计披露段（同口径，面向使用者）
- [x] 4.5 `docs/glossary.md` 补词条：遥测、埋点、端点（R3：人类面用词先入词典；`interface.md` 内另带自包含小术语表）

## 5. 接口文档落地与收尾

- [x] 5.1 接口文档落 `docs/mgh-telemetry-api.md`（以本 change `interface.md` 为源；本 change 的需求本身包含写这份文档，属 R5.11 豁免；服务端 URL 就绪后回填模块内置常量一行即激活）
- [x] 5.2 定向回归：`tests/test_mgh_telemetry.py` + 2.2 七个挂载脚本的既有测试文件（`test_write_runconfig` / `test_resume_state` / `test_write_ut_runconfig` / `test_resume_ut_init_state` / `test_sdr_context` / `test_resume_sdr_state` / `test_sra_prepare` / `test_srr_ingest`）+ `tests/test_distributed_md_purity.py` + 4.3 两件
- [x] 5.3 实机冒烟（隔离小目标仓）：① env 未设 → 零网络行为、init/sdr 正常跑完；② env 指向本地临时 http 接收器（标准库 `http.server` 几行）→ 收到恰六字段载荷、中文 operation 不乱码、同一 run 反复 `resume_state` 查询只报一条；③ env 指向不可达端口 → 退出码与产物不受影响；④ 删掉 `mgh_telemetry.py` 模拟版本错位 → 挂载脚本仍正常
- [x] 5.4 VERSION / CHANGELOG bump；`openspec validate add-mgh-telemetry-seam --strict` 过
