# StockOverflow Phase 2 Roadmap

> 数据智能化 + 前端现代化 + 交易指导

---

## 1. 智能数据获取引擎

### 1.1 主动获取（Always-On）

持续自动刷新的数据源：

| 数据源 | 频率 | 说明 |
|---|---|---|
| **主要指数** | 每 5 分钟 | SPY, QQQ, DIA, IWM, VIX（开盘时间） |
| **Watchlist 股票** | 每 5 分钟 | 用户自选股实时价格 |
| **每日飙升榜** | 每日收盘后 | 涨幅 Top 20 |
| **每日骤降榜** | 每日收盘后 | 跌幅 Top 20 |
| **热度排行** | 每小时 | 搜索量/交易量 Top 20 |

### 1.2 被动获取（On-Demand + TTL）

- [x] **最近搜索股票**：用户搜索后加入活跃列表，TTL 24 小时
- [x] **排行榜股票**：上榜期间保持活跃，下榜后 TTL 7 天（自动从 movers API 记录）
- [x] **LLM 预测股票**：预测后 TTL 3 天（自动记录 prediction 来源）
- [x] **纸盘交易持仓**：持有期间持续刷新（自动记录 trade 来源，TTL 8760h）

### 1.3 生命周期管理

```
搜索/上榜 → 加入 active_set (TTL=24h)
再次交互 → 续期 TTL
TTL 到期 → 移入 passive_set (仅按需获取)
再次交互 → 回到 active_set
30天无交互 → 完全移除
```

- [x] `active_stocks` 表：ticker, source, ttl, last_fetch, last_interaction
- [x] 后台任务：定期清理过期条目（启动时自动清理 + /api/market/cleanup）
- [x] 前端：显示哪些股票正在自动刷新（dashboard active_stocks 分组展示）

### 1.4 数据获取 API

```
GET /api/market/indices          # 主要指数实时数据 ✅
GET /api/market/movers?type=gainers   # 飙升榜 ✅
GET /api/market/movers?type=losers    # 骤降榜 ✅
GET /api/market/movers?type=hot       # 热度榜 ✅
GET /api/market/active-stocks         # 当前活跃股票列表 ✅
POST /api/market/interact             # 记录用户交互（搜索/查看）✅
GET /api/watchlist/predictions        # Watchlist 明日预测 ✅
```

---

## 2. 动态数据补全

### 2.1 缩放感知数据加载

当前问题：固定获取 5 年数据，缩放到近期时精度不足。

解决方案：

```
缩放范围          | 数据粒度    | 加载策略
> 2 years         | 日线        | 加载完整日线
3 months - 2 years| 日线        | 当前已有
< 3 months        | 日线 + 关键 | 补充盘前盘后
< 1 week (未来)   | 分钟线      | 按需加载 5 分钟线
```

- [x] 前端：检测 timeScale 可见范围变化
- [x] 前端：当缩放到 < 3 个月时，请求更高精度数据
- [x] 后端：`GET /api/stock/{ticker}/intraday?period=5d&interval=5m`
- [x] 后端：缓存分钟线数据（TTL 5 分钟）

### 2.2 增量数据流

- [x] WebSocket 推送：30 秒轮询最新价格并广播
- [x] 前端：实时更新价格显示 + 自动重连
- [x] 后端：`WS /ws/stock/{ticker}` 实时价格流

---

## 3. 因子实验室 & 回测 — 前端完善

### 3.1 因子实验室页（独立页面）

当前：内嵌在个股详情的 Factor Lab 区域。
目标：独立的全屏因子实验室。

- [x] **左侧栏**：内置因子库 + 自定义因子列表（已内嵌在个股详情页）
- [x] **中央编辑器**：表达式输入 + 15 个内置因子快捷按钮
- [x] **右侧面板**：
  - 因子值时间序列图 ✅
  - 分布直方图 ✅
  - Quintile 分析条形图 ✅
  - IC 衰减曲线 ✅
  - 相关性热力图 ✅
