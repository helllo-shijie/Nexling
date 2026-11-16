# NexLing v1.11.0（V11）

> **状态：已定版（2026-11-16）**
> 本版从 v10（已定版，2026-11-16）复制而来，v10 及更早目录未做任何修改。
> 独立复核四轮已全部通过，结论为「可以定版」，无必须修项；定版依据见文末「定版依据」。

> 对外名称：NexLing　｜　Python 包名：`laa_core`
> 数据目录：`%LOCALAPPDATA%\NexLing`（旧版便携目录 `.laa` 仅兼容读取，首次启动复制迁移）

## 启动方式

1. 双击本目录下的 `NexLing.cmd`（内部调用 `dist\NexLing\NexLing.exe`）。
2. 原生启动窗先出现，主窗在页面骨架/加载完成时显示，页面报告「可输入」后输入框可用。
3. 首次运行在 `%LOCALAPPDATA%\NexLing\` 建库；设置 → 模型 可填 API Key 切到真实模型。
4. 随交付目录的 `dist\NexLing\skins\` 放了三套示例皮肤包，需在「设置 → 界面 → 皮肤」导入后使用；
   它们**不内置**进默认列表。

命令行方式：`python run.py serve --port 8787 --static .\webui\dist`。

## 本版改动

### 1. 皮肤系统

**内置两套（不可删除）**

- `default`：V10 现有浅色学术风，作为默认皮肤，变量全部沿用 `global.css`。
- `mint`：参考 `人工补充/style3/global.css` 的视觉语言（薄荷青主色、较大圆角、更软的阴影），
  只吸收样式，不改任何布局结构；调色板在后端 `laa_core/domain/skin/service.py` 定义。

**外置示例包（三套，随交付目录提供）**

| 包 | 明暗 | 特点 |
| --- | --- | --- |
| `liquid-glass.nxlskin` | 浅色 | 仿 `人工补充/style2` 的冷银 + 毛玻璃；`effects.glass="on"`，`backdrop-filter` 仅作用于顶栏、历史侧栏、抽屉、设置导航，主内容区不做整页模糊 |
| `night.nxlskin` | 深色 | 完整深色变量（含情感概率条、置信度、术语高亮、行内句子情感底色、代码块、图表、滚动条、`color-scheme`），原生标题栏跟随变深 |
| `warm-contrast.nxlskin` | 暖色浅色 | 偏暖纸白 + 砖红强调，高对比、小圆角 |

示例包内含一张工作台截图，供人翻看挑选；软件**不读取、不显示、不校验**该截图，导出时也**不导出**。

**皮肤包格式（`.nxlskin`，单文件 zip）**

- 必需：`skin.json`；可选：背景图（`background.<ext>`）、任意文件名/格式的截图（软件忽略）。
- `skin.json`：
  ```json
  {
    "format": "nexling.skin",
    "version": 1,
    "id": "night",
    "name": "深空夜色",
    "mode": "dark",
    "vars": {"--bg": "#0f141b", "...": "..."},
    "effects": {"glass": "off"},
    "background": {"file": "background.png", "scrim": "high"}
  }
  ```
- 只接受声明式白名单键：颜色（hex/rgb/hsl/transparent）、阴影（受限语法）、圆角（0–32px）；
  未知字段、非法值、保留 id 一律在导入时报错拒绝。`effects.glass` 仅接受 `on` / `off`。
- 不携带字体文件、不换字体、不改布局；不支持任意 CSS/JS 与远程资源。
- 单包解压后总大小上限 **5 MB**，超限拒绝并说明；背景图单独上限 4 MB。
- 深色包必须提供全部颜色与阴影变量，并做 WCAG 对比度校验（正文/背景 ≥ 4.5，次级/弱化文字 ≥ 3.0，
  强调色上的文字 ≥ 3.0），不满足即拒绝导入。
- 同 ID 导入视为更新（原子替换，不并存版本）；切换即时生效，不重载页面；删除外置皮肤或导入失败时可切回默认恢复。
- `file.save_dialog` 增加 `base64_encoded` 支持，导出二进制包不经过文本转码。

**界面**

- 皮肤设置是「设置 → 界面」下的子标签，不新增顶级页；列表含内置/已导入、明暗、毛玻璃、背景图标记、
  当前生效皮肤与色板圆点，并提供使用、导入、导出、删除（内置不可删）。
- 深色皮肤下仅通过 DWM `DWMWA_USE_IMMERSIVE_DARK_MODE` 让原生标题栏变深；浅色保持系统默认，不自绘标题栏。
- 背景图只作用在主内容区，并叠一层可配置遮罩（low 0.55 / medium 0.72 / high 0.86）。

### 2. 设置 → 用量（四个页签）

1. **账单**：沿用原有汇总卡、按供应商、按天与调用明细。
2. **调用历史**：每页 20 条分页，避免上千条一屏拉长；翻页收起已展开详情。
3. **统计概览**：总花费/token/调用次数、最近 14 天趋势、按用途汇总，并提示离线口径。
4. **设置**：保留条数（默认 2000，可勾选无上限）、按 30/90 天清理、统计开关、包含离线开关、
   清空调用历史。

**数据口径**

- 账单与统计读 `usage` 账本；调用历史读 `calls` 表，两者分离。
- 保留上限对已有记录**只提示不删**：升级后只显示「当前 X 条，超过建议上限」，普通设置保存不裁剪；
  只有用户在本页主动点「保存并应用」才执行裁剪。按天数清理与清空历史都需显式点击。
- 裁剪/清空只动 `calls`，`usage` 聚合保留；账单与统计数字在清理后保持不变。

### 3. 版本与文档

- `laa_core.__version__`、`pyproject.toml`、`webui/package.json` / `package-lock.json`、
  `desktop.py` 关于信息、i18n 关于文案统一为 **1.11.0**。
- 同步 README、移交说明、前端契约、领域契约与本文件。

### 4. 独立复核三条修复（2026-11-16，仍在 v11 内）

- **颜色解析不再绕过对比度**：`_parse_color` 覆盖 hex(3/4/6/8)、`rgb()/rgba()`、
  `hsl()/hsla()`（逗号或空格+斜杠、可选 `deg`、百分比与 alpha）与 `transparent`；
  任何无法解析的颜色直接拒绝导入；透明前景判为不可读，半透明颜色按 alpha 叠到底色后计算对比度。
- **按天数清理不再误删**：`usage.calls.cleanup` 的 `days=0` 原样保留并一条不删（不再回落到配置 30）；
  用量设置里选「不按天数清理」时「立即按天数清理」按钮禁用并给出说明，30/90 天清理加 `confirm`
  二次确认后才执行。
- **深色冷启动标题栏**：DWM 属性写入改为“立即尝试 + 后台重试到句柄就绪”，窗口 `show()` 后再补写一次
  （隐藏窗口上的 DWM 写入可能被系统丢弃），最终失败写 `startup.log`；启动期读取
  `config.value` 先做 JSON 解码，避免把 `"night"` 当成带引号的皮肤 id。

### 5. 第二轮复核修复（2026-11-16，仍在 v11 内）

- **部分变量不再绕过对比度**：导入校验先把包内 `vars` 合并到内置基线，再对全部组合逐一检查；
  浅色基线取默认学术风，深色基线取内置深色语义。检查组合包括正文/次要/弱化文字分别对
  `--bg` 与 `--surface`、按钮文字对 `--accent`；任一侧解析失败、为透明或低于阈值（4.5 / 3.0）
  即拒绝导入，不存在“只给部分变量所以跳过”的路径。
- 复核给出的四个用例（`--text: transparent`、`--text: rgba(0,0,0,0)`、
  `--bg/--surface: #0f141b`、`--text: #ffffff`）均被拒绝；拒绝后前端保持原皮肤，不自动选中。
