#!/usr/bin/env python3
"""Select an installed local Ollama profile; dry run unless --apply is supplied.

Run from the repository root using its isolated Python environment and PyYAML,
or use the existing helper image (host networking reaches local Ollama):

  docker run --rm --user 1000:1000 --network host -v "$PWD:/workspace" \
    --entrypoint /opt/venv/bin/python jarvis-command-center:hud \
    /workspace/deploy/select_ollama_profile.py SELECTED_LOCAL_MODEL:TAG

Append --apply only after reviewing the real benchmark. The only changed
parsed values are model.default in the two existing runtime configurations.
Both originals are backed up beside their files before any replacement. YAML
formatting/comments may be rewritten by PyYAML. No service is restarted.
"""
import argparse
import copy
import datetime
import decimal
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.request
import uuid

import yaml

CONFIGS = (Path(".runtime/hermes/config.yaml"), Path(".runtime/hermes-ceo/config.yaml"))
LOCAL_BASE_URL = "http://ollama-models:11434/v1"
OLLAMA_API = "http://127.0.0.1:11434"
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*:[A-Za-z0-9._-]+\Z")


class ProfileError(Exception):
    """A safe operator-facing error that never includes configuration contents."""


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise ProfileError("Unexpected redirect from local Ollama")


def ollama_json(path, body=None):
    request = urllib.request.Request(
        OLLAMA_API + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    # Ignore proxy environment settings and refuse redirects outside loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), RejectRedirects())
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ProfileError("Local Ollama inspection response is unexpectedly large")
        value = json.loads(raw)
    except urllib.error.HTTPError as error:
        raise ProfileError("Local Ollama inspection failed (HTTP " + str(error.code) + ")") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProfileError("Cannot inspect the local Ollama installation") from None
    except (ValueError, UnicodeError):
        raise ProfileError("Local Ollama returned invalid inspection data") from None
    if not isinstance(value, dict):
        raise ProfileError("Local Ollama returned an unexpected inspection structure")
    return value


def validate_model(model, fetch=ollama_json):
    if not isinstance(model, str) or not MODEL_NAME.fullmatch(model):
        raise ProfileError("Select an explicit installed local model alias including its tag")
    tags = fetch("/api/tags").get("models")
    if not isinstance(tags, list):
        raise ProfileError("Local Ollama returned an unexpected model inventory")
    installed = next((entry for entry in tags if isinstance(entry, dict) and entry.get("name") == model), None)
    if installed is None:
        raise ProfileError("The selected alias is not already installed; no models were pulled")
    shown = fetch("/api/show", {"model": model, "verbose": False})
    if any(record.get(key) for record in (installed, shown) for key in ("remote_host", "remote_model")):
        raise ProfileError("The selected model is remote; a local alias is required")
    details = shown.get("details")
    info = shown.get("model_info")
    if (not isinstance(details, dict) or details.get("format") != "gguf" or
            not isinstance(info, dict) or not isinstance(info.get("general.parameter_count"), (int, float)) or
            isinstance(info.get("general.parameter_count"), bool) or info["general.parameter_count"] <= 0 or
            not isinstance(installed.get("size"), int) or isinstance(installed.get("size"), bool) or installed["size"] <= 0):
        raise ProfileError("The selected alias does not identify installed local model weights")
    capabilities = shown.get("capabilities")
    if not isinstance(capabilities, list) or not {"tools", "completion"}.issubset(capabilities):
        raise ProfileError("The selected local alias must support tools and completion")
    parameters = shown.get("parameters")
    if not isinstance(parameters, str):
        raise ProfileError("The selected alias has no explicit context/temperature profile")
    values = {}
    for name in ("num_ctx", "temperature"):
        matches = re.findall(r"(?m)^\s*" + name + r"\s+(\S+)\s*$", parameters)
        if len(matches) != 1:
            raise ProfileError("The selected alias must explicitly set num_ctx and temperature once")
        values[name] = matches[0]
    try:
        valid = int(values["num_ctx"]) == 65536 and decimal.Decimal(values["temperature"]) == decimal.Decimal("0.1")
    except (ValueError, decimal.InvalidOperation):
        valid = False
    if not valid:
        raise ProfileError("The selected alias must use num_ctx=65536 and temperature=0.1")


def snapshot(root, relative):
    path = root / relative
    current = root
    for part in relative.parts[:-1]:
        current /= part
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ProfileError("Runtime configuration directories must be real directories")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ProfileError("Runtime configurations must be regular files without links")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino):
            raise ProfileError("A runtime configuration changed while it was being inspected")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
    finally:
        os.close(fd)
    if len(raw) > 2 * 1024 * 1024:
        raise ProfileError("A runtime configuration is unexpectedly large")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        raise ProfileError("A runtime configuration is not valid safe YAML") from None
    if not isinstance(data, dict) or not isinstance(data.get("model"), dict):
        raise ProfileError("Runtime configurations must contain a model mapping")
    model = data["model"]
    if (not isinstance(model.get("default"), str) or not model["default"] or
            model.get("provider") != "custom" or model.get("base_url") != LOCAL_BASE_URL):
        raise ProfileError("Both runtimes must retain the fixed local custom provider and Ollama endpoint")
    if any(type(model.get(name)) is not int or model[name] != 65536 for name in ("context_length", "ollama_num_ctx")):
        raise ProfileError("Both runtimes must already use the 65536-token local context configuration")
    return {"path": path, "relative": relative, "stat": info, "raw": raw, "data": data}


