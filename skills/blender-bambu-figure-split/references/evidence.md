# 毕业设计逐步留痕

## 记录原则

每个有实质变化的步骤都存档，再继续下一步。记录目的是呈现真实的判断、修改和验证，不能为了显得工作量大而虚构操作、工时、失败或截图。标明 AI/脚本辅助、人工判断和实物操作各自做了什么。

建议在模型项目内建 `evidence/`。阶段例如 `00-source`、`01-inspection`、`02-part-plan`、`03-toe-trace`、`04-toe-interface`、`05-fit-check`、`06-full-split`、`07-color-transfer`、`08-plates`、`09-slicing`、`10-test-print`。按实际进度命名，不创建虚假的已完成阶段。

每阶段保留：

- 原始/修改后模型或可复现上一版的工程，外加本阶段切刀、控制点和参数。`.blend` 中保留原始对象、工作对象、切刀、预览集合，名称能对应阶段记录。
- 真实操作前后截图。主要视角、相机和缩放尽量一致；另拍局部接缝、线框/编辑模式、切刀和装配方向。保留能够看出软件和操作状态的上下文。
- 必要渲染图与爆炸图，明确标记“渲染”或“自动生成示意”，与“软件截图”“实物照片”区分。
- 操作记录，写清问题、参考依据、为何拆或合、实际使用的工具/脚本、改动、参数、结果和下一步。参数带单位；选择人工还是自动方式的原因也记录。
- 数值报告、切片结果及日志。关联输入和输出 SHA-256，保存原始报告。截图不能替代可编辑模型和原始日志。

## 归档工具

`scripts/record_stage.py` 不自动抓屏。先用实际可用的 Blender MCP、截图工具或用户提供的截图获取画面；渲染要标成 render。以 JSON 记录实际操作和材料：

```json
{
  "stage": "03-toe-trace",
  "title": "沿鞋头真实斜面拟合闭合切线",
  "record_type": "contemporaneous",
  "performed_by": "AI assisted, reviewed in Blender",
  "problem": "涂色越过凹槽，直接按颜色拆会出现锯齿",
  "decision": "以灰模斜面边缘确定几何边界，粉色仅用于定位",
  "actions": ["保留未修改工程", "画控制点并检查侧面", "拟合闭合曲线"],
  "parameters": {"target_height_mm": 180},
  "result": "完成切线，尚未完成实体试装",
  "next_step": "构建可沿前方抽出的成对切刀",
  "artifacts": [
    {"path": "work/03-toe-trace.blend", "kind": "model", "caption": "带原始对象与切刀的阶段工程"},
    {"path": "work/03-before.png", "kind": "screenshot", "caption": "操作前实际软件画面"},
    {"path": "work/03-after.png", "kind": "screenshot", "caption": "操作后实际软件画面"},
    {"path": "work/03-gray-overlay.png", "kind": "render", "caption": "灰模切线叠加，脚本生成"}
  ]
}
```

清单中路径相对该 JSON 所在目录。命令会把文件复制到独立的阶段目录，生成 `record.md` 和 `manifest.json`，目录已存在时拒绝覆盖：

```sh
python3 scripts/record_stage.py project/trace-record.json --root project/evidence
```

归档时间由程序记为当前 UTC 时间。实际操作时间有可靠来源才填 `operation_time`；不填时不能把归档时间当作历史操作时间。`record_type` 使用 `contemporaneous`（当时留痕）或 `retrospective`（事后整理），补整理的旧文件选后者，说明哪些阶段缺截图、缺工程或仅有脚本。文件系统修改时间只能作为文件元数据，不是操作时间证明。

截图拍到个人信息时，保留原图在本地并另存遮挡版，注明处理内容。公开展示或发布过程档案的范围由用户决定；工具仓库和作品档案分别保存。

## 交付给老师的索引

建立阶段表，按“问题 → 观察 → 选择 → 修改 → 验证”关联记录、模型和图片。允许一页并排展示同视角前后对照，但保留原图。失败或返工记录说明失败原因和更改依据。

切片页标出机型、喷嘴、层高、材料、盘数、支撑、实际用色、耗材/时间估计和通过/未通过状态。实物阶段再补同方向照片、测量、接缝观感和装配问题。未打印时明确标记“未打印、未实物试装”，不把数值无碰撞解释成成品合格。
