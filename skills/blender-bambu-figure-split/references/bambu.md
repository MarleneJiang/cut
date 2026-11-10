# 拓竹项目与切片验收

使用当前安装版本的机型配置和 CLI 帮助确认参数，不把旧机器配置硬编码为全部用户通用值。记录 Bambu Studio 版本、A1 或其他具体机型、喷嘴、材料、层高及多色设备。支持颜色数取决于实际设备和每盘使用方式；可以换盘换料，不能只看全项目调色板条目数。

## 项目与颜色

保留各件原位关系与单独打印变换，两者写在不同字段。导入实际 STL 后核对毫米尺寸，给每件命名并记录盘位、材料和朝向。支撑尽量避开可见正面和配合面，同时确保连接处层方向不至于很弱。核对支撑、裙边、擦料塔和运动范围是否在可用平台内。

STL 不保留贴图。Blender 中从原始 UV 对应关系给拆件重投影，并在多色 3MF 中建立明确的面/区域到耗材映射。复杂眼睛、细藤条和花纹需要检查实际切片预览是否能被喷嘴表达。若需要量化为较少颜色，保留“设计颜色 → 实际耗材 → 所属部件”的表，说明舍弃或合并的颜色。

优先通过 Bambu Studio 自身操作生成和保存项目。必须编辑 3MF 时，先检查已知可正常打开的该版本样例。3MF 是 ZIP/XML；组件资源可能通过 production 扩展 `p:path` 指向另一个文件，不能假定模型全在 `3D/3dmodel.model`。对象 ID 与文件路径一起定位，维护命名空间、关系、材质及盘位。不要重新三角化带面级涂色的网格后沿用旧 face ID。

旧流程使用过 CLI 形态：

```sh
"$BAMBU_BIN" --datadir "$PROJECT/bambu-data" --debug 2 \
  --load-settings "$PROJECT/machine.json;$PROJECT/process.json" \
  --load-filaments "$PROJECT/filament.json" \
  --load-assemble-list "$PROJECT/assemble.json" \
  --arrange 0 --orient 0 --outputdir "$PROJECT" --export-3mf base.3mf

"$BAMBU_BIN" --datadir "$PROJECT/bambu-data" --debug 2 \
  --arrange 0 --orient 0 --slice 0 --outputdir "$PROJECT/sliced" \
  --export-3mf sliced.3mf "$PROJECT/painted.3mf"
```

这些是命令形式示例，需要先准备并检查当前版本对应的配置及清单；多耗材按该版本要求传入完整列表。不要直接复制旧作品的绝对路径、坐标或不匹配的机型预设。参数 `--arrange 0 --orient 0` 用来保留已经确认的摆放，所以输入排盘本身必须正确。

## 验收与证据

- 保存可编辑的未切片项目、完成后的切片项目、CLI 日志及 `result.json`（若版本提供）。检查返回码、每一盘的切片结果，而不是只看到文件存在。
- 打开完成项目，保存真实“准备”页面截图及各盘关键层的“预览”截图，关注悬空细节、薄壁、配合槽和颜色边界。
- 查看切片结果的实际耗材使用。旧版本项目 `Metadata/slice_info.config` 的逐层用色列表可能采用从零开始的槽位 ID；统计报告也可能包含未实际使用的默认槽。对照当前版本和实际 G-code/预览核验，不能把配置里有颜色当作打印中用了颜色。
- 汇总每盘耗材和预计时间，包含支撑、换色冲刷及擦料塔；不要仅加总模型净重量。
- 报告准确说明完成范围。切片成功证明软件生成了路径，不能证明尺寸、承重、表面或拼装手感已通过真实打印。
