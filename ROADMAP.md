# StockOverflow Roadmap

> 一站式智能股票分析平台 — 面向投资小白，赋能进阶用户

## 愿景

让每个普通投资者都能像专业量化分析师一样：**看懂数据 → 理解指标 → 理性决策 → 验证策略 → 稳健交易**。

---

## 阶段总览

```
Phase 1 — 地基加固          ████████░░░░░░░░░░░░  ~2 周
Phase 2 — 数据 & 新闻      ████████████░░░░░░░░  ~2 周
Phase 3 — LLM 智能层       ████████████████░░░░  ~2 周
Phase 4 — 因子挖掘实验室    ████████████████████  ~3 周
Phase 5 — 回测 & 模拟交易   ████████████████████  ~3 周
Phase 6 — 商品级前端        ████████████████████  ~3 周
Phase 7 — 生产化 & 部署     ████████████████████  ~2 周
```

---

## Phase 1 — 地基加固（Foundation）

> 目标：让现有功能稳定可靠，为后续扩展打好基础。

### 1.1 数据层重构

- [x] **数据库升级**：SQLite WAL 模式 + busy_timeout=5000，支持并发读写
- [x] **历史数据全量保存**：可配置周期（1y/2y/5y/max），通过 `?period=2y` 参数或 `.env` 默认值
- [x] **数据版本管理**：`data_fetch_log` 表记录每次 fetch 的时间戳、周期、新增条数
- [x] **增量更新**：只拉取 DB 中最新日期之后的数据，已缓存且 ≤1天直接返回
- [ ] **多数据源容灾**：yfinance 失败时自动降级到 Alpha Vantage / Twelve Data / Polygon.io
- [x] **数据完整性校验**：检查缺失交易日，报告完整度百分比

### 1.2 后端架构优化

- [ ] **异步化**：yfinance 调用改为 async（httpx async + asyncio）
- [x] **请求队列**：LLM 调用加入队列管理，避免并发打爆 API
- [x] **缓存层**：内存 LRU 缓存热数据（50 stocks, 5min TTL）
- [x] **错误处理统一**：所有 API 返回统一错误格式 `{error, code, detail}` + 自定义异常类
- [x] **日志系统**：structlog 结构化日志，便于排查问题
- [x] **配置管理**：`.env` 文件 + pydantic-settings，区分 dev/prod

### 1.3 前端基础改进

- [x] **路由系统**：History API 路由，支持 `/stock/AAPL` 直接访问 + 前进后退
- [x] **加载状态优化**：骨架屏替代简单 spinner
- [x] **错误边界**：全局错误捕获 + 友好提示（toast 通知）
- [x] **响应式布局**：移动端适配（768px 断点，iOS zoom 修复）

---

## Phase 2 — 数据丰富 & 新闻资讯（Data & News）

> 目标：让 LLM 拥有更全面的上下文，让用户看到"发生了什么"。

### 2.1 企业新闻资讯

- [x] **yfinance 新闻接口**：`yf.Ticker.news` 获取个股新闻
- [x] **多源新闻聚合**：
  - Yahoo Finance（yfinance）
  - Finviz 新闻
- [x] **新闻缓存**：每只股票的新闻独立缓存，TTL 1 小时
- [x] **新闻 API 端点**：`GET /api/stock/{ticker}/news`
- [x] **新闻结构化**：提取标题、来源、时间、URL、摘要

### 2.2 新闻前端展示

- [x] **新闻面板**：图表下方显示最新新闻
- [x] **新闻卡片**：标题 + 来源 + 时间 + 可点击跳转
- [x] **新闻情绪标签**：LLM 分析每条新闻的 Bullish/Bearish/Neutral 情绪

### 2.3 新闻 → LLM 整合

- [x] **结构化 Prompt 增强**：将最近 5 条新闻作为上下文传入 LLM
- [x] **新闻影响分析**：LLM 输出中包含 news_impact 字段，标注新闻影响
- [x] **新闻关键词提取**：LLM 提取每条新闻的 1-3 个关键词

### 2.4 更多数据维度

