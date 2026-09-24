"""M2.5 self-tests: task-type loading, lookup, raw-export validation.

Run: python -m rh_pool.selftest_m25
Validation uses the real archived exports under config/workflows; malformed
configs are exercised through temp files (RH_TASK_TYPES override).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from rh_pool import workflow_def as wd  # noqa: E402


def check(name, cond):
    if not cond:
        raise AssertionError(f"FAILED: {name}")
    print(f"ok - {name}")


def write_tmp(data) -> str:
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, f, ensure_ascii=False)
    f.close()
    return f.name


def main():
    # Real unified config
    types = wd.load_task_types()
    check("loads 3 types", len(types) == 3)

    vc = wd.get_task_type("voice-clone")
    check("voice-clone lookup", vc.workflowId == "1991003046928916481")
    check("param lookup", vc.param("referenceAudio").type == "audio")

    dh = wd.get_task_type("digital-human")
    check("digital-human lookup", dh.workflowId == "1968591880252469250")

    # Validation against archived exports
    r_vc = wd.validate_type(vc)
    check("voice-clone validates", r_vc.ok and not r_vc.errors)
    r_dh = wd.validate_type(dh)
    check("digital-human validates", r_dh.ok and not r_dh.errors)

    ig = wd.get_task_type("image-gen")
    r_ig = wd.validate_type(ig)
    check("image-gen ok w/ missing-export warning",
          r_ig.ok and any("not archived" in w for w in r_ig.warnings))

    # Error: unknown type id
    try:
        wd.get_task_type("nope")
        check("missing type raises", False)
    except wd.DefinitionError:
        check("missing type raises", True)

    # Malformed: bad schema version
    bad1 = write_tmp({"schemaVersion": "other", "types": []})
    os.environ["RH_TASK_TYPES"] = bad1
    try:
        try:
            wd.load_task_types()
            check("bad schema raises", False)
        except wd.DefinitionError:
            check("bad schema raises", True)
    finally:
        os.unlink(bad1)

    # Malformed: duplicate type ids
    bad2 = write_tmp({"schemaVersion": wd.SCHEMA_VERSION, "types": [
        {"typeId": "a", "workflowId": "w"},
        {"typeId": "a", "workflowId": "w"},
    ]})
    os.environ["RH_TASK_TYPES"] = bad2
    try:
        try:
            wd.load_task_types()
            check("duplicate ids raise", False)
        except wd.DefinitionError:
            check("duplicate ids raise", True)
    finally:
        os.unlink(bad2)

    # A type pointing at a real archived export but wrong node id -> validation error.
    # Reuse the digital-human export graph by referencing its workflow id but a
    # bogus node; load via temp config.
    bad3 = write_tmp({"schemaVersion": wd.SCHEMA_VERSION, "types": [
        {"typeId": "broken", "workflowId": "1968591880252469250",
         "params": [{"name": "x", "type": "text",
                     "nodeId": "999999", "fieldName": "text", "required": True}]},
    ]})
    os.environ["RH_TASK_TYPES"] = bad3
    try:
        broken = wd.get_task_type("broken")
        rep = wd.validate_type(broken)
        check("nonexistent node is validation error",
              not rep.ok and any("999999" in e for e in rep.errors))
    finally:
        os.unlink(bad3)
        os.environ.pop("RH_TASK_TYPES", None)

    # Default resolution restored (real config)
    check("real config restored", len(wd.load_task_types()) == 3)

    print("\nAll M2.5 self-tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
