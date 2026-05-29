# PUNK PLANET 自动更新方案（网易云音乐）

## 1. 目标

为纯静态前端网站增加“自动更新新歌”的能力。

核心思路：
- 前端仍然只读取本地 `data/punk_data.js`；
- 使用 Python 脚本在站外定期调用网易云音乐 API；
- 将各国动态发现的新歌合并回 `data/punk_data.js`；
- 用 `data/punk_update_state.json` 记录歌曲首次出现时间，从而识别“站内新歌”。

---

## 2. 为什么这样设计

这个站点当前是纯静态页面（HTML + JS），浏览器里直接调网易云音乐 API 会有几个问题：

1. **API Base 暴露风险**：前端直连会把服务地址暴露给访问者；
2. **请求频率不可控**：用户一多，容易触发限流；
3. **启动性能差**：每次打开页面都实时请求，会拖慢加载；
4. **数据不稳定**：接口偶发失败时，页面会直接空掉。

所以更稳的做法是：

> 用离线脚本定时拉取 → 生成静态数据文件 → 前端继续像原来一样读本地文件。

这样既保留了静态网站部署简单的优点，也拥有“自动更新”的效果。

---

## 3. 网易云音乐 API 组合方案

### 3.1 可直接用到的接口

- `top/song`
  - 用途：获取新歌速递；
  - 作用：按地区类型拉取新歌。

### 3.2 推荐判定逻辑

脚本里按国家映射到区域类型，然后拉取该区域的新歌池：

1. CN -> ZH
2. JP -> JP
3. KR -> KR
4. 其他国家默认走 EA/ALL

区域映射只是为了适配现有的“按国家展示”结构。

---

## 4. “新歌”怎么定义

网易云的 `top/song` 更接近“新歌速递”，适合追踪最近新增的歌曲。

这套方案里，“新歌”采用的是：

> **对网站来说第一次被抓到的歌 = 站内新歌**

也就是：
- 脚本第一次看到某首歌进入目标区域的新歌池时；
- 会把它记入 `punk_update_state.json`；
- 后续再次出现时，不再标记为“新上榜”。

这很适合静态站，因为它强调“最近新发现了什么”，而不是强依赖官方发行日期。

如果以后你想升级成“真正的新发行追踪”，也可以再接：
- Spotify / Apple Music / MusicBrainz / Discogs 等更偏发行元数据的接口。

---

## 5. 已新增文件

- `scripts/update_punk_data.py`
  - 自动更新脚本；
- `data/punk_update_state.json`
  - 状态文件，用于记录首次出现时间；
- `README_AUTO_UPDATE.md`
  - 本说明文档。

---

## 6. 运行方式

### 6.1 本地手动执行

在项目目录下运行：

```bash
cd pop_punk_globe
export NCM_API_BASE="http://localhost:3000"
python3 scripts/update_punk_data.py
```

执行完成后会：
- 更新 `data/punk_data.js`
- 更新 `data/punk_update_state.json`

### 6.2 指定国家

```bash
python3 scripts/update_punk_data.py --countries US,GB,JP,CN
```

### 6.3 调整每国保留歌曲数

```bash
python3 scripts/update_punk_data.py --per-country-limit 6
```

### 6.4 直接传 API Base

```bash
python3 scripts/update_punk_data.py --api-base "http://localhost:3000"
```

> 更推荐环境变量方式，避免把地址写进脚本或命令历史。

---

## 7. 定时更新建议

### macOS / Linux（crontab）

每天早上 9 点更新一次：

```bash
0 9 * * * cd /path/to/pop_punk_globe && NCM_API_BASE=http://localhost:3000 /usr/bin/python3 scripts/update_punk_data.py >> update.log 2>&1
```

### GitHub Actions（更推荐）

如果网站托管在 GitHub Pages / 静态对象存储，建议用定时任务：

1. 把 `NCM_API_BASE` 配到 Secrets；
2. 每天定时运行脚本；
3. 自动提交更新后的 `data/punk_data.js` 和 `data/punk_update_state.json`。

这样网站本身仍是纯静态，但内容会自动刷新。

---

## 8. 前端展示方式

脚本不会破坏原有“经典乐队 + 手工策展歌曲”结构。

它会在每个国家的 `bands` 数组最前面插入一张动态卡片：

- 卡片名：`🔥 网易云新歌雷达`
- 标签：显示最近更新时间
- 歌曲列表：显示该国家最近抓到的新歌

这样用户点开国家后，会先看到最新动态，再看到你原来策展好的经典内容。

---

## 9. 架构反馈 / 后续可升级点

### 当前方案的优点

- 不改站点部署方式；
- API Base 不进入前端；
- 页面加载速度稳定；
- 就算网易云 API 临时挂了，前端仍有上一次成功生成的数据可展示。

### 当前方案的限制

- “新歌”更偏“新进入你站点视野的歌”，不等于官方发行日期；
- 不同区域的新歌池可能大小不一；
- 如果网易云返回不稳定，需要重试或回退策略。

### 我建议的后续增强

1. **增加缓存层**
   - 给新歌接口增加本地缓存，减少重复请求。

2. **增加失败回退机制**
   - 某国家本次抓不到数据时，保留旧动态卡片，不要清空。

3. **把“新上榜”做成视觉徽标**
   - 目前数据里已经保留了 `isNew` 字段，前端可以继续加角标样式。

4. **拆分静态 / 动态数据源**
   - 现在是直接回写 `punk_data.js`；
   - 如果后面想更清晰，也可以拆成：
     - `punk_static_data.js`
     - `punk_dynamic_data.js`
     - 页面启动时合并。

---

## 10. 一句话总结

这是一个很适合纯静态站点的做法：

> **用 Python 在离线环境里“进货”，把网易云的新歌提前烤进静态数据文件里，前端继续无脑读取。**

稳、快、好维护。朋克，但不鲁莽 🤘
