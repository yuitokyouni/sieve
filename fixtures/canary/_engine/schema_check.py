"""A dependency-free validator for the subset of JSON Schema the contract uses.

Why this exists: the three contract schemas are only worth something if
artifacts are actually checked against them, and the check has to run in the
same CI job as the canary. Adding `jsonschema` would mean touching
pyproject.toml and constraints.txt — the pinned reproduction environment that
the cross-machine seal job depends on — for a validator we need on three
hand-authored schemas. So the subset is implemented here instead.

SUPPORTED, and nothing else: $ref (local, "#/$defs/..."), type, const, enum,
required, properties, additionalProperties (bool or schema), propertyNames,
items, minItems, minLength, minimum, maximum, exclusiveMinimum, pattern,
allOf, anyOf, oneOf, if/then/else.

DELIBERATELY IGNORED: format, unevaluatedProperties, $dynamicRef, dependent*,
patternProperties, contains, uniqueItems. The contract schemas are written to
stay inside the supported set; `test_schema_subset_is_sufficient` fails if a
schema ever introduces a keyword this validator would silently skip, so the
gap between "validated" and "claimed validated" cannot open quietly.
"""

from __future__ import annotations

import json
import re
from typing import Any

SUPPORTED = {
    "$schema", "$id", "$defs", "$ref", "title", "description", "default",
    "type", "const", "enum", "required", "properties", "additionalProperties",
    "propertyNames", "items", "minItems", "minLength", "minimum", "maximum",
    "exclusiveMinimum", "pattern", "allOf", "anyOf", "oneOf", "if", "then",
    "else", "format",
}
IGNORED_BY_DESIGN = {"format"}

_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "null": type(None),
}


def _is_type(value: Any, name: str) -> bool:
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def unsupported_keywords(schema: Any) -> set[str]:
    """Every keyword in `schema` this validator does not implement."""
    found: set[str] = set()
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key in ("properties", "$defs"):
                for sub in value.values():
                    found |= unsupported_keywords(sub)
                continue
            if key not in SUPPORTED:
                found.add(key)
            found |= unsupported_keywords(value)
    elif isinstance(schema, list):
        for item in schema:
            found |= unsupported_keywords(item)
    return found


class Validator:
    def __init__(self, schema: dict) -> None:
        self.root = schema

    def _resolve(self, schema: dict) -> dict:
        while "$ref" in schema:
            ref = schema["$ref"]
            if not ref.startswith("#/"):
                raise ValueError(f"only local refs are supported: {ref}")
            node: Any = self.root
            for part in ref[2:].split("/"):
                node = node[part]
            merged = {k: v for k, v in schema.items() if k != "$ref"}
            schema = {**node, **merged}
        return schema

    def errors(self, value: Any, schema: dict | None = None,
               path: str = "$") -> list[str]:
        schema = self._resolve(self.root if schema is None else schema)
        out: list[str] = []

        if "type" in schema:
            names = schema["type"]
            names = names if isinstance(names, list) else [names]
            if not any(_is_type(value, n) for n in names):
                out.append(f"{path}: expected type {names}, got "
                           f"{type(value).__name__}")
                return out
        if "const" in schema and value != schema["const"]:
            out.append(f"{path}: expected const {schema['const']!r}, "
                       f"got {value!r}")
        if "enum" in schema and value not in schema["enum"]:
            out.append(f"{path}: {value!r} not in {schema['enum']!r}")
        if isinstance(value, str):
            if "minLength" in schema and len(value) < schema["minLength"]:
                out.append(f"{path}: shorter than {schema['minLength']}")
            if "pattern" in schema and not re.search(schema["pattern"], value):
                out.append(f"{path}: {value!r} does not match "
                           f"{schema['pattern']!r}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                out.append(f"{path}: {value} < minimum {schema['minimum']}")
            if "maximum" in schema and value > schema["maximum"]:
                out.append(f"{path}: {value} > maximum {schema['maximum']}")
            if ("exclusiveMinimum" in schema
                    and value <= schema["exclusiveMinimum"]):
                out.append(f"{path}: {value} <= exclusiveMinimum "
                           f"{schema['exclusiveMinimum']}")
        if isinstance(value, dict):
            for key in schema.get("required", []):
                if key not in value:
                    out.append(f"{path}: missing required property {key!r}")
            props = schema.get("properties", {})
            for key, sub in value.items():
                if key in props:
                    out += self.errors(sub, props[key], f"{path}.{key}")
                else:
                    extra = schema.get("additionalProperties", True)
                    if extra is False:
                        out.append(f"{path}: additional property {key!r} "
                                   f"is not allowed")
                    elif isinstance(extra, dict):
                        out += self.errors(sub, extra, f"{path}.{key}")
                if "propertyNames" in schema:
                    out += self.errors(key, schema["propertyNames"],
                                       f"{path}.<key {key!r}>")
        if isinstance(value, list):
            if "minItems" in schema and len(value) < schema["minItems"]:
                out.append(f"{path}: fewer than {schema['minItems']} items")
            if "items" in schema:
                for i, item in enumerate(value):
                    out += self.errors(item, schema["items"], f"{path}[{i}]")
        for sub in schema.get("allOf", []):
            out += self.errors(value, sub, path)
        if "anyOf" in schema:
            if all(self.errors(value, sub, path) for sub in schema["anyOf"]):
                out.append(f"{path}: matched none of anyOf")
        if "oneOf" in schema:
            matched = [i for i, sub in enumerate(schema["oneOf"])
                       if not self.errors(value, sub, path)]
            if len(matched) != 1:
                out.append(f"{path}: matched {len(matched)} of "
                           f"{len(schema['oneOf'])} oneOf branches "
                           f"(exactly 1 required)")
        if "if" in schema:
            branch = "then" if not self.errors(value, schema["if"], path) else "else"
            if branch in schema:
                out += self.errors(value, schema[branch], path)
        return out


def validate(instance: Any, schema_path: str) -> list[str]:
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    unsupported = unsupported_keywords(schema) - IGNORED_BY_DESIGN
    if unsupported:
        raise ValueError(
            f"{schema_path} uses keywords this validator does not implement: "
            f"{sorted(unsupported)}. Either implement them or stop using them; "
            f"silently skipping them would mean claiming a check that is not "
            f"being made.")
    return Validator(schema).errors(instance)
