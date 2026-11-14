"""Console-script shim that keeps Typer/Rich out of the library core."""


def run() -> None:
    try:
        from pons_analysis.presentation.cli import run as cli_run
    except ImportError as exc:  # pragma: no cover - depends on installation extra
        raise SystemExit("Install pons-analysis[cli] to use the command line.") from exc
    cli_run()


if __name__ == "__main__":
    run()
