# 实机笔记 — add-mgh-native-dispatch-watchdog(0.1.85)

机器:维护者本机(Windows,Git Bash;`python` 可用)。日期:2026-10-20。
宿主:opencode 2.1.0 常驻服务(`~/.local/state/opencode/service.json`,url 回环)。
模型:全部探针会话钉 `zai-coding-plan/glm-5.3-flash`(与本仓前几次实机闸门同源)。

## 1. 闸门仓

`C:\DEV\_mgh_wd_gate`(scratch 真仓,保留作复现场),`.opencode/agent/` 两个探针
agent(均 `mode: primary` + `hidden: true`,照仓内既有 opencode agent 的 frontmatter
形制):

| agent | permission 要点 | 用途 |
| --- | --- | --- |
| `wd-ask` | `read: allow` + `bash/edit/webfetch: deny` + `question: deny` + `external_directory: ask` | 复现「等待授权」挂死;兼作树外旁观者 |
| `wd-sleep` | `bash: allow` + `external_directory: deny` | 复现「活着不收敛」(长静默 bash sleep) |

会话全部经 HTTP `POST /api/session`(带 `location.directory` 指向闸门仓;子会话带
`parentID`)+ `POST /api/session/:id/prompt` 驱动。

## 2. 任务 3.1:等待授权形态(单扫处置)

序列:创建 `wd-perm2` 会话(agent `wd-ask`)→ prompt「读
`C:/DEV/m3g4horness/VERSION` 并回第一行」→ ~18s 后出现 pending
`external_directory`(resources `C:/DEV/m3g4horness/*`)→ 看门狗:

```
python core/scripts/native_watchdog.py --root <perm-id> --once --ask-grace-s 0 \
  --run-dir C:/DEV/_mgh_wd_gate/run-perm
# exit 0 in 0.2s
# stdout: {"…","mode":"once","cycles":1,"sessions":1,
#          "permissions_rejected":1,…,"exit_reason":"once","ok":true}
# stderr: event: action_reject_permission session=<perm-id> …
```

- 处置后 pending 清零;~20s 内会话 `outcome=succeeded`(模型收到拒绝文案后正常收尾,
  与维护者私有文档区的 opencode 2.x 实测记录中「reject+message → 模型正常收尾」一致);
- `run-perm/watchdog/events.jsonl`:pending_seen → action_reject_permission → exit,
  三行;`state.json` 含树快照(`pending_perm:1 → 处置前快照`)与阈值表;
- **树外零触碰**:旁观者会话(agent `wd-ask`,同款 pending ask,但不在 `--root` 树内)
  全程 pending 保持 1、零写请求、outcome 不动;事后人工 reject 收尾 succeeded。
- 注:`--once` 与宽限的语义边界——首见时刻从看门狗上线起算,故 `--once` 要在同一次
  扫描内处置必须 `--ask-grace-s 0`(首见即拒);正宽限属于常驻模式的「下一周期判定」。

## 3. 任务 3.2:无进展后代形态(常驻静默窗处置)

序列:创建 parent(不 prompt,纯树根)→ 创建 child(`parentID=parent`,agent
`wd-sleep`)→ prompt「跑 `python -c "import time; time.sleep(600); print(1)"`」→
child 进入 active、无持久进展 → 看门狗:

```
python core/scripts/native_watchdog.py --root <parent-id> --poll-s 3 \
  --silence-s 15 --unit-deadline-s 3600 --deadline-s 150 \
  --run-dir C:/DEV/_mgh_wd_gate/run-stall4
# exit 0 in 12.8s
# stdout: {"…","mode":"resident","cycles":5,"sessions":2,"aborts":1,
#          "aborts_repeat":0,"unresolved":[],"exit_reason":"settled","ok":true}
# stderr: event: action_abort session=<child-id> repeat=False reason=silence
```

- child 被 `interrupt?resume=false` 中止:`outcome=interrupted`、移出 active;
- 树落定自退(settled):child 终态 + parent 空闲,确认周期后退出码 0;
- parent(outcome None、非 active)全程零触碰;旁观者(上一节同一会话)依旧零触碰。