- [x] **财报数据**：`yf.Ticker.quarterly_financials`，展示 EPS / Revenue 趋势 + API + 前端表格
- [x] **机构持仓**：`yf.Ticker.institutional_holders`，API 已集成
- [x] **期权数据**：`yf.Ticker.options`，展示期权链（calls/puts）
- [x] **分红/拆股历史**：`yf.Ticker.dividends`，API 已集成
- [x] **同行对比**：同行业/板块 ETF 基准对比

---

## Phase 3 — LLM 智能层增强（Intelligence Layer）

> 目标：让 LLM 从"回答工具"升级为"投资顾问"。

### 3.1 LLM 核心增强

- [x] **多轮对话**：支持用户就某只股票追问（"为什么建议买？"、"止损设多少合适？"）
- [x] **对话历史持久化**：保存在 SQLite 中，支持查看历史分析
- [x] **流式输出**：SSE 流式返回 LLM 结果，实时显示分析过程
- [x] **多模型支持**：
  - 预设模型列表（GPT-4o, Claude, Gemini, DeepSeek, Qwen）
  - 本地模型支持（Ollama）
  - 模型 A/B 对比
- [x] **Prompt 版本管理**：系统提示词可编辑、可版本回退

### 3.2 LLM 新增功能

- [x] **投资百科问答**：不绑定股票，回答通用投资问题（"什么是 MACD？"）
- [x] **策略解释器**：用通俗语言解释每个指标的含义和当前状态
- [x] **风险评估**：根据波动率、最大回撤、VaR、夏普比率给出风险评级
- [x] **定投建议**：基于估值水平给出定投金额建议（INCREASE/MAINTAIN/DECREASE/PAUSE）
- [x] **学习路径推荐**：根据用户水平和兴趣推荐学习内容（LLM 生成）

### 3.3 LLM 输出增强

- [x] **结构化报告**：生成可下载的 Markdown/PDF 分析报告
- [x] **图表标注**：LLM 标注关键支撑/阻力位（3 support + 3 resistance levels）
- [x] **置信度校准**：根据历史预测准确率调整置信度（overconfident/underconfident 检测）
- [x] **多空对比**：同时输出看多和看空的理由，让用户自行判断

---

## Phase 4 — 因子挖掘实验室（Factor Lab）

> 目标：让进阶用户像搭积木一样构建量化因子。

### 4.1 低代码因子编辑器

- [ ] **可视化因子构建器**：
  - 拖拽式节点编辑器（类似 Node-RED / Unreal Blueprint）
  - 节点类型：数据源、算子、阈值、逻辑门、输出
  - 示例因子：`RSI(14) < 30 AND MACD_crossover AND Volume > SMA(Volume, 20)`
- [x] **表达式编辑器**：支持直接写表达式（如 `rsi(14) < 30 and macd_cross('bullish')`）
- [x] **内置因子库**：
  - 动量因子（N日收益率、相对强弱）
  - 波动率因子（历史波动率、GARCH）
  - 价值因子（PE、PB、PS — 需扩展数据源）
  - 资金流因子（OBV、MFI、成交量异动）
  - 情绪因子（新闻情绪、CNN F&G）
- [x] **自定义因子注册**：用户创建的因子可保存、命名、删除

### 4.2 因子可视化

- [x] **因子值时间序列图**：展示因子值随时间的变化
- [x] **因子分布图**：直方图 + 统计量（均值/标准差/百分位数）
- [x] **因子分组回测**：按因子值分 5 组（quintile），对比各组收益 + 单调性检验
- [x] **IC 值分析**：因子值与未来收益的 Rank IC 时序图
- [x] **因子相关性矩阵**：热力图展示因子间相关性
- [x] **因子衰减分析**：因子预测力随持有期的变化 + 半衰期计算

### 4.3 因子组合

- [x] **多因子加权**：手动权重组合 + Z-score 标准化 + Quintile 分析
- [x] **因子正交化**：Gram-Schmidt 去除因子间共线性
- [x] **因子中性化**：去均值 + 去趋势 + 滚动 Z-score 标准化

---

## Phase 5 — 回测 & 模拟交易（Backtesting & Trading）

> 目标：让用户在不花一分钱的情况下验证策略。

