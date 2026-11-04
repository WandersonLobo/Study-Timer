"""A CI deve falhar quando a cobertura exigida não foi realmente executada."""

import binascii
import json
import runpy
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from tests.native_manifest import NATIVE_SCENARIOS

MODULE = runpy.run_path(str(Path(__file__).parents[1] / "packaging" / "ci_checks.py"))
validate = cast(Callable[[Path, str, str | None], int], MODULE["validate_junit"])
export = cast(Callable[[Path, Path], None], MODULE["export_artifacts"])


def report(path: Path, names: list[str], module: str = "tests.test_native_ui") -> ET.Element:
    root = ET.Element("testsuite")
    for name in names:
        ET.SubElement(root, "testcase", name=name, classname=module)
    ET.ElementTree(root).write(path, encoding="utf-8")
    return root


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_native_gate_requires_every_scenario_once(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "tests.xml"
    names = [f"test_native_scenario[{scenario}-{mode}]" for scenario in NATIVE_SCENARIOS]
    report(path, names)
    assert validate(path, "native", mode) == len(names)
    for incomplete in (
        names[:-1],
        names + names[:1],
        [],
        [n.replace(mode, "other") for n in names],
    ):
        report(path, incomplete)
        with pytest.raises(ValueError):
            validate(path, "native", mode)


@pytest.mark.parametrize("tag", ["skipped", "failure", "error"])
def test_gate_rejects_failure_or_skip_even_with_all_modules(tmp_path: Path, tag: str) -> None:
    path = tmp_path / "tests.xml"
    root = ET.Element("testsuite")
    for module in sorted(MODULE["QUALITY_MODULES"]):
        ET.SubElement(root, "testcase", name="test_rule", classname=module)
    ET.ElementTree(root).write(path, encoding="utf-8")
    assert validate(path, "quality", None) == len(MODULE["QUALITY_MODULES"])
    ET.SubElement(root[0], tag).text = "Falha controlada da proteção de CI."
    ET.ElementTree(root).write(path, encoding="utf-8")
    with pytest.raises(ValueError):
        validate(path, "quality", None)


def test_quality_gate_rejects_missing_critical_group(tmp_path: Path) -> None:
    path = tmp_path / "tests.xml"
    report(path, ["test_rule"], "tests.test_clock")
    with pytest.raises(ValueError):
        validate(path, "quality", None)


def test_smoke_gate_rejects_partial_matrix(tmp_path: Path) -> None:
    path = tmp_path / "tests.xml"
    names = sorted(MODULE["SMOKE_CASES"])
    report(path, names, "tests.test_build_smoke")
    assert validate(path, "smoke", None) == 6
    report(path, names[:-1], "tests.test_build_smoke")
    with pytest.raises(ValueError):
        validate(path, "smoke", None)


def test_build_gate_requires_each_external_flow_and_theme(tmp_path: Path) -> None:
    path = tmp_path / "tests.xml"
    root = report(path, sorted(MODULE["SMOKE_CASES"]), "tests.test_build_smoke")
    names = sorted(MODULE["DESKTOP_CASES"])
    for name in names[:-1]:
        ET.SubElement(root, "testcase", name=name, classname="tests.test_packaged_ui")
    ET.ElementTree(root).write(path, encoding="utf-8")
    with pytest.raises(ValueError):
        validate(path, "build", None)
    ET.SubElement(root, "testcase", name=names[-1], classname="tests.test_packaged_ui")
    ET.ElementTree(root).write(path, encoding="utf-8")
    assert validate(path, "build", None) == 10


def chunk(kind: bytes, content: bytes) -> bytes:
    return (
        len(content).to_bytes(4, "big")
        + kind
        + content
        + binascii.crc32(kind + content).to_bytes(4, "big")
    )


def test_public_artifacts_remove_private_content(tmp_path: Path) -> None:
    raw, public = tmp_path / "raw", tmp_path / "public"
    raw.mkdir()
    private = "C:/Users/Private/Estudo pessoal"
    root = report(raw / "tests.xml", [private, "test_rule[" + private + "]", "test_ok[light]"])
    root.set("hostname", private)
    ET.SubElement(root[0], "failure", message=private).text = private
    ET.SubElement(root, "system-out").text = private
    ET.ElementTree(root).write(raw / "tests.xml", encoding="utf-8")
    (raw / "environment.json").write_text(
        json.dumps(
            {
                "kind": "quality",
                "python": "3.12.10",
                "runner_image": private,
                "secret": private,
            }
        ),
        encoding="utf-8",
    )
    (raw / "estudos.db").write_text(private, encoding="utf-8")
    (raw / "studytimer.log").write_text(private, encoding="utf-8")
    image = b"\x89PNG\r\n\x1a\n" + chunk(b"tEXt", private.encode()) + chunk(b"IEND", b"")
    (raw / "window.png").write_bytes(image)
    export(raw, public)
    assert sorted(p.name for p in public.iterdir()) == [
        "environment.json",
        "tests.xml",
        "window.png",
    ]
    for file in public.iterdir():
        assert private.encode() not in file.read_bytes()
    assert b"test_ok[light]" in (public / "tests.xml").read_bytes()
    assert json.loads((public / "environment.json").read_text()) == {
        "kind": "quality",
        "python": "3.12.10",
    }


def test_public_artifacts_reject_overlapping_directories(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        export(tmp_path, tmp_path / "public")


@pytest.mark.parametrize("data", [b"private", b"\x89PNG\r\n\x1a\n"])
def test_public_artifacts_reject_invalid_capture(tmp_path: Path, data: bytes) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "window.png").write_bytes(data)
    with pytest.raises(ValueError):
        export(raw, tmp_path / "public")
