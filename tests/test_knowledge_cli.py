import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from camera_assistant.knowledge.cli import main


def cli_record() -> dict:
    return {
        "knowledge_id": "test-cli-composition",
        "library_id": "composition",
        "title": "[测试数据]构图",
        "kind": "guideline",
        "content": "仅供自动化测试的构图记录，不是正式知识。",
        "payload": {"test_marker": True, "facts": {"test_number": 100}},
        "source": {
            "name": "测试自制资料",
            "license": "测试自制资料",
            "retrieval_allowed": True,
        },
        "author": "测试整理员",
    }


def invoke(capsys: pytest.CaptureFixture, *args: str) -> tuple[int, dict]:
    code = main(list(args))
    captured = capsys.readouterr()
    assert not captured.err
    return code, json.loads(captured.out)


def test_cli_full_review_publish_and_search_flow(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    database = str(tmp_path / "knowledge.db")
    args = ("--db", database)
    path = tmp_path / "record.json"
    path.write_text(json.dumps(cli_record(), ensure_ascii=False), encoding="utf-8")
    code, result = invoke(capsys, *args, "init")
    assert code == 0 and result["ok"]
    assert len(result["data"]["libraries"]) == 6
    code, result = invoke(capsys, *args, "import", str(path))
    assert code == 0
    assert result["data"]["revisions"][0]["status"] == "draft"
    code, result = invoke(capsys, *args, "list", "--library", "composition", "--status", "draft")
    assert code == 0
    assert len(result["data"]) == 1
    code, result = invoke(capsys, *args, "search", "构图")
    assert code == 0 and result["data"] == []
    code, result = invoke(capsys, *args, "publish", "test-cli-composition")
    assert code == 1 and not result["ok"]
    assert invoke(capsys, *args, "submit", "test-cli-composition")[0] == 0
    code, result = invoke(
        capsys, *args, "approve", "test-cli-composition", "--reviewer", "测试审核员"
    )
    assert code == 0
    assert invoke(capsys, *args, "publish", "test-cli-composition")[0] == 0
    code, result = invoke(capsys, *args, "show", "test-cli-composition", "--version", "1")
    assert code == 0 and result["data"]["status"] == "published"
    code, result = invoke(capsys, *args, "search", "构图", "--library", "composition")
    assert code == 0 and len(result["data"]) == 1
    code, result = invoke(
        capsys,
        *args,
        "structured",
        "--library",
        "composition",
        "--filters",
        '{"facts.test_number":100}',
    )
    assert code == 0 and len(result["data"]) == 1
    assert invoke(capsys, *args, "audit")[1]["data"]
    assert invoke(capsys, *args, "retire", "test-cli-composition")[0] == 0
    assert invoke(capsys, *args, "search", "构图")[1]["data"] == []


def test_cli_dry_run_does_not_create_database_or_parent(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    database = tmp_path / "not-created" / "knowledge.db"
    path = tmp_path / "record.json"
    path.write_text(json.dumps(cli_record()), encoding="utf-8")

    code, result = invoke(capsys, "--db", str(database), "import", str(path), "--dry-run")

    assert code == 0
    assert result["data"]["validated_only"]
    assert not database.parent.exists()


@pytest.mark.parametrize(
    "command",
    [
        ["libraries"],
        ["stats"],
        ["list"],
        ["show", "test-unknown"],
        ["audit"],
        ["search", "构图"],
        ["structured", "--library", "equipment"],
    ],
)
def test_cli_read_only_commands_do_not_create_missing_database(
    tmp_path: Path, capsys: pytest.CaptureFixture, command: list[str]
) -> None:
    database = tmp_path / "missing.db"

    code, result = invoke(capsys, "--db", str(database), *command)

    assert code == 2
    assert not result["ok"]
    assert not database.exists()


def test_cli_invalid_records_return_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / "record.json"
    path.write_text('{"status":"published"}', encoding="utf-8")
    code, result = invoke(capsys, "import", str(path), "--dry-run")
    assert code == 1
    assert not result["ok"]
    assert result["data"]["errors"]


@pytest.mark.parametrize("filters", ["[]", "{", '{"x":1,"x":2}', '{"x":NaN}'])
def test_cli_rejects_invalid_json_filters(
    tmp_path: Path, capsys: pytest.CaptureFixture, filters: str
) -> None:
    database = str(tmp_path / "knowledge.db")
    invoke(capsys, "--db", database, "init")
    code, result = invoke(
        capsys, "--db", database, "structured", "--library", "equipment", "--filters", filters
    )
    assert code == 2
    assert not result["ok"]


def test_cli_usage_errors_are_json(capsys: pytest.CaptureFixture) -> None:
    code, result = invoke(capsys, "approve", "test-cli-composition")
    assert code == 2
    assert not result["ok"]


def test_cli_schema_needs_no_database(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    database = tmp_path / "not-created" / "knowledge.db"

    code, result = invoke(capsys, "--db", str(database), "schema")

    assert code == 0
    assert result["data"]["title"] == "KnowledgeRecord"
    assert result["data"]["additionalProperties"] is False
    assert not database.parent.exists()


def test_cli_stats_show_empty_libraries(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    database = str(tmp_path / "knowledge.db")
    invoke(capsys, "--db", database, "init")

    code, result = invoke(capsys, "--db", database, "stats")

    assert code == 0
    assert len(result["data"]) == 6
    assert all(count == 0 for statuses in result["data"].values() for count in statuses.values())


def test_cli_corrupt_database_returns_json_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    database = tmp_path / "corrupt.db"
    database.write_bytes(b"THIS_IS_NOT_A_SQLITE_DATABASE_PRIVATE_CONTENT")

    code, result = invoke(capsys, "--db", str(database), "list")

    assert code == 1
    assert not result["ok"]
    assert "数据库" in result["error"]
    assert "PRIVATE_CONTENT" not in result["error"]


def test_cli_structured_conditions_control_visibility(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    database = str(tmp_path / "knowledge.db")
    args = ("--db", database)
    data = cli_record()
    data["conditions"] = {"scene": ["test-scene"]}
    path = tmp_path / "record.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    invoke(capsys, *args, "import", str(path))
    invoke(capsys, *args, "submit", "test-cli-composition")
    invoke(capsys, *args, "approve", "test-cli-composition", "--reviewer", "测试审核员")
    invoke(capsys, *args, "publish", "test-cli-composition")

    code, result = invoke(capsys, *args, "structured", "--library", "composition")
    assert code == 0 and result["data"] == []
    code, result = invoke(
        capsys,
        *args,
        "structured",
        "--library",
        "composition",
        "--conditions",
        '{"scene":"test-scene"}',
    )
    assert code == 0 and len(result["data"]) == 1


def test_cli_subprocess_outputs_utf8_even_when_parent_requests_ascii(tmp_path: Path) -> None:
    database = tmp_path / "knowledge.db"
    task_env = os.environ.copy()
    task_env["PYTHONIOENCODING"] = "ascii"
    task_env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")

    result = subprocess.run(
        [sys.executable, "-m", "camera_assistant.knowledge", "--db", str(database), "init"],
        env=task_env,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout.decode("utf-8"))
    assert output["ok"]
    assert any(item["name"] == "构图知识库" for item in output["data"]["libraries"])


def test_cli_reject_requires_reason_and_independent_reviewer_then_returns_for_revision(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    database = str(tmp_path / "knowledge.db")
    args = ("--db", database)
    path = tmp_path / "record.json"
    path.write_text(json.dumps(cli_record()), encoding="utf-8")
    assert invoke(capsys, *args, "import", str(path))[0] == 0
    assert invoke(capsys, *args, "submit", "test-cli-composition")[0] == 0

    code, result = invoke(
        capsys, *args, "reject", "test-cli-composition", "--reviewer", "测试审核员"
    )
    assert code == 1 and not result["ok"]
    assert invoke(capsys, *args, "show", "test-cli-composition")[1]["data"]["status"] == (
        "pending_review"
    )
    code, result = invoke(
        capsys,
        *args,
        "reject",
        "test-cli-composition",
        "--reviewer",
        "测试整理员",
        "--note",
        "测试退回原因",
    )
    assert code == 1 and not result["ok"]
    assert invoke(capsys, *args, "show", "test-cli-composition")[1]["data"]["status"] == (
        "pending_review"
    )
    code, result = invoke(
        capsys,
        *args,
        "reject",
        "test-cli-composition",
        "--reviewer",
        "测试审核员",
        "--note",
        "测试退回原因",
        "--version",
        "1",
    )
    assert code == 0
    assert result["data"]["status"] == "needs_revision"
    assert result["data"]["reviewer"] == "测试审核员"
    assert result["data"]["review_note"] == "测试退回原因"
    assert invoke(capsys, *args, "publish", "test-cli-composition")[0] == 1
    assert invoke(capsys, *args, "submit", "test-cli-composition")[0] == 1

    updated = cli_record()
    updated["version"] = 2
    updated["content"] = "仅供自动化测试，按退回意见修订后的构图记录。"
    path.write_text(json.dumps(updated), encoding="utf-8")
    assert invoke(capsys, *args, "import", str(path))[0] == 0
    assert invoke(capsys, *args, "submit", "test-cli-composition", "--version", "2")[0] == 0
    assert (
        invoke(
            capsys,
            *args,
            "approve",
            "test-cli-composition",
            "--reviewer",
            "测试审核员",
            "--version",
            "2",
        )[0]
        == 0
    )
    assert invoke(capsys, *args, "publish", "test-cli-composition", "--version", "2")[0] == 0
    old = invoke(capsys, *args, "show", "test-cli-composition", "--version", "1")[1]
    assert old["data"]["status"] == "needs_revision"


def test_cli_reject_requires_reviewer_argument(capsys: pytest.CaptureFixture) -> None:
    code, result = invoke(capsys, "reject", "test-cli-composition", "--note", "测试退回原因")
    assert code == 2
    assert not result["ok"]