### 5.1 历史回测引擎

- [x] **事件驱动回测框架**：
  - 数据馈送 → 信号生成 → 风控过滤 → 订单执行 → 持仓管理 → 绩效统计
  - 支持日线回测
- [x] **回测配置**：
  - 初始资金、手续费率、滑点模型
  - 止损/止盈百分比
  - 基准对比（SPY / QQQ / 自定义）
  - 时间范围选择
- [x] **回测结果展示**：
  - 累计收益曲线
  - 年化收益率、最大回撤、夏普比率、胜率、盈亏比
  - 交易明细表（每笔买卖记录）
  - 净值曲线图
- [x] **多策略对比**：同时运行多个策略，对比绩效（按 Sharpe 排名）

### 5.2 实盘回测（Walk-Forward）

- [x] **滚动窗口回测**：避免前视偏差（train/test split + consistency 指标）
- [x] **参数敏感性分析**：网格搜索最优参数区间
- [x] **Monte Carlo 模拟**：随机打乱交易顺序，评估策略稳健性（盈利概率、置信区间）
- [x] **样本外验证**：自动划分训练集/测试集 + robustness 评分

### 5.3 模拟交易

- [x] **实时模拟账户**：
  - 虚拟资金（可自定义金额）
  - 实时价格撮合
  - 持仓跟踪 + 浮盈浮亏计算
- [x] **订单类型**：
  - 限价单 / 市价单
  - 止损单 / 止盈单
  - 追踪止损
- [x] **交易日志**：每笔交易记录时间、价格、数量、理由
- [x] **绩效仪表盘**：
  - 总资产曲线
  - 交易统计（总交易量、费用、最常交易股票）
  - 胜率 / 盈亏比
  - 最大连续亏损

### 5.4 仓位管理

- [x] **仓位记录**：手动/自动记录买入卖出
- [x] **成本基础追踪**：FIFO / LIFO / 平均成本法
- [x] **盈亏分析**：已实现 / 未实现盈亏
- [x] **税务报告**：年度资本利得汇总（FIFO + short/long term）
- [x] **再平衡建议**：根据目标配置给出调仓建议（等权/自定义权重）

---

## Phase 6 — 商品级前端（Production Frontend）

> 目标：从"能用"变成"好用想用"。

### 6.1 UI 框架升级

- [ ] **迁移至现代框架**：React / Vue / Svelte（推荐 SvelteKit 或 Next.js）
- [ ] **组件库**：Shadcn / Radix / Ant Design 定制主题
- [x] **设计系统**：
  - 统一的色彩体系（dark/light 主题）
  - 字体规范（数字等宽字体）
  - 间距 & 圆角规范（CSS 变量：space-xs~2xl, radius-sm~full）
  - 动效规范（transition 0.3s）
- [x] **图标系统**：Lucide Icons（CDN + data-lucide 属性）

### 6.2 核心页面

- [x] **Dashboard 首页**：
  - 自选股列表 + 实时报价
  - 最近分析记录
  - 最近 LLM 预测
  - 纸盘交易账户概览
- [x] **Watchlist 自选股**：
  - 添加/删除自选股（☆/★ 按钮）
  - 自选股列表显示实时价格、涨跌幅
  - 点击跳转到个股详情
  - 持久化到数据库
- [x] **个股详情页**（当前页面的升级版）：
  - 多标签页布局：图表 / 指标 / 新闻 / LLM分析 / 回测
  - 侧边栏：快速切换自选股
  - 全屏图表模式（f 键或⛶按钮）
- [x] **因子实验室页**：表达式编辑 + 内置库 + 保存 + 回测 + 对比 + 敏感性 + 分布 + Quintile + IC + 衰减 + 多因子 + 正交化 + 中性化 + 相关性（SPA 内嵌）
- [x] **回测 & 交易页**：策略配置 + 净值曲线 + 策略对比 + Monte Carlo + Walk-forward + OOS + 模拟交易 + 限价单（SPA 内嵌）
- [x] **设置页**：LLM 配置（Base URL / Key / Model / Presets）+ 主题 + 语言（模态框）

### 6.3 交互体验