## 4. 附带实得(两个钉扎级发现)

1. **根豁免默认形态实机验证**:早期 3.2 尝试把「无进展会话」直接作 `--root` 跑
   (`run-stall/`),看门狗 41 周期只记录不动作——`root_stall` 事件逐字:
   `{"kind":"root_stall","reason":"silence","note":"recorded only; pass
   --interrupt-root to act"}`,预算到点 `exit_reason=deadline` 退出码 0。规格动作阶梯
   第 5 条的默认豁免与实机一致。
2. **interrupt 端点响应不带 `{"data":…}` 信封**(其余端点均带):实机返回裸
   `{interrupted,…}`。首版客户端按信封解析,把已落地的中止误记为 `action_skipped_gone`
   (闸门当场暴露:child outcome=interrupted 但 aborts=0)——已修 + 契约钉扎 +
   假服务改回真实形状(裸响应)防回退。

另一个观测:长 bash 执行期间会话 `time.updated` **冻结不推进**(持久进展不随 token/流
心跳走,正是静默判定需要的「持久边界」粒度);assistant 消息的 `time.streamed`(流完成
时刻)可能比 `updated` 更新,已并入进展候选(max 而非替代)。

## 5. 任务 3.3:企业 2.0.32 探测清单(交接内网执行,不阻塞归档)

对真实服务跑一轮只读探测,确认发现/枚举/只读面兼容;任何差异回填契约版本矩阵:

1. `opencode --version` 确认 2.0.32;`opencode debug paths` 找服务注册文件实际路径
   (默认假设 `~/.local/state/opencode/service.json`,若 2.0.32 不同,记录差异)。
2. `python <repo>/core/scripts/native_watchdog.py --root <一个真实在跑的会话 id> \
   --once --dry-run --run-dir <tmp>`——预期:退出码 0、stdout 摘要 `dry_run:true`、
   events/state 落盘、**服务端零写请求**;`sessions` ≥ 1(枚举面可用)。
3. 负样例:`--service-json` 指向一个手写注册文件(url 用局域网 IP)→ 预期退出码 2、
   `exit_reason":"non_loopback"`、零连接。
4. 根缺失负样例:`--root ses_does_not_exist` → 预期退出码 2、`root_missing`。
5. 差异关注点(逐项对 2.1.0 的钉扎):`/api/session?parentID=` 过滤、
   `/api/session/active` 返回 map、`/api/session/{id}/permission|form` 列表形状、
   消息分页字段(`time.created`/`time.streamed`)、信封 `{"data":…}`、interrupt 裸响应。
   任一 404/形状漂移 = 记进契约版本矩阵差异行,不改代码(2.0.32 兼容以探测回执为准)。

## 6. 单测与回归摘要(先红后绿)

- `tests/test_native_watchdog.py`:41 测(假服务 = 标准库 ThreadingHTTPServer 镜像
  钉扎面;时序边界用注入时钟的 stub client,零真实 sleep 等待)。先红
  (脚本不存在,import 全错)→ 绿 41 测。
- 红转绿过程修掉的实现缺陷(测试当场抓到):① 中止动作此前**没有**走动作前祖先链复核
  (规格「每次动作前」);② 首见宽限用严格 `>` 导致 `--once --ask-grace-s 0` 永不动作
  (与「宽限 0 = 立即拒绝」矛盾);③ 写请求 404(目标在两动作间消失)曾被计入动作数。
- 定向回归:`test_zero_deps`(13 测)+ `test_no_compile_warnings` 绿;
  lint 四件套:contracts 504 flags / purity 338 文件 0 违例(contract 初稿曾引
  `core/scripts/` 前缀被 purity 拦下一次,改裸文件名后净)/ budget 17 壳 /
  plain_language exit 0;`openspec validate add-mgh-native-dispatch-watchdog
  --strict` valid。