- 合规的部分变量包（只改主色）仍可正常导入。

### 6. 第三轮复核修复（2026-11-16，仍在 v11 内）

- **对比度校验扩展到组件级配对**：新增 `CONTRAST_PAIRS` 配对表，键全部来自基线定义，
  不因包内未给某个键而跳过；校验流程为「包内 `vars` 合并基线 → 逐配对计算 → 任一失败即拒绝」。
  覆盖范围：
  - 正文 `--text` 对 `--bg` / `--surface` / `--surface-2` / `--surface-hover` / `--accent-soft` /
    `--row-src-bg` / `--row-hover-bg` / `--row-src-hover-bg`（≥ 4.5）；
  - `--code-fg` 对 `--code-bg`、`--toast-fg` 对 `--toast-bg`（≥ 4.5）；
  - 次要 `--text-secondary`、弱化 `--text-muted` 对 `--bg` / `--surface` / `--surface-2` /
    `--surface-hover` / `--accent-soft`（≥ 3.0）；
  - 主按钮与当前导航项：`--on-accent` 对 `--accent` 与 `--accent-hover`、`--accent` 对 `--accent-soft`（≥ 3.0）；
  - 状态与置信度徽标：`--success-fg/--success-bg`、`--warn-fg/--warn-bg`、`--warn-strong/--warn-bg`、
    `--danger-fg/--danger-bg`、`--risk-fg/--risk-bg`、`--confidence-high-fg/-bg`、
    `--confidence-medium-fg/-bg`（≥ 3.0）；
  - 同一轮把实际会作为前景的其它键也纳入：`--accent` 对 `--bg`/`--surface`、`--danger-fg` 对 `--surface`、
    语义色（`--positive/--negative/--neutral/--urgent/--apology/--emphasis/--humor`）与
    `--confidence-low-fg` 对 `--surface`（≥ 3.0），以及 `--text` 对 `--low-bg`/`--row-low-bg`/`--seg-low-bg`
    （≥ 4.5）、`--confidence-low-fg`/`--urgent`/`--warn-fg` 对 `--low-bg`（≥ 3.0）。
