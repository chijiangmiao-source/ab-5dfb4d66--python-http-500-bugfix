# 口译交接时间轴对齐工具（Interpreter Handoff Aligner）

一场多语发布会结束后，两名口译员各自记录了交接附近听到的事件。漏记、补记与
时间偏移使组长无法直接对照双方笔记。本工具接收两组 JSON 笔记，使用**动态规划**
求出**全局最优且唯一**的对齐时间轴，并在页面上逐行展示配对、两类空缺、单步
代价、累计代价与总代价，支持逐步复算。

复盘时，组长可以把少量已确认的左右配对标记为**配对锚点**：重新计算时锚点行
保持固定（不被局部时间漂移推翻），系统只对锚点区间内的其余记录自动对齐；
时间轴上以 ★ 人工确认 / 算法生成 明确区分每一行的来源。

- 后端：Python 3.12 · FastAPI · 纯标准库实现的 DP（无任何外部匹配库）
- 前端：TypeScript · React 18 · Vite
- 测试：pytest（算法/校验/API）· Vitest（前端逻辑与组件）· Playwright（真实前后端联调）
- 部署：Docker Compose（web + api + 一次性 `verify` 验收服务）

---

## 1. 输入格式与示例

页面左右两个文本框各接收一个 **JSON 数组**；请求体形如
`{"left": [...], "right": [...], "anchors": [...]?}`（`anchors` 可选，见
第 3 节）。每项**仅含**两个字段：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `time` | 整数 | 毫秒时间戳；组内**严格递增、不可重复** |
| `text` | 非空字符串 | 听到的内容 |

单组最多 **200** 项。结构错误、超限、重复/非递增时间、多余字段都只会产生
**一次**明确失败，响应（与页面高亮）指向首个错误路径，如 `left[2].time`，
且原始输入原样保留。

> **超大毫秒整数**：`time` 按任意精度整数处理。前端手写的 JSON 解析器把
> 整数数字字面量保留为 `BigInt`，并将两个文本框里的数组**原始文本**直接
> 发给后端（不经过 `JSON.parse`/`JSON.stringify` 重序列化），后端 Python
> 原生支持任意精度整数。因此即使相邻时间超过 `Number.MAX_SAFE_INTEGER`
> （2⁵³−1，例如 `9007199254740993` 与 `9007199254740995`），也不会因
> double 舍入而被误报为重复；真正相等的超大整数仍会被准确拦截。
>
> 该承诺对**任意位数**生效，不设位数上限：CPython 默认将整数的
> 十进制字符串转换限制在 4300 位（CVE-2020-10735 缓解措施），后端在
> 导入 `app` 包时通过 `sys.set_int_max_str_digits(0)` 关闭该进程级限制，
> 使请求解析（`json.loads`）、锚点代价计算（`|Δt|` 大整数运算）、错误
> 消息格式化与响应序列化（`json.dumps`）全链路都接受任意位数的整数。
> 例如 4301 位的 `time` 会正常得到 HTTP 200 对齐结果，且响应中的十进制
> 数字与输入逐位一致——全程不经过浮点。

### 输入示例

```json
{
  "left": [
    {"time": 0, "text": "各位媒体朋友下午好"},
    {"time": 4200, "text": "新产品将于下月上市"},
    {"time": 9000, "text": "感谢各位的提问"}
  ],
  "right": [
    {"time": 150, "text": "各位媒体朋友下午好"},
    {"time": 4100, "text": "新产品将于下月上市"},
    {"time": 12000, "text": "交接后的补充记录"}
  ]
}
```

### 输出示例（节选）

```json
{
  "steps": [
    {"action": "match", "left": {"time": 0, "text": "各位媒体朋友下午好"},
     "right": {"time": 150, "text": "各位媒体朋友下午好"}, "cost": 150, "cumulative_cost": 150},
    {"action": "match", "left": {"time": 4200, "text": "新产品将于下月上市"},
     "right": {"time": 4100, "text": "新产品将于下月上市"}, "cost": 100, "cumulative_cost": 250},
    {"action": "right_gap", "left": {"time": 9000, "text": "感谢各位的提问"},
     "right": null, "cost": 2000, "cumulative_cost": 2250},
    {"action": "left_gap", "left": null,
     "right": {"time": 12000, "text": "交接后的补充记录"}, "cost": 2000, "cumulative_cost": 4250}
  ],
  "total_cost": 4250,
  "counts": {"match": 2, "left_gap": 1, "right_gap": 1},
  "costs": {"gap": 2000, "mismatch_penalty": 3000}
}
```

三种动作（动作名表示**该行哪一侧留空**，非空的另一侧携带该条笔记）：

- `match`：左右各一项配对；
- `left_gap`：**左侧留空**，行内只有右侧记录（左侧漏记）；
- `right_gap`：**右侧留空**，行内只有左侧记录（右侧漏记）。

