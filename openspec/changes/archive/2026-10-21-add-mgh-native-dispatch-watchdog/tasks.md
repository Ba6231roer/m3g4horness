## 1. 看门狗脚本(core/scripts/native_watchdog.py)

- [x] 1.1 骨架与契约:零依赖叶脚本(`--help` 即契约;stdout 恰好一行 JSON 摘要、stderr 心跳
  行、退出码 0/1/2);flag 面:`--root`/`--run-dir`/`--service-json`/`--poll-s`/`--ask-grace-s`/
  `--form-grace-s`/`--silence-s`/`--unit-deadline-s`/`--interrupt-settle-s`/`--deadline-s`/
  `--once`/`--dry-run`/`--interrupt-root`;验证:`--help` 输出含全部 flag 与缺省值
- [x] 1.2 服务发现与回环限定:`--service-json` > `[XDG_STATE_HOME 或 ~/.local/state]/opencode/
  service.json`;Basic 鉴权;url 主机 ∈ {127.0.0.1, localhost, ::1} 否则退出码 2;鉴权失败/
  连接丢失重读注册文件再试;密码只存内存;验证:红测锚「非回环 url 发起连接」为非法形态
- [x] 1.3 作用域圈定:根 = `--root` > `OPENCODE_SESSION_ID` env;按父 id 递归枚举后代;每次
  动作前重走目标祖先链复核(不过则放弃并记录);根不存在退出码 2 + recipe;验证:树外会话
  在全链测试中零处置断言
- [x] 1.4 巡检与判定:每 `--poll-s` 采集树内会话的活跃态/等待授权/等待表单/最近持久进展
  (会话更新、最新消息、最新工具时间取最大);授权与表单维护「首见」时刻;五类阈值判定
  (授权宽限 90/表单宽限 90/静默 1200/总时长 3600/中止复核 45,全可配);根豁免中止(除非
  `--interrupt-root`);验证:阈值边界用例(宽限-1 秒不动、+1 周期动)
- [x] 1.5 动作阶梯(受 `--dry-run` 约束):授权超宽限 → 回复 `reject + message`(NEVER
  once/always);表单超宽限 → 取消 + 提示;后代静默/超总时长 → 中止;中止后复核窗未落定 →
  再中止一次、仍不落定记「未收口」;根静默默认仅记录;验证:dry-run 下零写请求断言(假服
  务计数器)
- [x] 1.6 标记纪律与自退:全链零 `.done`/`.failed`/任何单元标记写入(测试断言 run 目录标记
  集不变);常驻自退 = 树落定(全空闲且无等待项,持续一个确认周期)或 `--deadline-s` 到
  点;`--once` 单扫即退;退出码语义:未收口/持续不可达/根缺失 → 2;验证:落定自退与预算
  自退两用例
- [x] 1.7 工件:`--run-dir` 时 events.jsonl 追加(动作/关键观测每行一 JSON,密码等敏感值
  永不入场)+ state.json 原子写(每周期至多一次);缺 `--run-dir` 不落盘;验证:文件形
  状、原子性(temp+rename spy)、摘要与 events 计数一致

## 2. 契约与测试

- [x] 2.1 同步 `core/contracts/fanout/runtime.md` 增「native watchdog」节:发现与回环限定/
  作用域与树外零触碰/阈值表(含「收敛上界非健康诊断」定性)/动作阶梯/dry-run/工件与退出
  码/非目标(零标记、零服务重启、不管理 shell API、不做限流判定)/版本矩阵(2.1.0 实机、
  2.0.32 待探测);验证:契约与实现逐项对得上
- [x] 2.2 新增 `tests/test_native_watchdog.py`:测试内起标准库假 HTTP 服务,覆盖——发现解析
  (缺省/覆盖/重读换密)/回环拒绝/根 env 与 flag 优先级/树枚举与树外零触碰/动作前祖先链复
  核/授权拒绝(含 never-approve 断言)/表单取消/静默与总时长中止/中止未收口两段记录/
  dry-run 零写/阈值边界/根豁免与 opt-in/--once/落定自退/预算自退/退出码三态/events+state
  工件/零标记断言;先红后绿;验证:全部用例过
- [x] 2.3 定向回归:`test_zero_deps` + `test_no_compile_warnings`(新脚本入扫描面);
  验证:逐一跑过无失败
- [x] 2.4 lint 四件套(check_contracts 新 --help 面 / purity 新分发脚本 / budget 无壳改动预
  期零增量 / plain_language)+ `openspec validate "add-mgh-native-dispatch-watchdog"
  --strict`;验证:与基线一致(无新增违例)

## 3. 实机闸门(本机 2.1.0,小阈值)

- [x] 3.1 等待授权形态:HTTP 创建带 ask 配置的探针会话触发越目录读(复现 pending)→ 小宽
  限看门狗 `--once` 处置 → 授权被拒、会话正常收尾、events 留痕;确认摘要退出码与计数正
  确;验证:命令与输出摘录入本 change 实机笔记
- [x] 3.2 无进展形态:创建一个不产出会话(或长静默会话)→ 小静默窗看门狗处置 → 会话
  `outcome=interrupted`;确认树外另一会话未被触碰;验证:记录进实机笔记
- [ ] 3.3 企业 2.0.32 探测(交接内网执行,不阻塞归档,附复现步骤):`--once --dry-run` 对
  真实服务跑一轮,确认发现/枚举/只读面兼容;验证:内网回执或差异清单回填契约版本矩阵

## 4. 收尾

- [x] 4.1 VERSION bump + CHANGELOG 分组条目(看门狗脚本/动作阶梯/零标记纪律/非目标边界)
- [x] 4.2 根 AGENTS.md R2 的 stdlib 列举补一行(urllib,仅本机回环 HTTP,零外网);实机笔
  记归位本 change 目录;验证:`test_distributed_md_purity` 复跑绿
