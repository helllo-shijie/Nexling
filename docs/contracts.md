# 内核契约（供各 domain 包实现时参照）

> 所有 domain 包**只能** `from laa_core.shared import ...`；领域层禁止 import `laa_core.infra` / `laa_core.app` / UI。
> 术语判定链路（匹配/冲突/一致性/抽取）**零模型、零网络**，结果必须可复现。

## 1. 运行时存储接口（duck-typed Repository）

App 层会把一个实现了以下方法的仓储对象注入到有状态的领域服务里。domain 包**不要 import 它**，只按名字调用即可。dict 的字段名以 `laa_core/shared/dto.py` 里对应 dataclass 的 `dump()` 输出为准（snake_case）。

```python
# 术语库
repo.list_banks() -> list[dict]
repo.get_bank(bank_id: str) -> dict | None
repo.save_bank(bank: dict) -> None
repo.list_entries(bank_id: str) -> list[dict]          # 未删除、按 source_term 排序
repo.get_entry(entry_id: str) -> dict | None
repo.save_entry(entry: dict) -> None                    # upsert by id
repo.delete_entry(entry_id: str, hard=False) -> None    # 默认软删 deleted_at
repo.next_bank_version(bank_id: str) -> int

# 场景档案
repo.list_scenes() -> list[dict]
repo.get_scene(scene_id: str) -> dict | None
repo.save_scene(scene: dict) -> None
repo.delete_scene(scene_id: str, hard=False) -> None

# 任务 / 片段 / 版本
repo.save_task(task: dict) -> None
repo.get_task(task_id: str) -> dict | None
repo.list_tasks() -> list[dict]
repo.update_task(task_id: str, patch: dict) -> dict | None
repo.save_segment(seg: dict) -> None
repo.list_segments(task_id: str) -> list[dict]
repo.save_version(version: dict) -> None
repo.list_versions(segment_id: str) -> list[dict]
repo.latest_version(segment_id: str) -> dict | None

# 任务级术语一致性（V10）：同一 task 内 source_term 唯一
repo.list_task_terms(task_id: str) -> list[dict]      # 按 source_term 排序
repo.upsert_task_term(term: dict) -> dict             # 优先级 user > glossary > model，低优先级不覆盖

# 翻译记忆（V8 起仅手动写入，created_at 用于上限清理时「最老优先」）
repo.upsert_tm(entry: dict) -> None
repo.list_tm() -> list[dict]                     # 按 created_at ASC, rowid ASC 返回
repo.find_tm_exact(source_hash: str, lang_pair: str) -> list[dict]

# 术语候选上限 / 手动清空
repo.trim_term_candidates(status: str, keep: int) -> int              # 只保留最新 keep 条，返回删除数
repo.delete_term_candidates(status=None, task_id=None) -> int         # 手动清空（可按状态/任务过滤）

# 账本（账单/统计的唯一来源，不受 calls 裁剪影响）
repo.append_usage(entry: dict) -> None
repo.sum_usage(group_by: str, exclude_providers=None) -> list[dict]  # day/provider/purpose/task
repo.usage_totals(exclude_providers=None) -> dict                     # {calls,input_tokens,output_tokens,amount}
repo.usage_range() -> dict                                            # {first_at,last_at}

# 调用历史（与账本分表；裁剪/清空只动这里）
repo.trim_calls(keep: int) -> int                 # 只保留最新 keep 条，返回删除数
repo.delete_calls_before(cutoff_iso: str) -> int  # 按 UTC ISO 时间清理
repo.clear_calls() -> int

# 配置 / 供应商
repo.get_config(key: str, default=None) -> Any
repo.set_config(key: str, value) -> None
repo.list_providers() -> list[dict]
repo.save_provider(profile: dict) -> None
```

## 2. 确定性约束（硬性）

- 一切字典键名用 snake_case，与 `dto.dump()` 一致。
- 时间戳：`from laa_core.shared import utc_now`。
- 新 ID：`from laa_core.shared import new_id`。
- 错误：`from laa_core.shared import err`（`err("LAA-4004", ...)`），或 `raise LaaError(code, ...)`。
- 禁止 `import openai/requests/httpx`、禁止子进程、禁止网络。

## 3. 皮肤包契约（V11）

- 单文件 zip（`.nxlskin`），必需 `skin.json`；可选 `background.<png|jpg|webp|gif>` 与任意截图；
  截图**不读取、不校验、不保存、不导出**，只为供人翻看。
- `skin.json` 字段：`format="nexling.skin"`、`version=1`、`id`（小写字母/数字/连字符，2–40，字母开头，
  不得占用 `default`/`mint`）、`name`（≤60）、`author`（≤80）、`description`（≤400）、
  `mode="light"|"dark"`、`vars`、`effects:{glass:"on"|"off"}`、`background:{file,scrim:"low"|"medium"|"high"}`。
- `vars` 只接受白名单键：颜色（hex 3/4/6/8、`rgb()/rgba()`、`hsl()/hsla()` 含 alpha 与 `transparent`）、
  阴影（受限语法，禁止 `url/var/expression/@/;`）、圆角（0–32px）；未知键、未知字段、非法值一律拒绝导入。
  颜色必须先解析成功：无法解析的写法直接拒绝，不跳过对比度检查。
- `mode="dark"` 必须给全全部颜色与阴影变量；导入时先把包内 `vars` 合并到内置浅色/深色基线，
  再按**从样式源码派生**的配对表 `laa_core/domain/skin/contrast_pairs.json` 校验对比度，
  不因包内缺键而跳过。
- 配对表由 `tools/derive_contrast_pairs.py` 生成：扫描 `webui/src/styles/*.css` 的规则块，
  把 `color` 里的颜色变量与 `background`/`background-color`/`background-image` 里的颜色变量两两配对；
  只设底色的块按继承的 `--text` 配对（状态变体如 `:hover` 先回溯到基础选择器取文字色）；
  只设文字色的块对 `--bg` 与 `--surface` 各配一次。
  阈值按前景语义：正文类（`--text`、`--code-fg`、`--toast-fg`）≥ 4.5，其余 ≥ 3.0。
  确实不含文字的装饰性底色（图表柱、滚动条、遮罩、色条等）按具体配对列入白名单并逐条注明理由，
  不支持整变量豁免。
- 覆盖范围包含正文、代码块、提示条、状态与置信度徽标、主按钮悬停、当前导航项、
  情绪标签底色、句子情感底色、页面渐变（`--bg-tint`）、低置信度行底色等全部实际组合。
- 样式新增配色组合但未重新生成配对表时，`tests/test_v11_contrast_pairs.py` 会失败并打印
  缺失的配对与来源选择器。

  任一侧解析失败、为透明或低于阈值即拒绝导入。
  透明前景直接判为不达标，半透明按 alpha 叠到已知底色后计算；不存在“只给部分变量所以跳过”的路径。
- 单包总大小（zip 与解压后）上限 5 MB；背景图上限 4 MB；`skin.json` 上限 256 KB。
- 存储：`<data_dir>/skins/<id>/skin.json` + `background.<ext>`；同 ID 导入原子替换，不并存版本。
- 不执行任意 CSS/JS，不携带字体，不改布局；前端只把 `vars` 写到根元素并设置
  `data-skin` / `data-skin-mode` / `data-skin-glass` / `data-skin-bg`。
- `app.skin.active` 存当前皮肤 id；失效时回退 `default`。深色切换通过 DWM 属性同步原生标题栏。

## 4. 验收句柄

各包必须在模块末尾或独立 `self_test.py` 内提供一段可 `python -c` 或 `python -m` 的纯内存自测，证明核心函数可跑（不需要 pytest）。