因此整组笔记只在一侧时，每一行都会正确地标出实际留空的另一侧：
只有 `left` 输入时动作为 `right_gap`，只有 `right` 输入时为 `left_gap`。

---

## 2. 代价规则与唯一性

对 `(m+1) × (n+1)` 的 DP 矩阵求最短路：

| 动作 | 单步代价 |
| --- | --- |
| 配对，`text` **相同** | `|timeL − timeR|` |
| 配对，`text` **不同** | `|timeL − timeR| + 3000` |
| 任一侧单项留空 | `2000` |

**平局裁决（保证时间轴唯一）**：总成本最小优先；成本相同时依次偏好

1. 配对（match）
2. 左侧留空（left gap）
3. 右侧留空（right gap）

动作仍无法区分时，取前驱坐标 `(i, j)` 字典序较小者。回溯得到的步骤按
笔记顺序排列，每一步带 `cumulative_cost`，页面的「上一步 / 下一步」按钮
可据此逐步复算到最终总代价。

---

## 3. 配对锚点（人工确认）

复盘时组长可能已确认少数左右笔记属于同一发言。页面在时间轴的每个配对行
提供「设为锚点 / 取消锚点」标记；再次点击「生成对齐」时，请求会**沿用原始
两组输入**并携带可选的 `anchors` 数组重新计算：

```json
{
  "left": [...],
  "right": [...],
  "anchors": [{"left": 0, "right": 0}, {"left": 2, "right": 1}]
}
```

每个锚点按**索引**引用左右记录。后端依次校验：索引存在（不越界）、同一侧
索引不可复用、两侧索引均严格递增（不可交叉）；随后以锚点为界把两组记录
切分成独立区间，对**每个区间运行同一套动态规划**，锚点行本身计入其原有
配对代价（`|Δt|` 或 `|Δt| + 3000`）。因此总代价恰好是「各区间最优解 +
锚点配对代价」之和，逐步复算仍得到同一总代价。

- 响应中每个步骤新增 `anchor` 布尔字段：`true` 为人工确认行，`false` 为
  算法生成行；页面以 ★ 人工确认 / 算法生成 标签区分。
- **未传 `anchors`（或传空数组）的旧请求，其响应与之前完全一致**——步骤中
  不出现 `anchor` 字段。
- 锚点越界、重复或交叉时返回**一次** 422 失败，`path` 指向首个确定的错误
  锚点（如 `anchors[1].left`）；页面保留当前输入与已选标记，在对应锚点旁
  显示该错误，且不展示可能被误认成有效的新时间轴。取消该锚点或修正输入
  后重新提交即可恢复。

---

## 4. 快速启动（Docker Compose，推荐）

需要 Docker（含 Compose v2）。

```bash
docker compose up --build
# 打开 http://localhost:8080
```

宿主端口可用环境变量覆盖（容器内部端口固定为 web 80、api 8000）：

```bash
WEB_PORT=9090 API_PORT=9000 docker compose up --build
# 页面 http://localhost:9090 ，API 文档 http://localhost:9000/docs
```

也可以复制 `.env.example` 为 `.env` 后修改 `WEB_PORT` / `API_PORT`，
Compose 会自动读取。

### 一次性验收服务 verify

`verify` 服务对**正在运行的容器栈**做真实联调验收（健康检查、web→api
同源代理、黄金样例、三类代价、平局顺序、单次失败契约、结果幂等唯一性，
以及锚点的固定入列、区间最优、越界/重复/交叉单次报错与旧请求兼容性），
并覆盖任意精度时间戳契约：4300 位边界值与 4301 位超阈值值的真实请求
均返回 200 且十进制数字逐位一致、超阈值时间戳的锚点代价计算与序列化
保持精确、非法超大输入只产生一个定位到字段的结构化 4xx——任何场景都
不得出现 HTTP 500 `Internal Server Error`。通过后退出码为 0，任一断言
失败则以非零退出：

```bash
docker compose up --build -d            # 先把 web/api 跑起来
docker compose run --rm verify          # 一次性验收，结束自动删除容器
docker compose down
```

---

## 5. 本地开发启动

### 后端（需要 Python 3.12；本地用 3.11 亦可运行测试）

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

