# NexLing 领域术语包

六个面向英译中的领域术语包，共 831 条。可直接在 NexLing 的「术语库 → 导入术语包」中导入，也可作为术语包格式示例参考。

## 文件清单

| 文件 | 领域 | 条目数 | 字节数 | 典型易错词 |
| --- | --- | ---: | ---: | --- |
| `digital-hardware-semiconductors.json` | 数字硬件与半导体 | 127 | 22817 | cache coherence、out-of-order execution、metastability |
| `advanced-mathematics.json` | 高等数学 | 136 | 23905 | eigenvalue、monomorphism、condition number |
| `machine-learning-deep-learning.json` | 机器学习与深度学习 | 145 | 26387 | backpropagation、perplexity、retrieval-augmented generation |
| `computer-networks.json` | 计算机网络 | 133 | 23389 | congestion control、head-of-line blocking、anycast |
| `databases-distributed-systems.json` | 数据库与分布式系统 | 149 | 25379 | write-ahead logging、linearizability、bloom filter |
| `compilers-programming-languages.json` | 编译原理与程序语言 | 141 | 24812 | monomorphization、static single assignment form、tail call optimization |

适用场景：阅读或翻译对应领域的英文论文、教材、技术文档、RFC 与源码注释。术语方向为英译中（`source_term` 英文，`target_term` 中文），源词保持小写，便于不区分大小写匹配。

## 术语包格式

导入器只读取 `entries` 数组，其余顶层字段仅作说明与版本管理，不参与导入。

```json
{
  "schema_version": "glossary-package/v1",
  "pack_id": "advanced-mathematics",
  "name": "高等数学",
  "description": "……",
  "version": "1.0.0",
  "langs": ["en", "zh-Hans"],
  "domain": "mathematics",
  "license": "CC-BY-4.0",
  "attribution": "NexLing community glossary",
  "entry_count": 136,
  "entries": [
    {
      "source_term": "eigenvalue",
      "target_term": "特征值",
      "domain": "mathematics",
      "definition": "满足 Ax=λx 的标量 λ；勿译作“本征值”以外的字面“固有值”。"
    }
  ]
}
```

条目字段：

- `source_term`、`target_term`：必填，均为非空字符串，导入时先去除首尾空白；任一为空则该条计为 `skipped`。
- `domain`：可选，缺省为 `general`。
- `definition`：可选，中文释义或易错点，会保留在词条中并可在术语库查看。
- `part_of_speech`：可选，词性。
- `forced`：可选，布尔值，表示强制采用该译法。
- `scene_variants`：可选，`{场景 ID: 该场景译词}`。
- `match_mode`：可选，缺省 `exact`；其他未知键会被忽略。

语言说明：导入时条目语言按通配处理，不读取顶层 `langs` 或条目级语言字段。因此英文源词在英译中、中译英两种任务中都会参与匹配；中译英时只有当原文出现该英文术语才会命中。

## 如何导入

### 界面操作

1. 打开「术语库」页，选择目标词库（内置 `personal-default` 为可写个人库；`builtin-default` 只读，导入时会自动落到 `personal-default`）。
2. 点击「导入术语包」，选择或拖入本目录中的 `.json` 文件。
3. 选择覆盖模式：
   - `merge`：同一词库中已存在相同 `source_term` 时，用新条目覆盖译词、域与释义，并把该词条版本号加 1。
   - `append`：已存在相同 `source_term` 时跳过，不改动原词条。
4. 导入完成后可在词条列表按域筛选查看。

六个包可以全部导入同一个词库，源词互不重复；也可以每个包建一个词库，再在「场景」中把需要的词库绑定到场景。导入后建议在实际翻译任务中检查透明化面板的术语提示，确认译法符合团队习惯后再签署。

### 脚本或桥接调用（可选）

CLI 没有术语导入子命令；导入走本地 HTTP 桥的 `glossary.import` 命令：

```powershell
# 启动桥接服务后，从输出中取得一次性 token
python cli.py --data <临时数据目录> serve --port 8799

$body = @{
  cmd = "glossary.import"
  payload = @{
    package = (Get-Content .\advanced-mathematics.json -Raw | ConvertFrom-Json)
    mode = "merge"
    target_bank_id = "personal-default"
  }
} | ConvertTo-Json -Depth 10

Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8799/api/invoke `
  -Headers @{ "X-NexLing-Token" = "<token>" } `
  -ContentType "application/json" -Body $body
```

返回值为 `{"inserted": n, "skipped": n, "updated": n}`。若要导入到独立词库，先调用 `glossary.bank.create` 创建词库，再把返回的 `id` 作为 `target_bank_id`。

## 重复与去重

- 去重范围是单个目标词库，判定条件是 `source_term` 去除首尾空白后与已有词条**完全一致**（区分大小写）。`Cache Coherence` 与 `cache coherence` 会被视为两个词条。
- 同一文件内、六个文件之间已做过去重检查，不存在相同源词；词条也不会与内置词库的 15 条基础术语重复。
- 重复导入同一文件：`merge` 会逐条更新并递增词条版本，`append` 会全部跳过；插入数、跳过数、更新数会在返回值和界面提示中如实显示。

## 许可

术语与释义由本仓库维护，采用 CC-BY-4.0。术语译法以国内计算机与数学教材的通行译法为准；如与团队既有规范不一致，导入后可直接在术语库中修改，修改只影响该词库中的条目。
