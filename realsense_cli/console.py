from rich.console import Console

# Command output goes to stdout, diagnostics and errors to stderr
console = Console()
err_console = Console(stderr=True)
