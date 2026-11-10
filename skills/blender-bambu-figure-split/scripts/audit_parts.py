"""Read-only STL solid and sampled straight-withdrawal audit. Coordinates in mm.

Exit 0: listed geometric checks passed. Exit 1: failed check. Exit 2: invalid input.
No mesh repair, continuous collision detection, wall-thickness or physical-fit test.
"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path

import manifold3d as m
import numpy as np
import trimesh


def load_solid(path):
    if path.suffix.lower() != ".stl":
        raise ValueError("Only STL files are accepted; export with assembly coordinates in mm")
    mesh = trimesh.load_mesh(path, process=False)
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces):
        raise ValueError(f"Not a non-empty triangle mesh: {path.name}")
    if not np.isfinite(mesh.vertices).all():
        raise ValueError(f"Non-finite coordinates: {path.name}")
    # STL stores independent facet vertices. Weld exact duplicates only, with no repair.
    vertices, inverse = np.unique(mesh.vertices, axis=0, return_inverse=True)
    mesh = trimesh.Trimesh(vertices, inverse[mesh.faces], process=False)
    if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume <= 0:
        raise ValueError(f"Not a closed, consistently oriented positive-volume mesh: {path.name}")
    solid = m.Manifold(m.Mesh64(np.asarray(mesh.vertices, dtype=np.float64),
                                np.asarray(mesh.faces, dtype=np.uint64)))
    if solid.status() != m.Error.NoError or solid.is_empty():
        raise ValueError(f"Manifold rejected {path.name}: {solid.status()}")
    components = solid.decompose()
    if len(components) != 1:
        raise ValueError(f"{path.name} has {len(components)} solids; inspect and declare them separately")
    return solid, {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "faces": len(mesh.faces), "volume_mm3": float(solid.volume()),
        "bounds_mm": mesh.bounds.tolist(), "components": len(components),
        "watertight": True, "winding_consistent": True,
    }


def boxes_separated(a, b):
    a, b = np.array(a.bounding_box()).reshape(2, 3), np.array(b.bounding_box()).reshape(2, 3)
    return bool(np.any(a[1] < b[0]) or np.any(b[1] < a[0]))


def overlap(a, b):
    if boxes_separated(a, b):
        return 0.0
    intersection = a ^ b
    if intersection.status() != m.Error.NoError:
        raise ValueError(f"Intersection failed: {intersection.status()}")
    return max(0.0, float(intersection.volume()))


def audit(manifest_path):
    config = json.loads(manifest_path.read_text())
    if config.get("units") != "mm":
        raise ValueError("Manifest units must explicitly be mm")
    parts = config.get("parts")
    if not isinstance(parts, dict) or not parts:
        raise ValueError("parts must be a non-empty mapping of names to STL paths")
    tolerance = float(config.get("overlap_tolerance_mm3", 0.0001))
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("overlap_tolerance_mm3 must be finite and nonnegative")
    report = {"units": "mm", "parts": {}, "assembled_pairs": [], "withdrawals": [],
              "overlap_tolerance_mm3": tolerance, "passed": True,
              "scope": "Solid validity, original-position intersections and sampled straight withdrawal only",
              "limitations": ["No continuous collision guarantee", "No wall-thickness check", "No physical fit validation"]}
    solids = {}
    for name, relative_path in parts.items():
        solid, info = load_solid(manifest_path.parent / relative_path)
        solids[name], report["parts"][name] = solid, info
    for a, b in itertools.combinations(solids, 2):
        vol = overlap(solids[a], solids[b])
        report["assembled_pairs"].append({"parts": [a, b], "overlap_mm3": vol})
        if vol > tolerance:
            report["passed"] = False
    order = config.get("assembly_order")
    if not isinstance(order, list) or len(order) != len(parts) - 1:
        raise ValueError("assembly_order must describe exactly N-1 withdrawals, leaving one base part")
    remaining = set(solids)
    for step in order:
        name = step["moving"]
        if name not in remaining:
            raise ValueError(f"Unknown or already removed moving part: {name}")
        against = step["against"]
        if not isinstance(against, list) or set(against) != remaining - {name} or len(set(against)) != len(against):
            raise ValueError(f"{name}: against must list every other part still in the assembly")
        direction = np.array(step["direction"], dtype=float)
        if direction.shape != (3,) or not np.isfinite(direction).all() or np.linalg.norm(direction) == 0:
            raise ValueError(f"{name}: direction must be a finite nonzero 3-vector")
        direction /= np.linalg.norm(direction)
        distance, samples = float(step["distance_mm"]), step.get("samples", 61)
        if not np.isfinite(distance) or distance <= 0 or type(samples) is not int or not 2 <= samples <= 10001:
            raise ValueError(f"{name}: positive finite distance and 2..10001 integer samples required")
        sampled = []
        for distance_t in np.linspace(0, distance, samples):
            moved = solids[name].translate((direction * distance_t).tolist())
            sampled.append({"distance_mm": float(distance_t), "overlap_mm3": {
                other: overlap(moved, solids[other]) for other in against}})
        end = solids[name].translate((direction * distance).tolist())
        end_clear = all(boxes_separated(end, solids[other]) for other in against)
        max_volume = max((v for s in sampled for v in s["overlap_mm3"].values()), default=0.0)
        passed = max_volume <= tolerance and end_clear
        report["withdrawals"].append({"moving": name, "against": against,
            "direction": direction.tolist(), "distance_mm": distance,
            "step_mm": distance / (samples - 1), "samples": sampled,
            "max_overlap_mm3": max_volume, "end_boxes_separated": end_clear, "passed": passed})
        report["passed"] &= passed
        remaining.remove(name)
    report["remaining_base"] = sorted(remaining)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; use a new filename to preserve previous evidence")
    try:
        report = audit(args.manifest.resolve())
        code = 0 if report["passed"] else 1
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        report, code = {"passed": False, "input_error": str(exc)}, 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(report, out, indent=2, ensure_ascii=False, allow_nan=False)
        out.write("\n")
    print(json.dumps({"passed": report["passed"], "report": str(args.output), "exit_code": code}))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