def unchanged(root, saved):
    current = snapshot(root, saved["relative"])
    old, new = saved["stat"], current["stat"]
    if (old.st_dev, old.st_ino, old.st_mtime_ns, old.st_mode, old.st_uid, old.st_gid, saved["raw"]) != (
            new.st_dev, new.st_ino, new.st_mtime_ns, new.st_mode, new.st_uid, new.st_gid, current["raw"]):
        raise ProfileError("A runtime configuration changed; inspect it and retry")


def set_metadata(fd, info):
    os.fchown(fd, info.st_uid, info.st_gid)
    os.fchmod(fd, stat.S_IMODE(info.st_mode))


def backup(saved, suffix):
    path = saved["path"].with_name(saved["path"].name + ".jarvis-profile-backup." + suffix)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        set_metadata(fd, saved["stat"])
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(saved["raw"])
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    return path


def atomic_write(saved, payload):
    path = saved["path"]
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".jarvis-profile.", dir=path.parent)
    try:
        set_metadata(fd, saved["stat"])
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def select_profile(root, model, apply=False, fetch=ollama_json):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ProfileError("The repository root must be a real directory")
    root = root.resolve(strict=True)
    saved = [snapshot(root, relative) for relative in CONFIGS]
    validate_model(model, fetch=fetch)
    changes = []
    for item in saved:
        if item["data"]["model"]["default"] == model:
            continue
        updated = copy.deepcopy(item["data"])
        # A YAML anchor may share this mapping with an unrelated config path.
        updated["model"] = dict(updated["model"])
        updated["model"]["default"] = model
        try:
            payload = yaml.safe_dump(updated, sort_keys=False, allow_unicode=True).encode()
            if yaml.safe_load(payload) != updated:
                raise ProfileError("A runtime configuration cannot be preserved by safe YAML serialization")
        except (yaml.YAMLError, ValueError, RecursionError):
            raise ProfileError("A runtime configuration cannot be safely serialized") from None
        changes.append((item, payload))
    report = {"selected_model": model, "changed_fields": [str(item["relative"]) + ":model.default" for item, _ in changes]}
    if not apply or not changes:
        return report
    # Inspect both again and create both backups before replacing either file.
    for item in saved:
        unchanged(root, item)
    suffix = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex
    for item in saved:
        backup(item, suffix)
    for item in saved:
        unchanged(root, item)
    try:
        for item, payload in changes:
            atomic_write(item, payload)
    except Exception:
        rollback_failed = False
        # Restore both, including a replacement that failed only after rename.
        for item in reversed(saved):
            try:
                atomic_write(item, item["raw"])
            except Exception:
                rollback_failed = True
        if rollback_failed:
            raise ProfileError("Profile selection failed and rollback was incomplete; restore both saved backup files before continuing") from None
        raise ProfileError("Profile selection failed; original runtime configurations were restored") from None
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model", help="Already installed local tool-capable alias with explicit tag")
    parser.add_argument("--apply", action="store_true", help="Back up and atomically update only both model.default values")
    args = parser.parse_args()
    try:
        result = select_profile(Path(__file__).resolve().parents[1], args.model, apply=args.apply)
    except ProfileError as error:
        print("Profile selection refused: " + str(error), file=sys.stderr)
        return 1
    except (OSError, UnicodeError):
        print("Profile selection refused: runtime files could not be safely read or written", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