- [x] **底部**：回测结果（净值曲线 + 交易明细 + 绩效指标 + CSV 导出）
- [x] **保存/加载**：因子方案持久化（custom_factors 表 + /api/factors/custom）

### 3.2 回测页（独立页面）

当前：内嵌在个股详情的 Backtest 区域。
目标：独立的策略回测工作台。

- [x] **策略配置面板**：
  - 买入表达式 + 卖出表达式 ✅
  - 初始资金、手续费、滑点 ✅
  - 止损/止盈百分比 ✅
- [x] **一键回测**：运行 + 显示结果（净值曲线 + 指标 + 交易明细 + CSV 导出）
- [x] **策略对比**：多个策略并排比较（5 种预设策略一键对比）
- [x] **参数敏感性**：网格搜索最优参数区间
- [x] **Monte Carlo**：盈利概率 + 置信区间
- [x] **Walk-Forward**：分段结果展示 + consistency 指标
- [x] **导出**：下载回测报告（CSV）

### 3.3 前端路由

```
/                      → Dashboard ✅
/stock/:ticker         → 个股详情 ✅
#factors               → 因子实验室 ✅
#backtest              → 回测工作台 ✅
#trading               → 模拟交易 (TODO)
#settings              → 设置 (TODO)
```

---

## 4. SvelteKit 迁移

### 4.1 技术栈

```
SvelteKit + TypeScript
Tailwind CSS (替代手写 CSS)
TradingView Lightweight Charts (保留)
Skeleton UI 或 Shadcn-svelte
```

### 4.2 迁移策略

- [ ] **Phase A**：Scaffold SvelteKit 项目，配置 Tailwind
- [ ] **Phase B**：迁移核心组件
  - SearchBar
  - StockChart (TradingView wrapper)
  - IndicatorPanel
  - NewsPanel
  - FactorLab
  - BacktestPanel
- [ ] **Phase C**：迁移页面路由
- [ ] **Phase D**：迁移设置/主题/i18n
- [ ] **Phase E**：测试 + 部署

### 4.3 组件结构

```
src/
├── lib/
│   ├── components/
│   │   ├── SearchBar.svelte
│   │   ├── StockChart.svelte
│   │   ├── IndicatorCard.svelte
│   │   ├── NewsCard.svelte
│   │   ├── FactorEditor.svelte
│   │   ├── BacktestPanel.svelte
│   │   ├── LLMCard.svelte
│   │   ├── ThemeToggle.svelte
│   │   └── LanguageToggle.svelte
│   ├── stores/
│   │   ├── theme.ts
│   │   ├── language.ts
│   │   ├── stock.ts
│   │   └── indicators.ts
│   └── api/
│       ├── stock.ts
│       ├── factors.ts
│       ├── backtest.ts
│       └── llm.ts
├── routes/
│   ├── +layout.svelte
│   ├── +page.svelte          (Dashboard)
│   ├── stock/[ticker]/
│   │   └── +page.svelte      (个股详情)
│   ├── factors/
│   │   └── +page.svelte      (因子实验室)
│   ├── backtest/
│   │   └── +page.svelte      (回测工作台)
│   ├── trading/
│   │   └── +page.svelte      (模拟交易)
│   └── settings/
│       └── +page.svelte      (设置)
└── static/
```

---

## 5. i18n 修复

### 5.1 当前问题

- 切换中文无效（只有部分 UI 文本有翻译）
- 搜索框 placeholder 等未更新

### 5.2 解决方案

- [x] 使用 `svelte-i18n` 或自定义 i18n store（自定义 i18n store + data-i18n 属性）
- [x] 提取所有 UI 文本到翻译文件（I18N 对象，50+ 翻译键）
- [x] 支持语言：English, 简简体中文
- [x] 自动检测浏览器语言（navigator.language）
- [x] 持久化到 localStorage

### 5.3 翻译覆盖范围

