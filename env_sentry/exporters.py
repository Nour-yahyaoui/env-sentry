"""
Export a .env file into the format the next tool wants.

Everything is generated locally with the standard library only, and every
format supports ``redact=True`` so a "safe preview" is one flag away.
"""

from __future__ import annotations

import base64
import json
from typing import Dict, Iterable, List, Optional, Sequence

from .envfile import EnvFile
from .redact import mask_value

FORMATS = ("dotenv", "json", "yaml", "shell", "tfvars", "ini", "compose", "k8s", "csv")


def _select(values: Dict[str, str], include: Sequence[str] = (), exclude: Sequence[str] = (),
            prefix: str = "") -> Dict[str, str]:
    from fnmatch import fnmatch

    chosen: Dict[str, str] = {}
    for key, value in values.items():
        if include and not any(fnmatch(key, pattern) for pattern in include):
            continue
        if exclude and any(fnmatch(key, pattern) for pattern in exclude):
            continue
        chosen[f"{prefix}{key}"] = value
    return chosen


def _escaped(value: str, quote: str = '"') -> str:
    escaped = value.replace("\\", "\\\\").replace(quote, "\\" + quote)
    return escaped.replace("\n", "\\n").replace("\r", "\\r")


def to_json(values: Dict[str, str], indent: int = 2) -> str:
    return json.dumps(values, indent=indent, ensure_ascii=False) + "\n"


def to_yaml(values: Dict[str, str]) -> str:
    lines = []
    for key, value in values.items():
        if value == "" or any(ch in value for ch in ":#{}[]&*!|>'\"%@`") or value.strip() != value:
            lines.append(f'{key}: "{_escaped(value)}"')
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"


def to_shell(values: Dict[str, str], command: str = "export") -> str:
    lines = [f'{command} {key}="{_escaped(value)}"' for key, value in values.items()]
    return "\n".join(lines) + "\n"


def to_envfile(values: Dict[str, str]) -> str:
    lines = []
    for key, value in values.items():
        if value == "" or any(ch.isspace() for ch in value) or "#" in value:
            lines.append(f'{key}="{_escaped(value)}"')
        else:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def to_tfvars(values: Dict[str, str]) -> str:
    return "\n".join(f'{key} = "{_escaped(value)}"' for key, value in values.items()) + "\n"


def to_ini(values: Dict[str, str], section: str = "settings") -> str:
    body = "\n".join(f"{key} = {value}" for key, value in values.items())
    return f"[{section}]\n{body}\n"


def to_compose(values: Dict[str, str], service: str = "app") -> str:
    lines = ["services:", f"  {service}:", "    environment:"]
    lines += [f'      - {key}={_escaped(value)}' for key, value in values.items()]
    return "\n".join(lines) + "\n"


def to_k8s(values: Dict[str, str], name: str = "app-secrets",
           namespace: str = "default") -> str:
    lines = [
        "apiVersion: v1",
        "kind: Secret",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {namespace}",
        "type: Opaque",
        "data:",
    ]
    for key, value in values.items():
        encoded = base64.b64encode(value.encode()).decode()
        lines.append(f"  {key}: {encoded}")
    return "\n".join(lines) + "\n"


def to_csv(values: Dict[str, str]) -> str:
    import csv as _csv

    import io

    buffer = io.StringIO()
    writer = _csv.writer(buffer)
    writer.writerow(["KEY", "VALUE"])
    for key, value in values.items():
        writer.writerow([key, value])
    return buffer.getvalue()


def export_env(
    env: EnvFile,
    fmt: str = "dotenv",
    redact: bool = False,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    prefix: str = "",
    visible: int = 4,
    name: str = "app-secrets",
    namespace: str = "default",
    service: str = "app",
    section: str = "settings",
) -> str:
    """Render ``env`` in ``fmt``. Unknown formats raise ValueError."""
    values = _select(env.values(), include, exclude, prefix)
    if redact:
        values = {key: mask_value(value, visible) for key, value in values.items()}

    if fmt == "dotenv":
        return to_envfile(values)
    if fmt == "json":
        return to_json(values)
    if fmt == "yaml":
        return to_yaml(values)
    if fmt == "shell":
        return to_shell(values)
    if fmt == "tfvars":
        return to_tfvars(values)
    if fmt == "ini":
        return to_ini(values, section=section)
    if fmt == "compose":
        return to_compose(values, service=service)
    if fmt == "k8s":
        return to_k8s(values, name=name, namespace=namespace)
    if fmt == "csv":
        return to_csv(values)
    raise ValueError(f"unknown export format: {fmt}")
