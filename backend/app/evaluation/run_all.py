from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


EVALUATION_DIR = Path("data/evaluation")


def main() -> None:
    commands = build_commands()
    results = []
    for label, command, placeholder in commands:
        print(f"running {label} placeholder={placeholder}")
        completed = subprocess.run(command, check=False, text=True, capture_output=True)
        results.append(
            {
                "label": label,
                "placeholder_input": placeholder,
                "returncode": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
            }
        )
        status = "ok" if completed.returncode == 0 else "failed"
        print(f"{label}: {status}")
    output_path = EVALUATION_DIR / "run_all_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
    print(f"summary={output_path}")


def build_commands() -> list[tuple[str, list[str], bool]]:
    retrieval_questions, retrieval_placeholder = choose_file("questions.jsonl", "questions.sample.jsonl")
    qa_questions, qa_placeholder = choose_file("qa_questions.jsonl", "qa_questions.sample.jsonl")
    extension_cases, extension_placeholder = choose_file("extension_eval_cases.jsonl", "extension_eval_cases.jsonl")
    artifact_cases, artifact_placeholder = choose_file("artifact_eval_cases.jsonl", "artifact_eval_cases.jsonl")
    return [
        (
            "retrieval_eval",
            [
                sys.executable,
                "-m",
                "app.evaluation.retrieval_eval",
                "--questions",
                str(retrieval_questions),
                "--mode",
                "hybrid",
                "--top-k",
                "10",
            ],
            retrieval_placeholder,
        ),
        (
            "qa_eval",
            [
                sys.executable,
                "-m",
                "app.evaluation.qa_eval",
                "--questions",
                str(qa_questions),
                "--mode",
                "hybrid",
                "--top-k",
                "5",
            ],
            qa_placeholder,
        ),
        (
            "extension_eval",
            [
                sys.executable,
                "-m",
                "app.evaluation.extension_eval",
                "--cases",
                str(extension_cases),
                "--top-k",
                "5",
            ],
            extension_placeholder,
        ),
        (
            "artifact_eval",
            [
                sys.executable,
                "-m",
                "app.evaluation.artifact_eval",
                "--cases",
                str(artifact_cases),
            ],
            artifact_placeholder,
        ),
    ]


def choose_file(primary: str, fallback: str) -> tuple[Path, bool]:
    primary_path = EVALUATION_DIR / primary
    if primary_path.exists():
        return primary_path, False
    return EVALUATION_DIR / fallback, True


if __name__ == "__main__":
    main()