- [x] **键盘快捷键**：`/` 搜索，`Esc` 关闭，`t` 切换主题，`s` 设置，`d` 首页，`p` 预测
- [ ] **拖拽布局**：用户可自定义面板排列
- [x] **实时更新**：WebSocket 推送价格变动（30s 轮询 + 实时价格显示）
- [x] **通知系统**：Toast 通知（错误/警告/信息）+ LLM 预测完成通知
- [x] **深链分享**：分享特定股票+指标配置的 URL

### 6.4 国际化

- [x] **中英文切换**：i18n 支持（🌐 按钮切换，自动检测浏览器语言）
- [x] **货币格式化**：根据市场自动适配（Intl.NumberFormat）
- [x] **时区处理**：自动转换为用户本地时间（Intl.DateTimeFormat）

---

## Phase 7 — 生产化 & 部署（Production）

> 目标：让项目可以稳定运行、方便部署。

### 7.1 测试

- [x] **单元测试**：指标计算、数据处理逻辑（pytest — 34 tests）
- [x] **API 测试**：端到端接口测试（httpx + pytest — 23 tests）
- [ ] **前端测试**：关键交互流程（Playwright）
- [ ] **回测验证**：与 TradingView / backtrader 对比验证指标正确性

### 7.2 CI/CD

- [x] **GitHub Actions**：push 自动 test
- [x] **Docker 化**：Dockerfile + docker-compose（backend + frontend + db）
- [x] **一键部署脚本**：支持 Railway / Fly.io / 自建 VPS（railway.toml + fly.toml + Dockerfile）

### 7.3 文档

- [x] **用户指南**：面向小白的图文教程（USER_GUIDE.md）
- [x] **API 文档**：自动生成（FastAPI 自带 Swagger + ReDoc）
- [x] **开发者文档**：架构说明、贡献指南
- [x] **指标白皮书**：每个指标的计算公式 + 信号逻辑详解（INDICATORS.md）

### 7.4 安全 & 性能

- [x] **API Key 安全**：服务端存储，GET 响应中移除 api_key 字段，仅返回 masked
- [x] **请求限流**：防止滥用（slowapi — 60/min default, 5/min for LLM）
- [x] **数据备份**：SQLite 手动/自动备份 + 列表 + 恢复（保留最近 10 份）
- [x] **性能监控**：API 响应时间追踪（avg/max per endpoint）

---

## 技术栈规划

```
┌─────────────────────────────────────────────────┐
│                    Frontend                      │
│  SvelteKit / Next.js  +  TradingView Charts     │
│  Shadcn UI  +  D3.js (可视化)  +  React Flow    │
├─────────────────────────────────────────────────┤
│                    Backend                       │
│  FastAPI  +  SQLAlchemy  +  Celery (任务队列)    │
│  OpenAI SDK  +  httpx  +  pandas/numpy          │
├─────────────────────────────────────────────────┤
│                    Data                          │
│  SQLite/PostgreSQL  +  Redis (缓存)              │
│  yfinance  +  CNN API  +  News RSS              │
├─────────────────────────────────────────────────┤
│                    Deploy                        │
│  Docker  +  GitHub Actions  +  Fly.io/Railway   │
└─────────────────────────────────────────────────┘
```

---

## 里程碑 & 优先级

| 里程碑 | 核心交付 | 价值 |
|---|---|---|
| **v0.2** | Phase 1 完成 | 稳定可靠的数据基础 |
| **v0.3** | Phase 2 完成 | 新闻+数据丰富度提升，LLM 上下文更完整 |
| **v0.4** | Phase 3 完成 | LLM 从工具升级为顾问 |
| **v0.5** | Phase 4 完成 | 量化因子挖掘能力，进阶用户核心价值 |
| **v0.6** | Phase 5 完成 | 策略验证闭环，用户可以"纸上谈兵" |
| **v1.0** | Phase 6+7 完成 | 商品级产品，可公开发布 |

---

## 已完成 ✅