- 浅色与深色基线都补齐到上述全部键；背景键半透明时按 alpha 叠到 `--surface`，前景或底色全透明直接拒绝。
- 回归用例扩充为 16 例（第四轮继续扩充到 24 例，见下节）：除前两轮的透明/深底/白字外，新增只改
  `--surface-2`、`--code-bg`、`--toast-bg`、四个状态底色、`--accent-hover`、`--accent-soft`、`--negative`、
  `--danger-fg`、`--low-bg` 的单键包，全部被拒绝；合规整包（三套示例）与只改主色的部分包仍可导入。

### 7. 第四轮复核修复：对比度配对改为结构式派生（2026-11-16，仍在 v11 内）

- **不再手工维护配对清单**：新增 `tools/derive_contrast_pairs.py`，扫描 `webui/src/styles/*.css`，
  按规则块把 `color` 的颜色变量与 `background`/`background-color`/`background-image` 的颜色变量两两配对；
  只设底色的块按继承的 `--text` 配对（`:hover` 等状态变体先回溯基础选择器取文字色），
  只设文字色的块对 `--bg`/`--surface` 各配一次。产物写入 `laa_core/domain/skin/contrast_pairs.json`（61 组），
  运行时校验只读该产物，打包时随 `NexLing.spec` 一起进 `dist`。
- **补齐复核点名的 11 组**：`--text`/`--risk-bg`、`--negative`/`--risk-bg`、
  `--positive`/`--emotion-positive-bg`、`--urgent`/`--emotion-urgent-bg`、
  `--apology`/`--emotion-apology-bg`、`--emphasis`/`--emotion-emphasis-bg`、`--humor`/`--emotion-humor-bg`、
  `--text`/`--sent-pos-bg`、`--text`/`--sent-neg-bg`、`--accent`/`--bg-tint`、`--positive`/`--success-bg`。
  两套基线补齐 `--sent-pos-bg`、`--sent-neg-bg`、`--emotion-*-bg`、`--bg-tint` 等键。
- **阈值沿用**：`--text`/`--code-fg`/`--toast-fg` 这类正文前景 ≥ 4.5，其余（次要文字、链接、状态与语义色、
  大字与图形边界）≥ 3.0；解析失败或任一侧透明一律拒绝。
