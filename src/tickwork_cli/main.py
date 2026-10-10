from importlib.metadata import version as installed_version

import typer

from tickwork_cli.common.cli_output import write_result

app = typer.Typer(no_args_is_help=True, help="Local scheduled task management CLI")


@app.callback()
def main() -> None:
    """Manage scheduled tasks on this device."""


@app.command()
def version() -> None:
    """Report the installed package version."""
    write_result({"version": installed_version("tickwork-cli")})


if __name__ == "__main__":
    app()
