# StockOverflow Roadmap v2

> 一站式智能股票分析平台 — 让数据驱动决策

---

## 已完成 ✅

### 核心功能
- [x] 股票搜索 + 5 年历史日线数据 + 增量更新
- [x] 16 项技术指标自动计算（MACD, BB, Ichimoku, TD, RSI, Stoch, ADX, VWAP, ATR, OBV, CCI, %R, SAR, MFI, Fib, CNN F&G）
- [x] 指标叠加绘制（价格叠加 + 子图同步）
- [x] 因子表达式引擎（20+ 内置函数，支持 and/or 组合）
- [x] 回测引擎（事件驱动，止损/止盈/手续费/滑点）
- [x] 纸盘交易系统（限价单/止损单/止盈单）
- [x] 多策略对比 + 参数敏感性 + Monte Carlo + Walk-Forward
- [x] CNN 恐慌指数 + 多源新闻（yfinance + Finviz）+ 新闻情绪
- [x] 财报数据 + 机构持仓 + 期权链 + 分红历史
- [x] Watchlist 自选股 + Dashboard 首页
- [x] 股票对比功能
- [x] 数据备份（手动 + 启动自动）

### LLM 集成
- [x] OpenAI 兼容 API（6 个模型预设）
- [x] 多轮对话 + 对话历史持久化
- [x] SSE 流式输出
- [x] 结构化预测（BUY/SELL/HOLD + 价格 + 止损 + 置信度）
- [x] 多空对比 + 定投建议 + 策略解释 + 学习路径
- [x] 图表标注（支撑/阻力位）

### 基础设施
- [x] SQLite WAL 模式 + LRU 缓存 + 请求队列
- [x] 统一错误处理 + 结构化日志
- [x] .env 配置 + Docker + Railway/Fly.io 部署
- [x] 66 个测试通过
- [x] WebSocket 实时价格流
- [x] 多时间周期（1D/日/周/月/季/年）

---

## 🔥 当前重点 — 待解决的核心问题

### 1. 图表稳定性
- [x] **修复 lightweight-charts 渲染错误**：添加渲染锁防止并发、安全销毁图表
- [x] **统一时间格式处理**：所有数据使用 Unix 时间戳，兼容日线和分时
- [x] **图表生命周期管理**：切换股票/时间周期时正确销毁旧图表实例
- [ ] **跨浏览器兼容性测试**：Safari/Firefox/Chrome 渲染一致性

### 2. GUI 重新设计
- [x] **设计语言升级**：渐变标题、毛玻璃导航栏、卡片悬浮阴影、过渡动画
  - 统一的卡片圆角、阴影、间距系统
  - 更精致的配色方案（不只是黑/白两色）
  - 动效：页面切换、数据加载、图表缩放的过渡动画
- [x] **导航重构**：顶部 Tab 导航（Dashboard / 因子实验室 / 回测）+ 活跃状态高亮
- [x] **侧边栏**：自选股快速切换 + 最近搜索（slide-out panel with ☰ toggle）
- [x] **响应式优化**：移动端布局优化（触摸目标、垂直堆叠、iOS zoom 修复）
- [x] **骨架屏优化**：每个区域独立加载（showSectionLoading/hideSectionLoading helpers）

### 3. i18n 国际化
- [x] **完整中文翻译**：覆盖所有 UI 文本（58 个翻译键，中英文完整覆盖）
- [x] **翻译文件外置**：JSON 文件管理（frontend/locales/en.json + zh.json，58 个翻译键）
- [x] **数字格式本地化**：中文环境显示 `万`/`亿` 而非 `K`/`M`/`B`
- [x] **日期格式本地化**：`zh-CN` / `en-US` locale 自动切换
- [x] **货币符号适配**：`$` / `¥` / `€` 根据市场自动切换（fmtCurrency + Intl.NumberFormat）

---

## 🧠 LLM 智能化升级

### 4. 预测时机优化
- [x] **盘后预测（16:00+）**：针对下一交易日
  - 使用当日完整日线 + 分时数据
  - 分析当日新闻 + 财报影响
  - 输出：明日限价单价格 + 止损 + 止盈
- [x] **盘中预测（9:30-16:00）**：针对当日交易
  - 使用实时分时数据（WebSocket 推送）
  - 分析盘中异动 + 资金流向
  - 输出：当日日内交易建议 + 目标价
- [x] **盘前预测（4:00-9:30）**：针对开盘策略
  - 使用盘前交易数据 + 隔夜新闻
  - 分析期货指数 + 全球市场
  - 输出：开盘策略 + 关键价位