- **白名单只按具体配对**：图表柱/网格、句子情感色条、滚动条、遮罩、纯色块等确实不含文字的底色逐条列出，
  每条写明理由，不支持整变量豁免；测试会校验白名单条目仍然真实存在，避免僵尸豁免。
- **防护已验证**：`tests/test_v11_contrast_pairs.py` 在样式里临时加入
  `.contrast-probe { color: var(--warn-strong); background: var(--success-bg) }` 后，
  派生结果会新增该配对，产物比对按预期失败并打印变量与选择器；三个组件抽查（工具提示 `.feature-notice`、
  状态徽标 `.tp__badge`、句子情感底色 `.sent--positive`）的派生配对与 CSS 实际写法一致。
- 顺带修正：提示条 CSS 原来用 `--text` 作底色、`--toast-bg` 从未被使用，现改为真正的 `--toast-bg`，
  使“只改 toast-bg”能真实影响提示条并被校验拦住。

### 8. 定版前清理（2026-11-16）

- **白名单僵尸条目**：`--text`/`--chart-grid` 在样式里只作 `border-bottom-color`，从不会形成
  “文字 × 底色”组合，已从白名单删除；同时修正 `test_whitelist_is_specific_and_reasoned`
  的取值时机（原先在 monkeypatch 之后才读取 `WHITELIST`，导致僵尸检查空转），
  现在去掉白名单后重新派生，任何样式不再产生的白名单条目都会让测试失败。
- **体积口径**：统一按 `1 MiB = 1,048,576 字节`、四舍五入到两位小数记 `25.74 MiB`
  （打包脚本终端按一位小数打印为 `25.7 MiB`，是同一数值的不同精度，不是差异）。
- **薄荷皮肤提示条底色**：`mint` 的 `--toast-bg` 为 `#123c33`（青绿色偏暗），与默认 `#1b2430`
  （蓝黑）有可察觉的色相变化，这是薄荷主题的设计选择；文字仍为白色，对比度约 11.9:1，可读性不受影响。
- **纯装饰键可自由设色**：`--scrollbar-thumb`、`--scrim`/`--scrim-soft` 属于滚动条、遮罩等
  不承载文字的元素，按具体配对列入白名单并注明理由，因此不会进入对比度校验，
  这是有意为之，皮肤作者可自由设定，不会造成文字不可读。

## 定版依据

- 独立复核确认：派生配对共 **61 组**，对样式源码的配色组合覆盖完整。
- 34 个绕过探针中，除 `--scrollbar-thumb` 与 `--scrim` 两个纯装饰键（按设计不参与文字对比度）外，
  其余全部被拒；复核点名的单键/部分变量组合无一漏过。
- 抽查组件（工具提示、状态徽标、句子情感底色等）实测最低对比度 **4.58:1**，高于对应阈值。
- 复核结论：无必须修项，可以定版；本版定版后不再改动。

## 验证记录

- 后端：`pytest` 全量连续运行三次均通过（**242 passed × 3**；含
  `tests/test_v11_skin_and_usage.py` 26 条、`tests/test_v11_contrast_pairs.py` 8 条与示例包发布守卫）。
- 前端：`npm run typecheck`、`npm test`（27 条，含 `skin-apply.test.ts`）、`npm run build` 通过。
- 打包：`python tools/build_release.py` 完成启动自检（5.6s 进入可输入状态）与发布守卫（5/5）；
  `dist\NexLing` 共 **153 文件 / 25.74 MiB**（26,989,707 字节，1 MiB = 1,048,576 字节；
  打包脚本终端按一位小数显示为 25.7 MiB）。
- dist 与源码一致：`laa_core/domain/skin/contrast_pairs.json` 与
  `dist\NexLing\app\_internal\laa_core\domain\skin\contrast_pairs.json` SHA-256 相同；
  `webui/dist/index.html` 与包内 `webui\dist\index.html` SHA-256 相同。
