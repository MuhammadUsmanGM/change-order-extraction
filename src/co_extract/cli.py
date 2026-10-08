"""Command Line Interface for Change-Order Extraction using Typer."""

import json
from pathlib import Path
from typing import Annotated

import typer

from co_extract.pipeline import run_pipeline

app = typer.Typer(
    name="co-extract",
    help="Change-Order Extraction Pipeline CLI: extract structured fields with validation and confidence.",
    add_completion=False,
)


@app.command(name="run")
def run_command(
    file: Annotated[
        Path,
        typer.Argument(
            help="Path to the document file (.pdf, .txt, .md) to extract.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            "-p",
            help="Extraction provider to use: 'claude', 'gemini', or 'both'.",
        ),
    ] = "claude",
    mock: Annotated[
        bool,
        typer.Option(
            "--mock/--no-mock",
            help="Run in offline mock mode using pre-recorded fixtures.",
        ),
    ] = False,
    record: Annotated[
        bool,
        typer.Option(
            "--record/--no-record",
            help="Record live provider outputs into fixtures for offline replay.",
        ),
    ] = False,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            "-o",
            help="Path to write the output JSON result.",
        ),
    ] = None,
    pretty: Annotated[
        bool,
        typer.Option(
            "--pretty/--compact",
            help="Print formatted JSON with indentation.",
        ),
    ] = True,
) -> None:
    """Extract, validate, and score structured change order fields from a document."""
    if provider not in ("claude", "gemini", "both"):
        typer.echo(
            f"Error: Invalid provider '{provider}'. Must be 'claude', 'gemini', or 'both'.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        result = run_pipeline(
            source=file,
            filename=file.name,
            provider=provider,  # type: ignore[arg-type]
            mock=mock,
            record=record,
        )
    except Exception as err:
        typer.echo(f"Pipeline error: {err}", err=True)
        raise typer.Exit(code=1) from err

    result_dict = result.model_dump(mode="json")
    output_str = json.dumps(result_dict, indent=2 if pretty else None)

    if out:
        out.write_text(output_str, encoding="utf-8")
        typer.echo(f"Output saved to {out}")
    else:
        typer.echo(output_str)


@app.command(name="eval")
def eval_command(
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            "-p",
            help="Provider to evaluate: 'claude', 'gemini', or 'both'.",
        ),
    ] = "both",
    mock: Annotated[
        bool,
        typer.Option(
            "--mock/--no-mock",
            help="Run eval against pre-recorded fixtures.",
        ),
    ] = True,
) -> None:
    """Evaluate pipeline accuracy and confidence calibration against synthetic ground-truth dataset."""
    typer.echo(
        f"Running evaluation benchmark on 12-doc dataset (provider={provider}, mock={mock})...\n"
    )

    # Import evaluation harness
    from eval.run_eval import evaluate_pipeline_on_dataset, run_full_evaluation_suite

    try:
        if provider == "both":
            reports, json_path, md_path = run_full_evaluation_suite(mock=mock)
            typer.echo(md_path.read_text(encoding="utf-8"))
        else:
            report = evaluate_pipeline_on_dataset(provider=provider, mock=mock)  # type: ignore[arg-type]
            typer.echo(f"Provider: {report.provider}")
            typer.echo(f"  Field Accuracy: {report.field_accuracy * 100:.1f}%")
            typer.echo(f"  Line-Item F1: {report.line_item_f1 * 100:.1f}%")
            typer.echo(f"  Hallucination Rate: {report.hallucination_rate * 100:.1f}%")
            typer.echo(
                f"  Expected Calibration Error (ECE): {report.expected_calibration_error:.4f}"
            )
            typer.echo(f"  Defect Catch Rate: {report.validation_catch_rate * 100:.1f}%")
            typer.echo(f"  Mean Latency: {report.mean_latency_ms:.1f} ms")
    except Exception as err:
        typer.echo(f"Evaluation failed: {err}", err=True)
        raise typer.Exit(code=1) from err


def main() -> None:
    """CLI entrypoint."""
    app()


if __name__ == "__main__":
    main()
