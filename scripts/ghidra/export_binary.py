#!/usr/bin/env python3
"""Export a Ghidra-analyzed binary into the ExAIS ghidra-export v1 schema.

Run with the Python environment where pyghidra is installed. PyGhidra is used
as a standalone library so this script can sit in a larger research workflow
rather than requiring GUI automation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "exais.ghidra-export.v1"


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def address_text(address: Any) -> str | None:
    if address is None:
        return None
    text = str(address)
    try:
        int(text, 16)
    except ValueError:
        return text
    return f"0x{text.lower()}"


def function_id(function: Any) -> str:
    return address_text(function.getEntryPoint()) or str(function.getEntryPoint())


def java_iter(value: Any):
    iterator = value.iterator() if hasattr(value, "iterator") else value
    if hasattr(iterator, "hasNext"):
        while iterator.hasNext():
            yield iterator.next()
    else:
        yield from iterator


def safe_call(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def function_types(function: Any) -> list[str]:
    values: list[str] = []
    return_type = safe_call(lambda: function.getReturnType())
    if return_type is not None:
        values.append(str(return_type))
    parameters = safe_call(lambda: function.getParameters(), []) or []
    for parameter in parameters:
        datatype = safe_call(lambda parameter=parameter: parameter.getDataType())
        if datatype is not None:
            values.append(str(datatype))
    return sorted({value for value in values if value})


def collect_reference_evidence(program: Any, function: Any) -> dict[str, Any]:
    listing = program.getListing()
    reference_manager = program.getReferenceManager()
    function_manager = program.getFunctionManager()
    body = function.getBody()

    strings: dict[tuple[str | None, str], dict[str, Any]] = {}
    imports: set[str] = set()
    reads_globals: set[str] = set()
    writes_globals: set[str] = set()
    instruction_count = 0

    instructions = listing.getInstructions(body, True)
    for instruction in java_iter(instructions):
        instruction_count += 1
        from_address = instruction.getAddress()
        for reference in reference_manager.getReferencesFrom(from_address):
            to_address = reference.getToAddress()
            ref_type = reference.getReferenceType()

            target_function = function_manager.getFunctionAt(to_address)
            if target_function is not None and safe_call(lambda: target_function.isExternal(), False):
                full_name = safe_call(lambda: target_function.getName(True), None) or target_function.getName()
                imports.add(str(full_name))
                continue

            data = listing.getDataAt(to_address)
            if data is not None:
                value = safe_call(lambda: data.getValue())
                if value is not None:
                    datatype_name = str(safe_call(lambda: data.getDataType(), ""))
                    rendered = str(value)
                    if "string" in datatype_name.lower() or isinstance(value, str):
                        key = (address_text(to_address), rendered)
                        strings[key] = {"address": key[0], "value": rendered[:16384]}
                        continue

            if to_address is not None and safe_call(lambda: to_address.isMemoryAddress(), False):
                if safe_call(lambda: body.contains(to_address), False):
                    continue
                rendered = address_text(to_address) or str(to_address)
                if safe_call(lambda: ref_type.isRead(), False):
                    reads_globals.add(rendered)
                if safe_call(lambda: ref_type.isWrite(), False):
                    writes_globals.add(rendered)

    return {
        "instruction_count": instruction_count,
        "strings": list(strings.values()),
        "imports": sorted(imports),
        "reads_globals": sorted(reads_globals),
        "writes_globals": sorted(writes_globals),
    }


def export_program(program: Any, binary_path: Path, *, timeout_seconds: int) -> dict[str, Any]:
    from ghidra.app.decompiler import DecompInterface
    from ghidra.framework import Application
    from ghidra.util.task import TaskMonitor

    monitor = TaskMonitor.DUMMY
    decompiler = DecompInterface()
    decompiler.toggleCCode(True)
    decompiler.toggleSyntaxTree(True)
    if not decompiler.openProgram(program):
        raise RuntimeError(f"Ghidra decompiler could not open program: {decompiler.getLastMessage()}")

    function_manager = program.getFunctionManager()
    functions: list[dict[str, Any]] = []
    for function in java_iter(function_manager.getFunctions(True)):
        if safe_call(lambda: function.isExternal(), False):
            continue
        fid = function_id(function)
        callers = sorted(
            function_id(item)
            for item in (safe_call(lambda: function.getCallingFunctions(monitor), []) or [])
            if not safe_call(lambda item=item: item.isExternal(), False)
        )
        callees: list[str] = []
        direct_imports: set[str] = set()
        for item in (safe_call(lambda: function.getCalledFunctions(monitor), []) or []):
            if safe_call(lambda item=item: item.isExternal(), False):
                direct_imports.add(str(safe_call(lambda item=item: item.getName(True), item.getName())))
            else:
                callees.append(function_id(item))

        evidence = collect_reference_evidence(program, function)
        evidence["imports"] = sorted(set(evidence["imports"]) | direct_imports)

        decompilation = None
        decompile_error = None
        try:
            result = decompiler.decompileFunction(function, timeout_seconds, monitor)
            if result is not None and result.decompileCompleted():
                decompiled = result.getDecompiledFunction()
                if decompiled is not None:
                    decompilation = str(decompiled.getC())
            else:
                decompile_error = str(result.getErrorMessage() if result is not None else "no result")[:4096]
        except Exception as exc:
            decompile_error = f"{type(exc).__name__}: {exc}"[:4096]

        namespace = safe_call(lambda: function.getParentNamespace().getName(True))
        signature = safe_call(lambda: function.getSignature().getPrototypeString())
        if signature is None:
            signature = safe_call(lambda: str(function.getSignature()))
        calling_convention = safe_call(lambda: function.getCallingConventionName())
        body_size = int(safe_call(lambda: function.getBody().getNumAddresses(), 0) or 0)

        record = {
            "id": fid,
            "name": str(function.getName()),
            "address": fid,
            "namespace": str(namespace) if namespace else None,
            "signature": str(signature) if signature else None,
            "calling_convention": str(calling_convention) if calling_convention else None,
            "size": body_size,
            "instruction_count": int(evidence["instruction_count"]),
            "callers": callers,
            "callees": sorted(set(callees)),
            "strings": evidence["strings"],
            "imports": evidence["imports"],
            "reads_globals": evidence["reads_globals"],
            "writes_globals": evidence["writes_globals"],
            "types": function_types(function),
            "decompilation": decompilation,
            "decompilation_sha256": sha256(decompilation.encode("utf-8")).hexdigest() if decompilation else None,
            "decompile_error": decompile_error,
        }
        functions.append(record)

    decompiler.dispose()
    memory = program.getMemory()
    compiler_spec = safe_call(lambda: program.getCompilerSpec())
    return {
        "schema_version": SCHEMA_VERSION,
        "ghidra_version": str(Application.getApplicationVersion()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "binary": {
            "name": binary_path.name,
            "sha256": file_sha256(binary_path),
            "size_bytes": binary_path.stat().st_size,
            "path": str(binary_path.resolve()),
            "executable_format": str(safe_call(lambda: program.getExecutableFormat(), "")) or None,
            "language_id": str(safe_call(lambda: program.getLanguageID(), "")) or None,
            "compiler_spec_id": str(safe_call(lambda: compiler_spec.getCompilerSpecID(), "")) if compiler_spec else None,
            "image_base": address_text(safe_call(lambda: program.getImageBase())),
            "min_address": address_text(safe_call(lambda: memory.getMinAddress())),
            "max_address": address_text(safe_call(lambda: memory.getMaxAddress())),
        },
        "functions": functions,
        "metadata": {
            "function_count": len(functions),
            "analysis_engine": "Ghidra/PyGhidra",
            "exporter": "exais scripts/ghidra/export_binary.py",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a binary with PyGhidra and export EXAIS records")
    parser.add_argument("binary", type=Path)
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument("--ghidra-install-dir", type=Path, default=None)
    parser.add_argument("--project-dir", type=Path, default=None)
    parser.add_argument("--project-name", default="exais-binary-research")
    parser.add_argument("--decompile-timeout", type=int, default=60)
    args = parser.parse_args()

    if not args.binary.is_file():
        parser.error(f"binary does not exist: {args.binary}")
    if args.decompile_timeout < 1 or args.decompile_timeout > 600:
        parser.error("--decompile-timeout must be 1..600 seconds")

    import pyghidra

    if args.ghidra_install_dir:
        pyghidra.start(install_dir=args.ghidra_install_dir)

    # The compatibility open_program API remains supported by PyGhidra. Keeping
    # it isolated here makes migration to newer project/program context APIs
    # straightforward without changing the EXAIS export contract.
    kwargs: dict[str, Any] = {}
    if args.project_dir:
        kwargs["project_location"] = args.project_dir
        kwargs["project_name"] = args.project_name
    with pyghidra.open_program(args.binary, analyze=True, **kwargs) as flat_api:
        export = export_program(flat_api.getCurrentProgram(), args.binary, timeout_seconds=args.decompile_timeout)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(export, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "binary_sha256": export["binary"]["sha256"],
        "functions": len(export["functions"]),
        "ghidra_version": export["ghidra_version"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