- dist 真产物（CDP 驱动，临时数据目录）逐项通过：
  - 内置 `mint` 与应用内切换、页面不重载（`performance.timeOrigin` 不变）；
  - 三套示例包与一张背景图包经界面文件输入导入成功；同目录截图未落盘；
  - `night` 深色：语义变量完整、`color-scheme=dark`、DWM 标题栏变深；工作台、术语库、设置各节
    与用量四页签逐页截图，文本对比度自动检查无低于门槛项；
  - 毛玻璃仅 `topbar` 命中 `backdrop-filter`，`.main` 为 `none`；
  - 背景图只在 `.main`，遮罩 `rgba(...,0.86)`；
  - 导出 `night.nxlskin` 仅含 `skin.json`，无截图；删除外置皮肤后回退默认；
  - 用量四页签齐全；102 条调用下分页 20/页并可翻页；超限只提示、普通保存不裁剪；
    主动点「保存并应用」后裁到 100 条；裁剪前后账单 totals 完全一致。
  - 复核修复后实测：`hsl()` 1:1 与 `transparent` 前景均被拒（错误信息含「对比度 / 透明」）；
    `days=0` 返回 `removed=0` 且 10 条调用原样保留；「不按天数清理」时清理按钮禁用，
    30 天清理弹二次确认且取消后不执行；`night` 冷启动 DWM 属性为 1，切浅色回 0、切深色回 1。
  - 第二轮复核后实测：四个部分变量用例全部被拒（透明 2 例、深底 1.2:1、白字 1.1:1），
    拒绝后 `skin.active` 仍为 `default`；仅改主色的合规包仍可导入。
  - 第三轮复核后实测（重新打包的 dist，CDP 驱动，临时数据目录）：十二个单键用例全部被拒并给出具体配对，
    `--surface-2`、`--code-bg`、`--toast-bg` 均报各自配对 1.0:1；`--success-bg/--warn-bg/--danger-bg/--risk-bg`
    与对应前景同色被拒；`--accent-hover` 报 `--on-accent` 1.0:1、`--accent-soft` 报 `--text` 1.0:1；
    `--negative`/`--danger-fg` 报对 `--surface` 1.0:1、`--low-bg` 报 `--text` 1.0:1；
    拒绝后 `skin.active` 仍为 `default`；只改 `--accent`、主色三键的部分包与三套示例整包均导入成功。
  - 第四轮复核后实测（重新打包的 dist）：二十个单键用例全部被拒并给出派生配对，
    复核点名的 11 组逐条命中：`--negative`/`--risk-bg`、五种 `--emotion-*-bg` 与对应语义色、
    `--text` 对 `--sent-pos-bg`/`--sent-neg-bg`、`--accent` 对 `--bg-tint`（2.3:1）、
    `--positive` 对 `--success-bg`；拒绝后 `skin.active` 仍为 `default`；
    只改 `--accent`、主色三键的部分包与三套示例整包仍导入成功。
- 截图：`docs/screenshots/{liquid-glass,night,warm-contrast}.png`（同时作为示例包内截图）；
  深色逐页证据在 `docs/screenshots/v11-dark/`（工作台、术语库、设置各节、用量四页签、皮肤列表）。

## 已知问题

- 毛玻璃依赖 WebView2 的 `backdrop-filter`；低端机滚动时仍可能有轻微合成开销，故只用于固定小块。
- 皮肤变量白名单是刻意收窄的：不支持阴影内多色复杂写法、渐变、动画与自定义字体。
- 深色标题栏依赖 Windows 10 20H1+ 的 DWM 属性；系统不支持时会重试到超时并在 `startup.log`
  记录一条失败，界面功能不受影响。
- `NEXLING_DEBUG_PORT` 仅供本机自动化验收，设置后才打开 WebView2 调试端口，默认关闭。
- 启动耗时受机器负载影响；本轮多次打包自检在 5.8–8.2 s 内进入可输入状态。

## 花费

- 本轮 dist 端到端验证全部使用离线演示引擎，未发起真实 API 请求，花费 $0，远低于 ¥1 上限。
- 未读取或改动 `%LOCALAPPDATA%\NexLing` 下的真实配置与凭据；如需真实渠道连通性复核，
  建议在独立复核时用已配置 Key 的环境跑一条短句。
