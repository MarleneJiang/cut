# Blender 手办拆件与拓竹打印 Skill

把有贴图的 FBX / Blender 手办，整理成边缘干净、零件数量适当、能按明确方向拼装的打印件。按参考图决定配色，按真实几何边缘决定切线，并为毕业设计保存逐步可核验的过程记录。

## 包含内容

- [Skill 入口](skills/blender-bambu-figure-split/SKILL.md)
- [几何拆件、分色与装配方法](skills/blender-bambu-figure-split/references/splitting.md)
- [毕业设计过程留痕](skills/blender-bambu-figure-split/references/evidence.md)
- [拓竹项目与切片验收](skills/blender-bambu-figure-split/references/bambu.md)
- [SeanIXz Pro 插件说明](skills/blender-bambu-figure-split/references/seanixz.md)
- 原始 `seanixz_print_helper_pro_v1_5_9.py`，位于 Skill 的 `assets/blender/`，保持原文件字节与作者标注
- `scripts/audit_parts.py` 检查封闭实体、原位干涉及装配顺序中的抽离路径
- `scripts/heightfield.py` 生成沿单一轴向开放的曲面切刀
- `scripts/record_stage.py` 归档阶段文件、截图和检查报告，生成 SHA-256 清单及操作记录

这是一个辅助判断和执行的 Skill。新模型仍需查看参考图、贴图和多视角几何，并重新设计切线。数值检查、切片通过和真实打印试装是三个不同的验收阶段。

## 安装和使用

把 `skills/blender-bambu-figure-split` 整个目录复制到 `~/.codex/skills/`，在重新加载技能后的新对话使用，例如：

> 用 $blender-bambu-figure-split 检查这个 FBX 和参考图，目标为拓竹 A1 手办。先试拆一只鞋头，沿真实斜面边缘修顺，检查装配。每步保存模型、真实截图、操作记录和检查结果，用于毕业设计过程展示。

几何脚本使用独立 Python 环境。进入 Skill 目录后：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/audit_parts.py --help
python3 scripts/record_stage.py --help
```

Blender 插件需单独在 Blender 中安装并启用。安装步骤见插件说明；复制 Skill 不等于启用插件。过程档案保存在每个模型项目的目录中，默认不进入本工具仓库。

## 来源与验证范围

这套方法整理自一次带 UV 贴图手办的鞋头试拆和整模分件工作。新建的通用脚本使用合成几何进行验证。源作品和参考图不随工具发布。

原插件来自使用者提供的文件，其内部标注作者为 `SeanIXz / ChatGPT`，版权为 `(c) SeanIXz`。随附文件未发现独立许可证声明，本仓库不为它重新授予开源许可，也不声明对其拥有著作权。原文件校验值见 [来源记录](THIRD_PARTY.md)。
