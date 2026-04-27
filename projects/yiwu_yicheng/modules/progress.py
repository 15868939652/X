from contextlib import contextmanager
import sys
from rich.console import Console
from rich.panel import Panel

# highlight=False 避免并发时数字被随机上色干扰阅读
console = Console(highlight=False, legacy_windows=False)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def show_header(brand: str) -> None:
    console.print()
    console.print(Panel(
        f"[bold white]{brand}  文案批量生成系统[/bold white]",
        border_style="bright_blue",
        padding=(0, 4),
    ))
    console.print()


def show_total(total: int) -> None:
    console.print(f"   共 [bold]{total}[/bold] 篇待生成\n")


def show_article_header(platform: str, keyword: str, task_id: int) -> None:
    console.rule(
        f" [bright_blue]{platform}[/bright_blue]"
        f"  [dim]-[/dim]  {keyword[:30]}"
        f"  [dim]-[/dim]  #{task_id} ",
        style="dim",
    )


def show_params(mode: str, profile: str) -> None:
    console.print(f"   [dim]模式: {mode}   人设: {profile[:20]}...[/dim]")


@contextmanager
def step(label: str):
    """线程安全的步骤标记，替代 console.status() 的 Live spinner"""
    console.print(f"   [dim]-> {label}...[/dim]")
    yield


def show_done(label: str, detail: str = "") -> None:
    detail_part = f"   [dim]{detail}[/dim]" if detail else ""
    console.print(f"   [green][OK][/green]  {label}{detail_part}")


def show_score(score: int, min_score: int) -> None:
    color = "green bold" if score >= min_score else "yellow bold"
    console.print(f"   [green][OK][/green]  质量评分   [{color}]{score} 分[/{color}]")


def show_retry(retry: int, score: int, max_retry: int) -> None:
    console.print(
        f"   [yellow][RETRY][/yellow]  得分 [yellow bold]{score}[/yellow bold]，"
        f"第 {retry}/{max_retry} 次重试..."
    )


def show_saved(path: str) -> None:
    console.print(f"   [bright_blue][SAVE][/bright_blue]  已保存：[dim]{path}[/dim]\n")


def show_error(msg: str) -> None:
    console.print(f"   [red][ERR][/red]  {msg}")
