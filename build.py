#!/usr/bin/env python3
"""Build the PowerPot firmware into a single deployable main.py.

Usage:
    python build.py

Output:
    dist/main.py - all non-project imports hoisted to the top (combined
    and de-duplicated), prefixed with a "# PowerPotFirmware <version> crc32=.."
    magic header on the first line. The body is protected by a CRC-32 and a
    closing marker; the OTA update server serves exactly this file, and the
    device verifies header + CRC before applying it.
"""

import ast
import json
import pathlib
import re
import sys
import zlib

ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "src"
CONFIG_PATH = ROOT / "config.json"
OUT_DIR = ROOT / "dist"
OUT_FILE = OUT_DIR / "main.py"
MAGIC = "# PowerPotFirmware"
MAGIC_END = "# EndPowerPotFirmware"
PROJECT_PREFIX = "src"

MERGE_ORDER = [
    "lib/enum/log_type.py",
    "lib/enum/operation_mode.py",
    "lib/enum/operation_state.py",
    "lib/config_util.py",
    "lib/server_handler.py",
    "lib/powerpot_handler.py",
    "lib/rest_api_handler.py",
    "lib/ota_util.py",
    "main.py",
]


def load_version():
    with open(CONFIG_PATH, encoding="utf-8") as file:
        config = json.load(file)
    return config["ota"]["version"]


def _alias_text(alias):
    return f"{alias.name} as {alias.asname}" if alias.asname else alias.name


def split_file(path):
    with open(path, encoding="utf-8") as file:
        lines = file.readlines()
    tree = ast.parse("".join(lines))
    imports = []
    drop_lines = set()
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for lineno in range(node.lineno, (node.end_lineno or node.lineno) + 1):
            drop_lines.add(lineno)
        if isinstance(node, ast.Import):
            imports.append(("import", None, node.names))
        else:
            module = node.module or ""
            if node.level > 0 or module.startswith(PROJECT_PREFIX):
                continue
            imports.append(("from", module, node.names))
    kept = [line for lineno, line in enumerate(lines, start=1) if lineno not in drop_lines]
    return kept, imports


def collect_imports(imports):
    plain = []
    seen_plain = set()
    from_imports = {}
    for kind, module, names in imports:
        if kind == "import":
            text = "import " + ", ".join(_alias_text(alias) for alias in names)
            if text not in seen_plain:
                seen_plain.add(text)
                plain.append(text)
        else:
            entry = from_imports.setdefault(module, [])
            for alias in names:
                text = _alias_text(alias)
                if text not in entry:
                    entry.append(text)
    lines = list(plain)
    lines.extend(f"from {module} import " + ", ".join(module_imports)
                 for module, module_imports in from_imports.items())
    return lines


def module_exports(path):
    with open(path, encoding="utf-8") as file:
        tree = ast.parse(file.read())
    exports = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            exports.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    exports.add(target.id)
    return exports


def rewrite_merged_modules(source, merged_modules):
    for module, exports in merged_modules:
        for attr in exports:
            source = re.sub(rf"\b{module}\.{attr}\b", attr, source)
    return source


def build():
    version = load_version()
    all_imports = []
    body_parts = []
    merged_modules = []
    for relative in MERGE_ORDER:
        path = SRC / relative
        if not path.is_file():
            sys.exit(f"[build] Missing source file: {path}")
        kept, imports = split_file(path)
        all_imports.extend(imports)
        body_parts.append("".join(kept).rstrip() + "\n\n")
        merged_modules.append((pathlib.PurePath(relative).stem, module_exports(path)))

    hoisted = "\n".join(collect_imports(all_imports))
    body = rewrite_merged_modules(f"{hoisted}\n\n{''.join(body_parts)}", merged_modules)
    header_line = f"{MAGIC} {version}"
    content = body.rstrip() + "\n\n" + MAGIC_END + "\n"
    post_header = "\n" + content
    checksum = zlib.crc32(post_header.encode("utf-8"))
    source = header_line + f" crc32={checksum:08x}" + "\n\n" + content

    try:
        compile(source, str(OUT_FILE), "exec")
    except SyntaxError as error:
        sys.exit(f"[build] Merged source is not valid Python:\n{error}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as file:
        file.write(source)
    print(f"[build] Wrote {OUT_FILE} ({len(source)} bytes), "
          f"header: '{MAGIC} {version} crc32={checksum:08x}'")


if __name__ == "__main__":
    build()