```
search_placeholder    搜索股票代码或公司名称...
predict_btn          🔮 预测
share_btn            🔗 分享
watchlist_btn        ☆ 自选
overall_signal       综合信号
support              支撑位
resistance           阻力位
buy                  买入
sell                 卖出
hold                 持有
loading              加载中...
no_data              暂无数据
```

---

## 6. 待机面板（Standby Dashboard）

### 6.1 功能

当用户打开页面但未搜索任何股票时，显示：

- [x] **Watchlist 交易指导**：
  - 每只自选股的明日预测（BUY/SELL/HOLD）
  - 建议限价单价格
  - 止损/止盈价格
  - 置信度
- [x] **限价单精度修复**：
  - 当前问题：大额数字显示为 `1.8k`，精度不够
  - 修复：价格永远显示完整数字（如 `$1,823.50`）
  - 只有市值/成交量等大数值才用缩写
- [x] **市场概览**：
  - 主要指数涨跌
  - CNN Fear & Greed 指数
  - 今日飙升/骤降 Top 5

### 6.2 限价单精度修复

```javascript
// 修复前
fmtNum(1823.50)  → "1.8K"  // ❌ 精度丢失

// 修复后
fmtPrice(1823.50) → "$1,823.50"  // ✅ 价格精确
fmtCap(1823500000) → "$1.82B"    // ✅ 市值用缩写
```

- [x] 新增 `fmtPrice()` 函数：价格永远精确到小数点后 2 位
- [x] 价格显示使用 `Intl.NumberFormat` 格式化
- [x] 限价单、止损、止盈价格使用 `fmtPrice()`
- [x] 市值、成交量等大数值继续使用 `fmtNum()` 缩写

### 6.3 待机面板布局

```
┌─────────────────────────────────────────────────┐
│  📊 Market Overview                              │
│  SPY ▲+0.5%  QQQ ▲+0.8%  VIX 18.5  F&G: 27    │
├─────────────────────────────────────────────────┤
│  ⭐ Watchlist — Tomorrow's Guide                │
│  ┌──────┬────────┬────────┬────────┬──────────┐ │
│  │Ticker│ Signal │ Limit  │ Stop   │Confidence│ │
│  ├──────┼────────┼────────┼────────┼──────────┤ │
│  │ AAPL │ BUY    │$293.50 │$285.00 │ 72%      │ │
│  │ MSFT │ HOLD   │   —    │   —    │ 45%      │ │
│  │ TSLA │ SELL   │$390.00 │$405.00 │ 68%      │ │
│  └──────┴────────┴────────┴────────┴──────────┘ │
├─────────────────────────────────────────────────┤
│  🔥 Today's Movers                              │
│  ▲ NVDA +8.2%  ▲ AMD +5.1%  ▼ INTC -3.4%     │
└─────────────────────────────────────────────────┘
```

---

## 实施顺序

| 优先级 | 任务 | 预估工时 |
|---|---|---|
| ✅ | 限价单精度修复（`fmtPrice`） | 1h |
| ✅ | 待机面板 — Market Overview + Watchlist 交易指导 | 1d |
| ✅ | 智能数据获取引擎（主动/被动/TTL + active_stocks） | 2d |
| 🟠 P1 | 动态数据补全（缩放感知） | 1d |
| ✅ | i18n 修复（data-i18n 属性 + 完整中英文翻译） | 0.5d |
| ✅ | 因子实验室独立页面（#factors 路由） | 0.5d |
| ✅ | 回测工作台独立页面（#backtest 路由） | 0.5d |
| 🟢 P3 | SvelteKit 迁移 | 5-7d |
| 🟢 P3 | WebSocket 实时推送 | 2d |

**总计预估：~16 天**

---

## 依赖关系

```
限价单精度修复 ──→ 待机面板
                    ↓
智能数据获取 ──→ 动态补全 ──→ WebSocket
                    ↓
              因子实验室页面
              回测工作台页面
                    ↓
              SvelteKit 迁移 ──→ i18n 修复
```