- [x] 基础搜索 & K线展示（yfinance + TradingView Lightweight Charts）
- [x] SQLite 本地数据持久化 + WAL 模式
- [x] 16 项技术指标自动计算（MACD, BB, Ichimoku, TD, RSI, Stoch, ADX, VWAP, ATR, OBV, CCI, %R, SAR, MFI, Fib, CNN F&G）
- [x] 指标信号聚合 & 买卖建议
- [x] 指标叠加绘制（价格叠加 + 子图同步）
- [x] 日/夜主题切换（跟随系统）
- [x] CNN 恐慌指数实时获取（30分钟缓存）
- [x] OpenAI 兼容 LLM 集成（结构化预测输出 + 新闻 + 财报上下文）
- [x] LLM 配置界面（Base URL / Key / Model / Temperature）
- [x] NaN 数据容错处理
- [x] 可配置历史周期（1y/2y/5y/max）+ 增量更新
- [x] 数据获取日志（data_fetch_log 表 + /fetch-history API）
- [x] .env 配置管理（pydantic-settings）
- [x] URL 路由（History API + /stock/AAPL 直接访问）
- [x] 统一错误处理（AppError + JSON 格式）
- [x] 结构化日志系统
- [x] 企业新闻获取（yfinance news + 1hr 缓存 + 前端面板）
- [x] 财报数据（季度 Revenue/Net Income/EBITDA + EPS + 前端表格）
- [x] 机构持仓 & 分红历史 API
- [x] 骨架屏加载状态
- [x] 全局错误边界（toast 通知 + unhandledrejection 捕获）
- [x] LLM 请求队列（防止并发打爆 API）
- [x] SSE 流式 LLM 输出（实时进度推送）
- [x] 多轮对话（聊天历史持久化 + 上下文感知）
- [x] 多模型预设（GPT-4o/Claude/DeepSeek/Qwen/Ollama 一键切换）
- [x] 策略解释器（LLM 用通俗语言解释指标）
- [x] 预测历史记录（保存每次 LLM 预测结果）
- [x] 投资百科问答（通用投资问题 Q&A）
- [x] 多空对比分析（Bull/Bear case 自动生成）
- [x] 结构化分析报告（Markdown 格式）
- [x] 因子表达式引擎（20+ 内置函数，支持 and/or 组合）
- [x] 内置因子库（15 个常用因子模板）
- [x] 因子值时间序列可视化
- [x] 回测引擎（事件驱动，止损/止盈/手续费/滑点）
- [x] 回测结果展示（收益曲线、Sharpe、最大回撤、胜率、交易明细）
- [x] 纸盘交易系统（虚拟账户、买卖下单、持仓跟踪、盈亏计算）
- [x] 交易日志（每笔交易记录时间、价格、数量、理由）
- [x] Dashboard 首页（账户概览、最近股票、预测历史、交易记录）
- [x] 纸盘交易绩效统计（交易量、费用、最常交易、交易频率）
- [x] Docker 容器化（Dockerfile + docker-compose）
- [x] .env 配置模板（.env.example）
- [x] Makefile 常用命令
- [x] API 文档（Swagger + ReDoc 自动）
- [x] 键盘快捷键（/搜索, t主题, s设置, d首页, p预测, Esc关闭）
- [x] 单元测试（34 tests — indicators, factor engine, backtest）
- [x] GitHub Actions CI（push 自动 test）
- [x] 请求限流（slowapi — 60/min default, 5/min LLM）
- [x] 开发者文档（CONTRIBUTING.md）
- [x] API 端到端测试（23 tests — search, stock, news, financials, factors, backtest, paper trading, dashboard）
- [x] 全屏图表模式（f 键切换）
- [x] 深链分享（🔗 Share 按钮复制 URL）
- [x] 中英文切换（🌐 按钮，自动检测浏览器语言）
- [x] 多策略对比（5 种策略一键比较，按 Sharpe 排名）
- [x] 参数敏感性分析（网格搜索最优 RSI period/threshold）
- [x] 因子相关性矩阵（10 个因子热力图）
- [x] 响应式移动端布局（768px 断点，iOS zoom 修复）
- [x] 新闻情绪标签（LLM 分析 Bullish/Bearish/Neutral）
- [x] 期权链数据（calls/puts）
- [x] 行业/板块 ETF 基准对比
- [x] 限价单/止损单/止盈单（纸盘交易）
- [x] Watchlist 自选股（添加/删除/实时价格/涨跌幅/持久化）
- [x] 5 年历史数据（默认 5y，增量更新 + 自动回填）
- [x] 风险评估（年化波动率、最大回撤、VaR、夏普比率、风险等级）
- [x] 自定义因子注册（保存/删除/内置+自定义统一展示）
- [x] 因子分布分析（直方图 + 均值/标准差/百分位数）
- [x] Prompt 版本管理（保存/切换/回退）
- [x] 因子分组回测（Quintile 分析 + 单调性检验）
- [x] 新闻影响分析（LLM 输出 news_impact 字段）
- [x] IC 值分析（Rank IC 时序 + 最优滞后期）
- [x] 因子衰减分析（IC 随持有期变化 + 半衰期）
- [x] 多因子加权组合（Z-score + 权重 + Quintile 分析）
- [x] Monte Carlo 模拟（交易顺序随机打乱 + 盈利概率 + 置信区间）
- [x] 内存 LRU 缓存（50 stocks, 5min TTL + /api/cache/stats）
- [x] 数据完整性校验（缺失交易日检测 + 完整度百分比）
- [x] Walk-forward 滚动窗口回测（train/test split + consistency）
- [x] 新闻关键词提取（LLM 提取 1-3 个关键词）
- [x] 定投建议（DCA advice — INCREASE/MAINTAIN/DECREASE/PAUSE）
- [x] 图表标注（LLM 识别 3 support + 3 resistance levels）
- [x] 数据备份（手动备份 + 列表 + 恢复 + 启动自动备份，保留最近 10 份）
- [x] 再平衡建议（等权/自定义权重，>2% 偏差触发建议）
- [x] 学习路径推荐（LLM 生成，按水平+兴趣定制）
- [x] 性能监控（/api/perf — 每个端点的调用次数/avg/max 响应时间）
- [x] 因子正交化（Gram-Schmidt 去除共线性）
- [x] 货币格式化（Intl.NumberFormat 按市场自动适配）
- [x] 时区处理（Intl.DateTimeFormat 转本地时间）
- [x] API Key 安全加固（GET 响应中完全移除 api_key）
- [x] 置信度校准（历史预测准确率 → overconfident/underconfident 检测）
- [x] 因子中性化（去均值 + 去趋势 + 滚动 Z-score）
- [x] 样本外验证（train/test split + robustness STRONG/MODERATE/WEAK）
- [x] 税务报告（FIFO 匹配 + short/long term 分类）
- [x] Railway + Fly.io 部署配置（railway.toml + fly.toml）
- [x] 用户指南（USER_GUIDE.md）
- [x] 指标白皮书（INDICATORS.md — 16 个指标公式+信号逻辑）
- [x] 因子实验室页（表达式编辑+库+保存+回测+对比+敏感性+分布+Quintile+IC+衰减+多因子+正交化+中性化+相关性，SPA 内嵌）
- [x] 回测 & 交易页（策略配置+净值曲线+对比+MC+WF+OOS+模拟交易+限价单，SPA 内嵌）
- [x] 设置页（LLM 配置+模型预设+主题+语言，模态框）

---

## Next Steps — Future Development

> 以下为已完成核心功能后的进阶方向，按优先级排列。

### 🔥 High Priority
- [ ] **框架迁移**：vanilla JS → SvelteKit / Next.js，组件化重构
- [x] **WebSocket 实时推送**：市场开盘时推送价格变动（30s 轮询广播）
- [x] **通知系统**：Toast 通知（错误/警告/信息）+ LLM 预测完成通知

### 🧪 Research
- [ ] **可视化因子构建器**：拖拽式节点编辑器（React Flow / Svelte Flow）
- [ ] **回测验证**：与 TradingView / backtrader 对比验证指标正确性

### 🎨 Polish
- [ ] **组件库**：Shadcn / Radix UI 定制主题
- [x] **设计系统**：统一色彩/字体/间距/动效规范（CSS 变量）
- [x] **图标系统**：Lucide Icons

### 🧪 Testing
- [ ] **E2E 测试**：完整用户流程自动化测试
