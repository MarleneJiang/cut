"""Copy real stage evidence into a new, immutable-by-convention directory.

Requires only Python's standard library. Does not take screenshots or invent times.
An existing stage is never overwritten. Paths in the record are relative to it.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

KINDS = {"model", "screenshot", "render", "photo", "report", "script", "parameters", "reference", "log"}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def archive(spec_path, root):
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    required = ("stage", "title", "record_type", "performed_by", "problem", "decision", "actions", "result", "artifacts")
    for key in required:
        if not spec.get(key):
            raise ValueError(f"Missing non-empty field: {key}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", spec["stage"]):
        raise ValueError("stage must be a short lowercase slug with digits, hyphens or underscores")
    if spec["record_type"] not in {"contemporaneous", "retrospective"}:
        raise ValueError("record_type must be contemporaneous or retrospective")
    if not isinstance(spec["actions"], list) or not all(isinstance(x, str) for x in spec["actions"]):
        raise ValueError("actions must be a non-empty list of strings")
    if not isinstance(spec["artifacts"], list):
        raise ValueError("artifacts must be a non-empty list")
    sources = []
    for item in spec["artifacts"]:
        if item.get("kind") not in KINDS or not item.get("caption"):
            raise ValueError("Every artifact needs a known kind and truthful caption")
        path = (spec_path.parent / item["path"]).resolve()
        if not path.is_file():
            raise ValueError(f"Evidence file missing: {item['path']}")
        sources.append((item, path))
    root.mkdir(parents=True, exist_ok=True)
    destination = root / spec["stage"]
    if destination.exists():
        raise FileExistsError(f"Stage exists, refusing overwrite: {destination}")
    temporary = Path(tempfile.mkdtemp(prefix=".record-stage-", dir=root))
    try:
        (temporary / "files").mkdir()
        manifest = {key: value for key, value in spec.items() if key != "artifacts"}
        manifest["archived_at_utc"] = datetime.now(timezone.utc).isoformat()
        manifest["time_note"] = "Archive time is not proof of historical operation time. Source mtime is metadata only."
        manifest["artifacts"] = []
        for i, (item, source) in enumerate(sources, start=1):
            relative = Path("files") / f"{i:02d}-{source.name}"
            target = temporary / relative
            before = sha256(source)
            shutil.copy2(source, target)
            after = sha256(target)
            if before != after or sha256(source) != before:
                raise ValueError(f"Evidence changed while copying: {source.name}")
            manifest["artifacts"].append({
                "file": relative.as_posix(), "kind": item["kind"], "caption": item["caption"],
                "source_path_as_supplied": item["path"], "sha256": after,
                "size_bytes": target.stat().st_size,
                "source_mtime_utc": datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(),
            })
        (temporary / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        lines = [f"# {spec['title']}", "", f"阶段 `{spec['stage']}` · 记录类型 `{spec['record_type']}`", "",
                 f"执行者 {spec['performed_by']}", "", f"归档时间 {manifest['archived_at_utc']}", "",
                 "归档时间不代表历史操作时间。文件修改时间仅作为元数据保留。", ""]
        for key, label in [("operation_time", "实际操作时间（记录者提供）"), ("problem", "问题"),
                           ("decision", "判断依据"), ("result", "结果"), ("next_step", "下一步")]:
            if spec.get(key):
                lines += [f"## {label}", "", str(spec[key]), ""]
        lines += ["## 实际操作", ""] + [f"- {action}" for action in spec["actions"]] + [""]
        if "parameters" in spec:
            lines += ["## 参数", "", "```json", json.dumps(spec["parameters"], indent=2, ensure_ascii=False), "```", ""]
        lines += ["## 原始证据", ""]
        for item in manifest["artifacts"]:
            lines += [f"- [{item['kind']} · {item['caption']}](<{item['file']}>) — SHA-256 `{item['sha256']}`"]
        (temporary / "record.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Reserve the final directory exclusively, so concurrent writers never replace a stage.
        destination.mkdir()
        try:
            for item in temporary.iterdir():
                shutil.move(str(item), str(destination / item.name))
        except Exception:
            # Preserve any partial evidence for diagnosis; no overwrite on a subsequent run.
            raise
        return destination
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = archive(args.record.resolve(), args.root.resolve())
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"Archive failed: {exc}\n")
    print(json.dumps({"stage_directory": str(result)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
