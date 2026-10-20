# Java Web 安全分析真仓测试 · 开源大仓调研报告

> 生成日期：2026-10-16 ｜ 数据来源：GitHub REST API 实测（仓库元信息 / 分支总数 / 语言字节）+ Gitee API + 公开 CVE 检索
> 用途锚点：为「Java Web 研发阶段安全设计缺失分析」管线选取**真实多分支大仓库**做本地真仓验证（银行内网画像：老技术栈、海量代码、代码不出内网）。

**一句话结论（榜单浓缩）**

- 只选一个全能主测仓：**Apache OFBiz**（业务系统密度 × 老栈 × CVE ground truth 最均衡）；
- 主打超大体量 / 跨分支 diff 压测：**Liferay、XWiki、dotCMS、Pentaho Kettle**；主打金融域贴合：**Fineract、jPOS、Kill Bill**；
- 国产老栈生态：**RuoYi / jeecg-boot / xxl-job / Nacos**（独立清单见第四节）。

---

## 一、选型依据

### 1.1 需求锚点

| 锚点 | 判定标准 |
|------|----------|
| 多分支 | 仓库分支总数 ≥ 10，且有可用的 release / 维护分支线（支撑跨分支 diff 测试） |
| 大规模 | Java 代码 ≥ 10 万行，报告中按 ≈10万 / 50万 / 百万+ 分档标注 |
| 真实工程仓 | 只收真实生产级项目；合成靶场（OWASP WebGoat / Benchmark、NIST Juliet）按约定不收录 |
| 领域 | 综合混合（金融业务系统 + 门户/CMS/ERP + 少量内网常见平台），按综合分排序 |
| 银行画像 | 技术栈老旧度、认证/授权/会话等安全设计样本密度、内网常见度纳入评分 |

### 1.2 评分维度与权重

| 维度 | 权重 | 说明 |
|------|:----:|------|
| D1 业务系统贴合度 | 25% | 是否是"带业务逻辑的系统"（ERP/计费/门户/CMS），而非纯中间件；银行视角的相关性 |
| D2 老栈 / 银行相似度 | 15% | Struts/Servlet/JSP/Groovy/JSF/Portlet/自研框架等老技术栈占比，与银行存量系统同构程度 |
| D3 代码规模 | 20% | Java 代码量分档（百万+ > 50万级 > 10万级），规模直接决定管线压力测试价值 |
| D4 多分支可测性 | 15% | 分支总数、release 维护线数量、仓库活跃度（pushed_at） |
| D5 CVE ground truth | 15% | 已知漏洞的数量、类型多样性（认证绕过/反序列化/注入/RCE），用于验证管线检出能力 |
| D6 落地成本 | 10% | 克隆体积、模块自包含程度、构建复杂度、License、是否活跃/归档 |

综合分 = Σ(维度得分 × 权重)，满分 5.0；D1–D6 每维 1~5 分（本次人工评定，依据实测数据 + 公开资料）。

### 1.3 数据口径说明（重要）

- **分支数**：GitHub API `/branches` 端点分页 Link 头实测的仓库分支总数（含全部历史/维护分支），采集于 2026-10-16；
- **代码规模**：GitHub `/languages` 返回的 Java 字节量 ÷ 40 ≈ 行数，**含测试代码与仓库内捆绑代码**（Liferay、Metasfresh、OpenAM 等仓捆绑/生成代码占比高，分档仅供选型参考；需精确数字请本地 cloc/scc 复核）；
- **License**：GitHub 自动识别结果，`NOASSERTION`/未识别表示仓库使用自定义或多重协议，使用前以仓库 LICENSE 文件为准；
- **活跃度**：主榜 15 仓中除 Kuali KFS（2018 冻结，刻意保留作老栈标本）外，其余均于 2026-10 仍有提交。

---

## 二、主榜 TOP 15（综合分排序）