### 前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 ，/api 自动代理到 127.0.0.1:8000
```

打开 http://localhost:5173 ，左右文本框已预填示例，点击「生成对齐」即可。

---

## 6. 测试

### pytest — 算法、校验与 API（77 个用例）

```bash
cd backend
python -m pytest
```

其中包含对所有小规模输入与朴素递归枚举的最优代价对拍、平局偏好
（配对 > 左留空 > 右留空）的专门用例，以及锚点切分后「区间最优 +
锚点自身代价」与朴素枚举的对拍。另有任意精度时间戳用例：4300 位
边界值、4301 位及 10000 位超阈值值经真实 ASGI 请求得到 200 且数字
逐位一致、超阈值锚点代价精确、非法超大输入只报一次结构化 4xx。

### Vitest — 前端逻辑与组件（54 个用例）

```bash
cd frontend
npm test
```

覆盖与后端一致的客户端校验、带源码位置的 JSON 解析器、API 客户端、
错误路径高亮、输入保留、逐步复算交互，以及锚点的标记/取消、请求体
携带与逐锚点错误展示；含 4301 位时间戳的 BigInt 解析、原样转发与
渲染往返用例（不经过 `Number`）。

### Playwright — 真实全栈联调（15 个用例）

先启动真实服务（生产构建 + FastAPI）：

```bash
cd backend && uvicorn app.main:app --port 8000 &
cd frontend && npm run build && npm run preview -- --port 4173 &
npx playwright test
```

用例在真实浏览器中验证：黄金时间轴的动作顺序与每步代价、逐步复算、
重复时间只报一次错且保留输入并高亮 `left[1].time`、超限（201 项）路径、
非法 JSON 的行列号定位、空数组零代价交接，以及锚点的标记固定、时间漂移
下锚点不被推翻、取消锚点恢复原时间轴、越界锚点的逐条报错与输入保留；
还包括 4301 位时间戳的前端 BigInt 往返——输入、提交与结果渲染全程
逐位一致，不被 JavaScript `Number` 截断或舍入。
也可设置 `E2E_AUTO_START=1 npx playwright test` 让 Playwright 自动拉起两端。

---

## 7. HTTP 接口

- `GET /health` → `200 {"status": "ok"}`
- `POST /api/align`

成功返回 `200` 与对齐结果；任何输入问题都返回**一个**错误对象：

```json
{"error": "left[1].time 为 1，未严格递增（上一项时间为 1）。", "path": "left[1].time"}
```

| 场景 | 状态码 | path 示例 |
| --- | --- | --- |
| 请求体不是合法 JSON | 400 | `""` |
| 根不是对象 / 缺少 left、right | 422 | `""` / `left` |
| 某侧不是数组 | 422 | `right` |
| 超过 200 项（指向越界首项） | 422 | `left[200]` |
| time 缺失/非整数/重复/非递增 | 422 | `left[2].time` |
| text 缺失/非字符串/为空 | 422 | `right[0].text` |
| 存在 time、text 之外的字段 | 422 | `left[0].who` |
| anchors 不是数组 / 锚点结构错误 | 422 | `anchors` / `anchors[0].right` |
| 锚点索引越界 | 422 | `anchors[0].left` |
| 锚点复用同一侧记录 | 422 | `anchors[1].left` |
| 锚点交叉（索引非严格递增） | 422 | `anchors[1].right` |

校验顺序固定为先 `left` 后 `right`、再 `anchors`，自上而下，因此任何
输入组合都只有**首个**错误被报告。

---

## 8. 目录结构

```
.
├── backend/
│   ├── app/
│   │   ├── alignment.py      # DP 对齐（代价矩阵 + 平局裁决 + 回溯）与锚点切分
│   │   ├── validation.py     # 结构/数量/类型/递增与锚点校验，返回首个错误路径
│   │   └── main.py           # FastAPI、手工 JSON 解析、单次失败契约
│   ├── tests/                # pytest：算法对拍、校验、真实 ASGI API
│   ├── Dockerfile            # python:3.12-slim
│   └── requirements*.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx           # 页面：输入、错误定位、逐步复算、锚点面板
│   │   ├── ResultTimeline.tsx# 逐行动作/代价/复算说明/来源列与锚点标记
│   │   ├── anchors.ts        # 锚点索引推导、排序切换、错误路径解析
│   │   ├── HighlightedTextarea.tsx
│   │   ├── jsonLocations.ts  # 带源码区间的 JSON 解析器（高亮首个错误）
│   │   ├── validation.ts     # 与后端一致的浏览器端校验
│   │   ├── api.ts            # /api/align 客户端（可选 anchors）
│   │   └── e2e/              # Playwright 真实联调用例
│   ├── Dockerfile            # 多阶段构建 + nginx 同源代理
│   └── nginx.conf
├── verify/
│   └── verify.py             # 仅用标准库的一次性联调验收脚本
├── docker-compose.yml        # api / web(WEB_PORT) / api(API_PORT) / verify
├── .env.example
└── .gitignore
```

## 9. 关于“无占位实现、无外部匹配库”

DP 矩阵、平局裁决与回溯全部为手写实现（`backend/app/alignment.py`，
约 100 行），未引入任何对齐/编辑距离/模糊匹配第三方库；前端的 JSON
源码定位解析器同样为手写递归下降。所有层（算法对拍、组件交互、浏览器
联调、容器内验收）均有自动化测试覆盖。
