"""Publish validated cache generations without touching the web checkout or process."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path


PUBLICATION_DIR = Path("work/live-cache")
GROUPS = {
    "Material": (
        "data/page_data_cache.json",
        "data/request_form_cache.json",
        "assets/gift_projects",
        "assets/request_categories",
    ),
    "Contacts": ("data/contact_departments_cache.json",),
    "Warehouse": ("data/warehouse_location_cache.json", "assets/warehouse_locations"),
}


def _signature(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
        return str(path), stat.st_mtime_ns, stat.st_size
    except FileNotFoundError:
        return str(path), 0, 0


@lru_cache(maxsize=128)
def _read_json(path: str, modified: int, size: int) -> dict:
    del modified, size
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Cache must be a JSON object: {path}")
    return value


def read_json(path: Path) -> dict:
    return _read_json(*_signature(path))


@lru_cache(maxsize=16)
def _version(path: str, modified: int, size: int) -> str:
    del modified, size
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)', Path(path).read_text(encoding="utf-8-sig"), re.M)
    if not match:
        raise ValueError("Application version is missing.")
    return match.group(1)


def app_version(root: Path) -> str:
    return _version(*_signature(root / "app.py"))


def read_manifest(root: Path) -> dict:
    path = root / PUBLICATION_DIR / "current.json"
    if not path.exists():
        return {}
    value = read_json(path)
    if value.get("schema_version") != 1 or not isinstance(value.get("groups"), dict):
        raise ValueError("Unsupported live cache publication.")
    return value


def resolve_cache_path(root: Path, relative: str, manifest: dict | None = None) -> Path:
    root = root.resolve()
    original = (root / relative).resolve()
    if root not in original.parents:
        raise ValueError("Cache path must stay inside the application directory.")
    relative = original.relative_to(root).as_posix()
    group = next((key for key, paths in GROUPS.items()
                  if any(relative == prefix or relative.startswith(prefix + "/") for prefix in paths)), None)
    if group is None:
        return original
    manifest = read_manifest(root) if manifest is None else manifest
    entry = manifest.get("groups", {}).get(group)
    if not entry or entry.get("version") != app_version(root):
        return original
    # A subsequent code/cache deployment always wins over an older publication.
    baseline = root / GROUPS[group][0]
    if baseline.exists() and str(read_json(baseline).get("generated_at", "")) > entry["generated_at"]:
        return original
    generation = str(entry["generation"])
    if not re.fullmatch(r"[0-9a-f]{32}", generation):
        raise ValueError("Invalid live cache generation.")
    candidate = (root / PUBLICATION_DIR / generation / relative).resolve()
    if (root / PUBLICATION_DIR).resolve() not in candidate.parents:
        raise ValueError("Live cache path escaped publication directory.")
    return candidate


def _digest(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def _copy_group(source: Path, destination: Path, group: str, *, freshly_generated: bool = False) -> dict[str, str]:
    hashes = {}
    for relative in GROUPS[group]:
        path = source / relative
        if not path.exists():
            raise ValueError(f"Required cache path is missing: {relative}")
        paths = [path] if path.is_file() else sorted(path.rglob("*"))
        (destination / relative).parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            (destination / relative).mkdir(parents=True, exist_ok=True)
        for item in paths:
            if item.is_dir():
                continue
            if source.resolve() not in item.resolve().parents:
                raise ValueError("Source cache contains a path outside the project.")
            name = item.relative_to(source).as_posix()
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)
            if freshly_generated and relative.startswith("data/"):
                # preserve_unchanged_cache_files restores the committed timestamp
                # but writes the file again after this refresh. Keep that actual
                # observation time in the live copy so stale in-memory rows lose.
                data = read_json(target).copy()
                observed = datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                if not data.get("generated_at"):
                    raise ValueError(f"Cache generation time is missing: {relative}")
                data["built_from"] = data["generated_at"]
                data["generated_at"] = max(str(data["generated_at"]), observed)
                target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    return hashes


def validate_generation(root: Path, groups: tuple[str, ...]) -> None:
    # Reuse the production validators against the copied files, not the source.
    import app
    from scripts.validate_page_data_cache import validate_page_data_cache
    from scripts.validate_warehouse_location_cache import validate_warehouse_location_cache

    for group in groups:
        cache = read_json(root / GROUPS[group][0])
        if not cache.get("generated_at"):
            raise ValueError(f"Cache generation time is missing: {group}")
        if group == "Material":
            validate_page_data_cache(cache, require_data=True, require_cached_gift_images=True, cache_root=root)
            app.validate_request_form_cache(read_json(root / GROUPS[group][1]), require_data=True)
        elif group == "Warehouse":
            validate_warehouse_location_cache(cache, cache_root=root, require_data=True)
        else:
            if not isinstance(cache.get("departments"), list) or not cache["departments"]:
                raise ValueError("Contact cache contains no departments.")
            if not isinstance(cache.get("users"), list) or len(cache["users"]) != int(cache.get("user_count", -1)):
                raise ValueError("Contact cache user count is invalid.")
            if len(cache["departments"]) != int(cache.get("row_count", -1)):
                raise ValueError("Contact cache department count is invalid.")


def publish_cache(source: Path, target: Path, groups: tuple[str, ...], *, freshly_generated: bool = False) -> dict:
    """Caller holds the shared Windows cache mutex across generation/publication."""
    source, target = source.resolve(), target.resolve()
    if not groups or any(group not in GROUPS for group in groups):
        raise ValueError("Unknown cache scope.")
    version = app_version(source)
    if version != app_version(target) or not (target / "live_cache.py").is_file():
        raise ValueError("正式网页版本与本地程序不一致，请先完成版本发布，再刷新缓存。")
    current = read_manifest(target)
    generation = uuid.uuid4().hex
    directory = target / PUBLICATION_DIR / generation
    directory.mkdir(parents=True)
    entries = dict(current.get("groups", {}))
    changed = []
    for group in groups:
        hashes = _copy_group(source, directory, group, freshly_generated=freshly_generated)
        generated = str(read_json(directory / GROUPS[group][0]).get("generated_at", ""))
        existing_path = resolve_cache_path(target, GROUPS[group][0], current)
        if existing_path.exists() and str(read_json(existing_path).get("generated_at", "")) > generated:
            raise ValueError(f"拒绝用较旧缓存覆盖正式应用：{group}")
        digest = _digest(hashes)
        old = entries.get(group, {})
        if old.get("digest") == digest and old.get("version") == version:
            continue
        entries[group] = {"generation": generation, "version": version, "digest": digest,
                          "generated_at": generated, "files": hashes}
        changed.append(group)
    validate_generation(directory, groups)
    if not changed:
        # This directory is this invocation's unpublished UUID, never a live one.
        resolved_stage = directory.resolve()
        if resolved_stage.parent != (target / PUBLICATION_DIR).resolve() or resolved_stage.name != generation:
            raise RuntimeError("Invalid staging directory.")
        shutil.rmtree(resolved_stage)
        return {"changed": False, "revision": current.get("revision", ""), "groups": list(groups),
                "message": "正式应用已使用相同缓存，无需重复切换。"}
    # Publish one pointer only after every file and every requested scope validates.
    manifest = {"schema_version": 1, "revision": generation, "groups": entries,
                "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    pointer = target / PUBLICATION_DIR / "current.json"
    temporary = pointer.with_name(f"current-{generation}.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, pointer)
    if read_manifest(target) != manifest:
        raise RuntimeError("正式应用缓存发布回读不一致。")
    for group in changed:
        for relative, expected in entries[group]["files"].items():
            if hashlib.sha256(resolve_cache_path(target, relative, manifest).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"正式应用缓存文件回读不一致：{relative}")
    return {"changed": True, "revision": generation, "groups": changed,
            "published_at": manifest["published_at"],
            "message": "已同步并校验正式应用缓存，无需重启；打开的页面将在 5 秒内提示更新。"}