### 5. LLM 深度应用
- [x] **智能复盘**：每日收盘后自动生成持仓股票的复盘报告（/api/llm/portfolio-review）
- [x] **异常检测**：LLM 分析异动原因（为什么暴涨/暴跌？）
- [x] **组合优化**：根据风险偏好给出仓位建议（/api/llm/optimize）
- [x] **新闻深度解读**：不只是情绪分析，而是"这条新闻对我的持仓意味着什么"
- [x] **财报解读**：自动分析财报数据，给出投资建议（/api/llm/financial-analysis）
- [x] **多空博弈分析**：同时给出看多和看空的完整论据（bull_bear_debate API）
- [x] **LLM 交易日志**：记录每次预测的依据（llm_history 表 + /api/llm/history/{ticker}）

---

## 🧪 因子实验室重构

### 6. 因子实验室 — 易用性
- [x] **向导模式**：引导式因子构建（选择类型 → 选择指标 → 生成表达式 → 一键测试）
- [x] **因子模板库**：7 大分类、31 个内置因子（动量/均值回归/趋势/波动/成交量/突破/复合）
- [x] **一键测试**：点击模板直接在当前股票上运行（factor lib + strategy templates）
- [x] **因子参数优化**：自动搜索最优参数组合（sensitivity analysis API）
- [x] **因子可视化增强**：信号标记点（"Mark on Chart" 按钮，将信号标在 K 线上）
  - 因子值与价格的双轴对比图
  - 信号标记点（买入/卖出信号在 K 线上的标注）
  - 因子分布直方图 + 正态拟合
- [x] **因子回测集成**：⚡ Quick Backtest 按钮，因子评估直接运行回测

### 7. 因子实验室 — 进阶功能
- [x] **多因子组合构建器**：点击选择因子 + 自定义权重 + Quintile 分析
- [x] **因子有效性检验**：IC 分析 + 分组回测 + 衰减分析
- [x] **因子正交化**：去除因子间共线性（Gram-Schmidt）
- [x] **因子中性化**：去除行业/市值暴露（de-mean + de-trend + Z-score）
- [x] **自定义因子注册**：保存、分享、导出因子表达式

---

## 📊 回测系统增强

### 8. 回测 — 用户体验
- [x] **策略模板库**：8 个预置策略（RSI/MACD/BB/Stoch+RSI/ADX+MACD/Volume/MFI）
- [x] **回测参数可视化**：初始资金 + 止损百分比参数面板
- [x] **回测报告导出**：CSV 格式
- [x] **多股票回测**：在一组股票上批量测试策略（strategy comparison API）
- [x] **基准对比**：与 SPY/QQQ 的收益对比曲线（sector ETF comparison）

### 9. 回测 — 高级功能
- [x] **Walk-Forward 优化**：滚动窗口参数优化
- [x] **Monte Carlo 置信区间**：收益分布可视化
- [x] **风险指标增强**：Sharpe、Max Drawdown、Win Rate、Profit Factor
- [x] **交易成本建模**：滑点模型 + 手续费阶梯（BacktestConfig）

---

## 🔮 未来方向

### 10. 数据增强
- [x] **多数据源容灾**：yfinance 失败时降级到 Alpha Vantage（需配置 API key）
- [x] **SEC 文件解析**：SEC 日历事件（财报日期、分红日期）
- [x] **分析师评级**：目标价 + 评级 + 分析师数量（/api/stock/{ticker}/analyst）
- [x] **内部交易**：高管买卖记录（insider transactions API）
- [x] **期权链分析**：calls/puts 数据（/api/stock/{ticker}/options）

### 11. 框架迁移（长期）
- [ ] **SvelteKit 迁移**：组件化重构，提升开发效率
- [ ] **TypeScript**：类型安全
- [ ] **组件库**：Shadcn-svelte
- [ ] **状态管理**：Svelte stores
- [ ] **E2E 测试**：Playwright

### 12. 生产化
- [x] **用户认证**：API Key 认证（生成/验证/管理 + /api/auth/* 端点）
- [ ] **云端部署**：数据库迁移到 PostgreSQL
- [x] **性能优化**：defer 脚本加载、preconnect CDN、API 性能监控面板
- [x] **监控告警**：API 响应时间追踪（/api/perf endpoint）

---

## 实施优先级

```
P0 (立即)  → 图表稳定性 + i18n 完善
P1 (近期)  → GUI 重新设计 + LLM 预测时机优化
P2 (中期)  → 因子实验室重构 + 回测增强
P3 (长期)  → 框架迁移 + 生产化
```

---

## 文件结构

```
backend/          22 Python 模块
frontend/         1 SPA (index.html)
tests/            5 测试文件, 66 tests
docs/archive/     旧版路线图归档
```