| # | 仓库 | 综合分 | Java 规模（分档） | 分支数 | 老栈特征 | CVE ground truth 代表 |
|--:|------|:------:|------|------:|------|------|
| 1 | [apache/ofbiz-framework](https://github.com/apache/ofbiz-framework) | 4.5 | ≈50万行（Java 43万 + Groovy/FM） | 10 | Groovy + XML Widget + FreeMarker + MiniLang，自研 RBAC | CVE-2024-38856（CVSS 9.8 pre-auth RCE）、CVE-2024-45195（未认证 RCE） |
| 2 | [xwiki/xwiki-platform](https://github.com/xwiki/xwiki-platform) | 4.3 | ≈98万行（百万级压线） | 168 | Java + Velocity + Hibernate，组件化老平台 | CVE-2024-31982（默认可达 RCE）、用户权限绕过系列 |
| 3 | [liferay/liferay-portal](https://github.com/liferay/liferay-portal) | 4.2 | ≈1200万行（含捆绑，千万级） | 143 | JSP / Portlet / JSF + 新前端混合 | CVE-2020-7961（JSON 反序列化 RCE）、CVE-2024-26267 |
| 4 | [geoserver/geoserver](https://github.com/geoserver/geoserver) | 4.2 | ≈126万行 | 107 | Servlet + Spring + Jetty | CVE-2024-36401（XPath 注入 RCE，大规模在野利用） |
| 5 | [pentaho/pentaho-kettle](https://github.com/pentaho/pentaho-kettle) | 4.2 | ≈117万行 | 501 | Swing + 老插件体系（银行常用 ETL） | 公开 CVE 少（低密度对照样本） |
| 6 | [keycloak/keycloak](https://github.com/keycloak/keycloak) | 4.1 | ≈130万行 | 37 | Java（Quarkus/WildFly），IAM 认证授权全栈 | CVE-2025-11429（认证绕过）、CVE-2025-3910（2FA 绕过） |
| 7 | [metasfresh/metasfresh](https://github.com/metasfresh/metasfresh) | 4.1 | ≈320万行（含捆绑/生成） | 428 | Adempiere 血统 ERP | 公开 CVE 少 |
| 8 | [idempiere/idempiere](https://github.com/idempiere/idempiere) | 4.1 | ≈117万行 | 27 | OSGi + ZK，Compiere 血统 ERP | 公开 CVE 少 |
| 9 | [killbill/killbill](https://github.com/killbill/killbill) | 4.0 | ≈35万行 | 69 | Java 多模块 + JRuby 插件（计费/支付） | 公开 CVE 少 |
| 10 | [kuali/kfs](https://github.com/kuali/kfs) | 4.0 | ≈114万行 | 35 | **Struts 1 + JSP + OJB（教科书级老栈）** | 无公开 CVE（2018 冻结） |
| 11 | [jpos/jPOS](https://github.com/jpos/jPOS) | 4.0 | ≈18万行 | 57 | ISO-8583 支付交换框架，20 年演进 | 公开 CVE 少（支付域敏感） |
| 12 | [apache/fineract](https://github.com/apache/fineract) | 3.9 | ≈117万行（含大量集成测试） | 13 | Spring Boot + JPA 核心银行 | 公开 CVE 少 |
| 13 | [dotCMS/core](https://github.com/dotCMS/core) | 3.9 | ≈161万行 | **2261** | Java CMS + Angular 混合 | CVE-2022-26352（未认证反序列化 RCE） |
| 14 | [dhis2/dhis2-core](https://github.com/dhis2/dhis2-core) | 3.8 | ≈121万行 | **989** | Java + 老型 Web 层，敏感数据域 | 少量 XSS/权限类 advisory |
| 15 | [jenkinsci/jenkins](https://github.com/jenkinsci/jenkins) | 3.8 | ≈33万行（核心仓） | 57 | Java 老内核 + 插件生态 | CVE-2024-23897（CLI 任意文件读 → RCE） |

### 逐仓适配说明

**1. Apache OFBiz（综合分 4.5）**
ERP/财务/电商/制造一体的业务系统，自带完整 RBAC（SECURITY_GROUP/权限组）、发票/付款/总账模块，是"业务逻辑 + 权限设计"密度最高的真实样本。技术栈古老（Groovy、XML Widget、FreeMarker、MiniLang），与银行存量系统高度同构；2024 年起 CVE 连环爆发（CVE-2024-38856 CVSS 9.8 pre-auth RCE、CVE-2024-45195 未认证 RCE），官方安全页附带受影响版本与修复 commit 对照，ground truth 极佳。10 条 release 分支线（release17.12 → release24.09），克隆 753MB，Apache-2.0。

**2. XWiki Platform（4.3）**
企业级 wiki/知识管理平台，Java + Velocity + Hibernate 老栈、组件化程度高，业务对象（页面/权限/用户组）模型完整。168 个分支、每个 minor 版本一条 stable-*.x 维护线，非常适合跨分支 diff 测试；CVE 高产且官方 advisory 带修复对照（CVE-2024-31982 数据库搜索默认可达 RCE、多个用户权限绕过），能验证"设计缺失 → 修复补丁"的映射能力。≈98 万行 Java（+前端约百万级总量），LGPL-2.1，克隆 634MB。

**3. Liferay Portal（4.2）**
企业门户底座（银行网银门户/内部门户的同类产品），全场规模之王：Java 字节量 496MB（折算千万行级，含大量捆绑模块），143 个分支。历史 CVE 丰富且类型全（CVE-2020-7961 JSON 反序列化 RCE、CVE-2024-26267 信息泄露、SSRF/XSS 系列），是"超大仓 + 老门户栈"压力测试首选。⚠️ git 全量克隆约 43GB，建议 `--depth 1` 或 `--filter=blob:none` 分阶段拉取；License 为自定义（社区版历史为 LGPL 系），以仓库为准。

**4. GeoServer（4.2）**
Servlet + Spring + Jetty 服务端老栈，CVE-2024-36401（OGC Filter/XPath 注入 RCE）曾被大规模在野利用，配套 evaluateCollection 系列 property 注入 CVE——是"表达式注入类设计缺陷"的最佳验证素材。107 个分支覆盖各维护版本线（2.23.x → 2.2x/25.x），社区习惯为每个漏洞发布精准修复 commit。≈126 万行 Java，GPL-2.0（GitHub 识别为 NOASSERTION），克隆 647MB。

**5. Pentaho Kettle（4.2）**
银行内网最常见的 ETL/数据平台之一（数据迁移、报表加工场景多），501 个分支（版本维护线极多，跨分支测试素材量大），≈117 万行 Java，Swing + 老插件体系。公开 CVE 少（暴露面小），恰好可以当"低 CVE 密度大仓"，检验管线在高误报风险场景下的稳定性。738MB，License GitHub 未识别（以仓库 LICENSE 为准）。

**6. Keycloak（4.1）**
IAM 领域事实标准（银行统一认证/单点登录同类），认证、授权、会话、Token、强制动作等安全设计最密集——对"认证授权设计缺失"分析是天然的正反例对照库。≈130 万行 Java+TS，37 条 release/x.y.z 分支线；CVE-2025-11429 认证绕过、CVE-2025-3910 二次认证绕过等持续产出。Apache-2.0，克隆 609MB。

**7. Metasfresh（4.1）**
Adempiere 血统的开源 ERP（财务/仓库/生产/采购模块齐全），428 个分支，Java 字节量 129MB（折算 300 万+ 行，**含较多捆绑与生成代码**，业务逻辑密度建议抽样核验）。适合做"多分支 × 超大体量 ERP"组合测试。373MB，License GitHub 未识别（历史为 GPL 系，使用前自查）。

**8. iDempiere（4.1）**
Compiere → ADempiere → iDempiere 血统的开源 ERP，OSGi + ZK 老架构，总账/应收应付/资产模块完整，≈117 万行 Java、27 条 release 分支线。作为"老 ERP 栈"的活跃替代（ADempiere 分支数不达标），公开 CVE 少。408MB，License 以仓库为准（GPL 系）。

**9. Kill Bill（4.0）**
生产级计费/账务/支付平台（电信、SaaS 在用），Java 多模块 + JRuby 插件体系，≈35 万行、69 个分支，架构中 invoice/payment/entitlement 边界清晰，适合测"账务核心的安全设计"。Apache-2.0，克隆 666MB，持续活跃。

**10. Kuali KFS（4.0，冻结标本）**
高校财务系统（总账/采购/应付/差旅），**Struts 1 + JSP + OJB 的教科书级老栈**，≈114 万行、35 个分支。⚠️ 2018 年后冻结、无公开 CVE 记录——不能当演进仓用，但作为"银行老旧系统标本"（老栈 + 大体量 + 财务域三重契合）仍然稀缺。AGPL-3.0，克隆 430MB。

**11. jPOS（4.0）**
ISO-8583 支付交换/收单核心框架，20 年持续演进的金融老仓，≈18 万行、57 个分支；银行卡/支付域的报文解析、密钥、交易流水设计样本密集。AGPL-3.0（内网测试不涉及分发，合规无碍），克隆仅 72MB——全场最小克隆之一，适合作为金融域深化的低成本起点。

**12. Apache Fineract（3.9）**
Apache 官方核心银行/微金融平台（贷款/储蓄/会计分录/客户 KYC），Spring Boot + JPA；≈117 万行 Java 含大量集成测试与 Gherkin 场景（本身就是"安全相关测试资产"丰富的好样本）。13 条分支、克隆仅 123MB、Apache-2.0——**领域最贴 + 落地成本最低**的组合，适合管线首轮全量跑测。

**13. dotCMS（3.9）**
Java CMS/门户（内容 + 权限 + 工作流），≈161 万行 Java + 百万级前端代码；**2261 个分支全场冠军**（release-* 历史线保留极完整），跨分支 diff/历史漏洞回归素材最足。CVE-2022-26352 未认证反序列化 RCE 等存量漏洞可作 ground truth。1.2GB，License 分许可（社区版 GPL 系，以仓库为准）。

**14. DHIS2（3.8）**
政府级卫生信息系统（组织架构 + 数据权限 + 审批流，敏感数据域与银行同构），≈121 万行 Java、989 个分支（每个维护版本一线），BSD-3-Clause、389MB。非金融域，但"大数据量 + 细粒度共享权限"的设计缺陷样本多，且分支规模仅次于 dotCMS。

**15. Jenkins（3.8）**
CI/CD 内网标配（银行内网必有同类），核心仓 ≈33 万行 + 庞大插件生态，57 条 LTS 分支线规范。核心 CVE 丰富且可复现（CVE-2024-23897 CLI 任意文件读导致 RCE 等），MIT、克隆仅 169MB——轻量但 ground truth 密度高。

---

## 三、扩展榜（有效候选，未进 TOP 15）

| 仓库 | Java 规模 | 分支 | 一句话点评 |
|------|------|------:|------|
| [OpenIdentityPlatform/OpenAM](https://github.com/OpenIdentityPlatform/OpenAM) | ≈217万行 | 10 | OpenSSO 血统 SSO/IAM，极老栈；Keycloak 的老派备选 |
| [sakaiproject/sakai](https://github.com/sakaiproject/sakai) | ≈154万行 | 36 | 高校教学平台，JSF/Velocity 老栈，体量大但域偏远 |
| [adempiere/adempiere](https://github.com/adempiere/adempiere) | ≈130万行 | 6 | ERP 老祖，1.5GB 克隆；**分支数不达标（<10）** |
| [alkacon/opencms-core](https://github.com/alkacon/opencms-core) | ≈116万行 | 14 | 老牌 Java CMS，LGPL-2.1，活跃但社区小 |
| [thingsboard/thingsboard](https://github.com/thingsboard/thingsboard) | ≈90万行(+TS) | 106 | IoT 平台，有 SSRF/默认凭据类 advisory；域与银行弱相关 |
| [DSpace/DSpace](https://github.com/DSpace/DSpace) | ≈69万行 | 18 | 文献库平台，BSD-3，老 Spring 栈 + Angular |
| [BroadleafCommerce/BroadleafCommerce](https://github.com/BroadleafCommerce/BroadleafCommerce) | ≈35万行 | 68 | Spring 电商框架，域贴金融交易；License 需自查 |
| [openmrs/openmrs-core](https://github.com/openmrs/openmrs-core) | ≈26万行 | 67 | 医疗敏感数据域老栈（Spring/Hibernate/JSP） |
| [shopizer-ecommerce/shopizer](https://github.com/shopizer-ecommerce/shopizer) | ≈9万行 | 383 | Spring Boot 电商，压线规模；2025-03 起停更 |
| [camunda/camunda-bpm-platform](https://github.com/camunda/camunda-bpm-platform) | ≈116万行 | 147 | 银行常用 BPM；⚠️ 2025-11 已归档（Camunda 7 EOL 进程），可作冻结标本 |

**基础设施类备注**：Tomcat / WildFly / Solr / CXF / Hadoop / Elasticsearch 属于中间件而非业务系统，未参与综合排名；但若需要"分支冠军"（Elasticsearch 500+ 分支）或超大仓（Hadoop 百万行级）做极限压测，可自行补充。SonarQube 因定位为研发工具链且 License 变更，未纳入。

---

## 四、国产老栈独立清单（银行内网贴近度排序）

RuoYi 系与 jeecg 系是国内银行/国企内网管理后台、批量调度、注册配置中心的事实标准，单仓体量虽小，但 CVE 密度高、技术栈与真实内网环境同构，适合作为主榜大仓之外的"贴近度补充"。

| # | 项目 | 源仓库 | 规模 | 分支 | 特点 / 已知漏洞 |
|--:|------|------|------|-----:|------|
| 1 | RuoYi / RuoYi-Vue | [gitee.com/y_project/RuoYi](https://gitee.com/y_project/RuoYi) · [RuoYi-Vue](https://gitee.com/y_project/RuoYi-Vue)（GitHub 无官方镜像） | ≈4万行 | — | 4.89万★/4.32万★，MIT，2026-10 活跃；Shiro（经典版）+ Spring Security/JWT（Vue 版）经典三层；历史漏洞：任意文件下载/读取、dataScope SQL 注入、默认密钥等 |
| 2 | jeecg-boot | [github.com/jeecgboot/jeecg-boot](https://github.com/jeecgboot/jeecg-boot)（[Gitee](https://gitee.com/jeecg/jeecg-boot)） | ≈63万行(含Vue) | 5 | 4.82万★，Apache-2.0；CVE-2023-1454（jmreport SQLi）、CVE-2023-40989（SQLi）；jmreport/druid 未授权访问系列 |
| 3 | Nacos | [github.com/alibaba/nacos](https://github.com/alibaba/nacos) | ≈87万行 | 46 | 3.35万★，Apache-2.0；CVE-2021-29441/29442（认证绕过）、默认 token.secret.key、derby-console 未授权；内网注册/配置中心标配 |
| 4 | xxl-job | [github.com/xuxueli/xxl-job](https://github.com/xuxueli/xxl-job) | ≈3万行 | 31 | 3.06万★，GPL-3.0；默认 accessToken + 执行器未授权 RCE 系列；体量小、分支多，适合管线冒烟 |
| 5 | ruoyi-vue-pro（芋道） | [github.com/YunaiV/ruoyi-vue-pro](https://github.com/YunaiV/ruoyi-vue-pro)（[Gitee](https://gitee.com/zhijiantianya/ruoyi-vue-pro)） | ≈63万行 | 8 | 3.98万★，MIT；RuoYi 增强版（多租户/SaaS/支付模块），代码量大 |
| 6 | pig | [github.com/pig-mesh/pig](https://github.com/pig-mesh/pig)（[Gitee](https://gitee.com/log4j/pig)） | ≈3.8万行 | 6 | 6690★，Apache-2.0；Spring Cloud + OAuth2 微服务底座，微服务版老栈代表 |

---

## 五、不计入榜单的说明

- **合成靶场**：OWASP WebGoat / Benchmark、NIST Juliet 等按约定不收录（合成代码会干扰"安全设计缺失"类分析的有效性）；
- **归档/停更仓**：Camunda 7（2025-11 归档）、Kuali KFS（2018 冻结）、Shopizer（2025-03 停更）——前两者以"冻结标本"身份保留，不参与活跃度评分；
- **多仓生态**：Alfresco Community 拆分为数十个服务仓库，单仓无法呈现完整业务系统，未纳入；
- **分支数不达标**：ADempiere（6 个分支）虽规模/老栈优秀，但不满足 ≥10 分支锚点，移入扩展榜。

## 六、落地提示

- **巨型仓克隆**：Liferay 全量约 43GB，建议 `git clone --depth 1` 起步，或 `git clone --filter=blob:none`（先拿全分支引用，按需取 blob）平衡"多分支"与"体积"；
- **License 合规**：GeoServer / dotCMS / ADempiere（GPL 系）、jPOS / Kuali KFS（AGPL）仅内网测试不涉及分发，风险可控；对外输出报告或二次分发前请核对仓库 LICENSE；
- **口径复核**：本报告规模数据为 GitHub 语言字节折算（含测试与捆绑代码），对 Liferay / Metasfresh / OpenAM 这类捆绑大户，建议本地 `scc` 或 `cloc` 复核后再定管线跑批范围；
- **配额友好排序**：若先小后大做管线冒烟，可按"Fineract(123MB) → jPOS(72MB) → Jenkins(169MB) → OFBiz(753MB) → 百万级大仓"的顺序控制单仓索引与模型调用量，再进入 429 限流下的分批调度。

---
*AI生成*
