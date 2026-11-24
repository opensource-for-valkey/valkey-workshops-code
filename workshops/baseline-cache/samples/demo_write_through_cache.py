"""
Write-Through Cache Pattern Demo

Demonstrates data consistency when updating flight information.
In write-through caching, updates are written to both the database
and cache simultaneously, ensuring consistency.

This demo shows:
1. Reading flight data (cache-aside pattern)
2. Updating flight departure time (write-through pattern)
3. Verifying consistency between database and cache
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict
import time
from dotenv import load_dotenv
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box
from rich.prompt import Confirm, IntPrompt

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from daos.write_through_cache import WriteThroughCache

# Load environment variables
load_dotenv(os.environ.get("WORKSHOP_ENV_FILE", ".env"))

# Initialize typer app and rich console
app = typer.Typer(help="Write-Through Cache Pattern Demonstration")
console = Console()

# Global verbose flag
VERBOSE = False


def print_section(title: str):
    """Print a formatted section header using rich."""
    console.print()
    console.print(Panel(f"[bold cyan]{title}[/bold cyan]", box=box.DOUBLE))


def print_flight_info(flight_data: Dict, title: str):
    """Pretty print flight information using rich."""
    if not flight_data:
        console.print(f"\n[yellow]{title}[/yellow]")
        console.print("[dim]No data available[/dim]")
        return
    
    console.print(f"\n[bold cyan]{title}[/bold cyan]")
    
    # Create a table for flight information
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")
    
    table.add_row("Flight ID", str(flight_data.get('flight_id')))
    table.add_row("Flight No", str(flight_data.get('flightno')))
    table.add_row("Route", f"{flight_data.get('from_airport')} → {flight_data.get('to_airport')}")
    table.add_row("Airline", str(flight_data.get('airlinename')))
    table.add_row("Departure", str(flight_data.get('departure')))
    table.add_row("Arrival", str(flight_data.get('arrival')))
    
    console.print(table)


def print_verbose_info(cache_key: str, query: str = None, source: str = None):
    """Print verbose information about cache keys and SQL queries."""
    if not VERBOSE:
        return
    
    console.print("\n[dim]─── Verbose Details ───[/dim]")
    
    if cache_key:
        console.print(f"[dim]Cache Key:[/dim] [yellow]{cache_key}[/yellow]")
    
    if source:
        source_icon = "✓" if source == "CACHE_HIT" else "✗"
        source_color = "green" if source == "CACHE_HIT" else "yellow"
        console.print(f"[dim]Cache Status:[/dim] [{source_color}]{source_icon} {source}[/{source_color}]")
    
    if query:
        console.print(Panel(
            f"[cyan]{query}[/cyan]",
            title="[bold]SQL Query Executed[/bold]",
            border_style="dim",
            box=box.ROUNDED
        ))


def demo_initial_read(cache: WriteThroughCache, flight_id: int) -> tuple:
    """Step 1: Initial read - Cache-Aside Pattern"""
    print_section("STEP 1: Initial Read - Cache-Aside Pattern")
    
    console.print("\n[dim]Reading flight data for the first time (expecting CACHE_MISS)...[/dim]")
    flight, source, latency, cache_key, query = cache.get_flight(flight_id)
    
    if not flight:
        console.print(f"\n[red]✗ Flight {flight_id} not found. Please use a valid flight_id.[/red]")
        return None, None, None
    
    # Show verbose info first
    print_verbose_info(cache_key, query, source)
    
    # Show performance info
    if not VERBOSE:
        source_color = "yellow" if source == "CACHE_MISS" else "green"
        console.print(f"\n[{source_color}]Source:[/{source_color}] {source} | [magenta]Latency:[/magenta] {latency:.3f} ms")
    else:
        console.print(f"\n[magenta]Latency:[/magenta] {latency:.3f} ms")
    
    print_flight_info(flight, "Initial Flight Data")
    return flight, source, latency


def demo_cached_read(cache: WriteThroughCache, flight_id: int, db_latency: float) -> tuple:
    """Step 2: Second read - Should hit cache"""
    print_section("STEP 2: Second Read - Cache Hit Expected")
    
    console.print("\n[dim]Reading the same flight data again (expecting CACHE_HIT)...[/dim]")
    flight, source, latency, cache_key, query = cache.get_flight(flight_id)
    
    # Show verbose info first
    print_verbose_info(cache_key, query, source)
    
    # Show performance info with comparison
    if not VERBOSE:
        source_color = "green" if source == "CACHE_HIT" else "yellow"
        console.print(f"\n[{source_color}]Source:[/{source_color}] {source} | [magenta]Latency:[/magenta] {latency:.3f} ms")
    else:
        console.print(f"\n[magenta]Latency:[/magenta] {latency:.3f} ms")
    
    if source == "CACHE_HIT" and db_latency:
        speedup = db_latency / latency if latency > 0 else 0
        console.print(f"[green]⚡ Performance:[/green] [bold]{speedup:.1f}x faster[/bold] than database query")
        
        # Show comparison table
        perf_table = Table(title="Performance Comparison", box=box.ROUNDED)
        perf_table.add_column("Source", style="cyan bold")
        perf_table.add_column("Latency", style="magenta", justify="right")
        perf_table.add_column("Speedup", style="green", justify="right")
        
        perf_table.add_row("Database (MISS)", f"{db_latency:.3f} ms", "1.0x")
        perf_table.add_row("Cache (HIT)", f"{latency:.3f} ms", f"{speedup:.1f}x")
        
        console.print(perf_table)
    
    print_flight_info(flight, "Cached Flight Data")
    return flight, source, latency


def demo_write_through_update(cache: WriteThroughCache, flight_id: int, flight: Dict) -> tuple:
    """Step 3: Update flight times - Write-Through Pattern"""
    print_section("STEP 3: Update Flight Times - Write-Through Pattern")
    
    # Parse current times and add 2 hours delay
    current_departure = datetime.fromisoformat(flight["departure"])
    current_arrival = datetime.fromisoformat(flight["arrival"])
    
    new_departure = current_departure + timedelta(hours=2)
    new_arrival = current_arrival + timedelta(hours=2)
    
    console.print(f"\n[yellow]Simulating flight delay:[/yellow] Adding 2 hours to departure and arrival times")
    
    # Create comparison table
    table = Table(title="Flight Time Update", box=box.ROUNDED)
    table.add_column("", style="cyan bold")
    table.add_column("Old Time", style="yellow")
    table.add_column("New Time", style="green")
    
    table.add_row("Departure", str(current_departure), str(new_departure))
    table.add_row("Arrival", str(current_arrival), str(new_arrival))
    
    console.print(table)
    
    console.print("\n[dim]Executing write-through update...[/dim]")
    
    success, queries = cache.update_flight_departure(
        flight_id=flight_id,
        new_departure=new_departure,
        new_arrival=new_arrival,
        user="demo_user",
        comment="Flight delayed by 2 hours due to weather"
    )
    
    if success:
        # Show verbose info
        if VERBOSE and queries:
            console.print("\n[dim]─── SQL Queries Executed ───[/dim]")
            for i, query in enumerate(queries, 1):
                console.print(Panel(
                    f"[cyan]{query}[/cyan]",
                    title=f"[bold]Query {i}: {'SELECT' if 'SELECT' in query else 'UPDATE' if 'UPDATE' in query else 'INSERT'}[/bold]",
                    border_style="dim",
                    box=box.ROUNDED
                ))
        
        console.print("\n[green]✓ Write-through update completed successfully[/green]")
        if not VERBOSE:
            console.print("[dim]  → Database updated[/dim]")
            console.print("[dim]  → Cache updated[/dim]")
            console.print("[dim]  → Change logged in flight_log table[/dim]")
    else:
        console.print("\n[red]✗ Write-through update failed[/red]")
    
    return success, current_departure, current_arrival


def demo_consistency_check(cache: WriteThroughCache, flight_id: int):
    """Step 4: Verify data consistency"""
    print_section("STEP 4: Verify Data Consistency")
    
    console.print("\n[dim]Checking consistency between database and cache...[/dim]")
    
    consistency = cache.verify_consistency(flight_id)
    
    # Show verbose info
    if VERBOSE:
        console.print("\n[dim]─── Verbose Details ───[/dim]")
        console.print(f"[dim]Cache Key:[/dim] [yellow]{consistency.get('cache_key')}[/yellow]")
        console.print(Panel(
            f"[cyan]{consistency.get('query')}[/cyan]",
            title="[bold]Consistency Check Query[/bold]",
            border_style="dim",
            box=box.ROUNDED
        ))
    
    if consistency["consistent"]:
        console.print("\n[green]✓ Data is CONSISTENT between database and cache[/green]")
        
        # Show side-by-side comparison
        table = Table(title="Consistency Verification", box=box.ROUNDED, show_lines=True)
        table.add_column("Field", style="cyan bold")
        table.add_column("Database", style="yellow")
        table.add_column("Cache", style="green")
        table.add_column("Match", style="magenta")
        
        db_data = consistency["db_data"]
        cache_data = consistency["cache_data"]
        
        for key in ["flight_id", "flightno", "departure", "arrival"]:
            db_val = str(db_data.get(key, "N/A"))
            cache_val = str(cache_data.get(key, "N/A"))
            match = "✓" if db_val == cache_val else "✗"
            table.add_row(key, db_val, cache_val, match)
        
        console.print(table)
    else:
        console.print("\n[red]✗ Data INCONSISTENCY detected![/red]")
        console.print(f"[yellow]Reason:[/yellow] {consistency.get('reason', 'Unknown')}")
        
        if VERBOSE:
            print_flight_info(consistency.get("db_data"), "Database Data")
            print_flight_info(consistency.get("cache_data"), "Cache Data")


def demo_read_updated_data(cache: WriteThroughCache, flight_id: int):
    """Step 5: Read updated data"""
    print_section("STEP 5: Read Updated Flight Data")
    
    console.print("\n[dim]Reading updated flight data (expecting CACHE_HIT after write-through)...[/dim]")
    updated_flight, source, latency, cache_key, query = cache.get_flight(flight_id)
    
    # Show verbose info first
    print_verbose_info(cache_key, query, source)
    
    # Show performance info
    if not VERBOSE:
        source_color = "green" if source == "CACHE_HIT" else "yellow"
        console.print(f"\n[{source_color}]Source:[/{source_color}] {source} | [magenta]Latency:[/magenta] {latency:.3f} ms")
    else:
        console.print(f"\n[magenta]Latency:[/magenta] {latency:.3f} ms")
    
    print_flight_info(updated_flight, "Updated Flight Data (from cache)")


def demo_restore_original(cache: WriteThroughCache, flight_id: int, original_departure: datetime, original_arrival: datetime):
    """Step 6: Restore original times"""
    print_section("STEP 6: Restore Original Flight Times")
    
    console.print("\n[yellow]Restoring original departure and arrival times...[/yellow]")
    console.print("[dim]This ensures the demo doesn't permanently modify the database[/dim]")
    
    success, queries = cache.update_flight_departure(
        flight_id=flight_id,
        new_departure=original_departure,
        new_arrival=original_arrival,
        user="demo_user",
        comment="Restoring original flight times after demo"
    )
    
    if success:
        # Show verbose info for queries
        if VERBOSE and queries:
            console.print("\n[dim]─── SQL Queries Executed ───[/dim]")
            for i, query in enumerate(queries, 1):
                console.print(Panel(
                    f"[cyan]{query}[/cyan]",
                    title=f"[bold]Query {i}: {'SELECT' if 'SELECT' in query else 'UPDATE' if 'UPDATE' in query else 'INSERT'}[/bold]",
                    border_style="dim",
                    box=box.ROUNDED
                ))
        
        console.print("\n[green]✓ Original times restored successfully[/green]")
        
        restored_flight, source, latency, cache_key, query = cache.get_flight(flight_id)
        
        # Show verbose info
        print_verbose_info(cache_key, query, source)
        
        # Show performance info
        if not VERBOSE:
            source_color = "green" if source == "CACHE_HIT" else "yellow"
            console.print(f"[{source_color}]Source:[/{source_color}] {source} | [magenta]Latency:[/magenta] {latency:.3f} ms")
        else:
            console.print(f"\n[magenta]Latency:[/magenta] {latency:.3f} ms")
        
        print_flight_info(restored_flight, "Restored Flight Data")
    else:
        console.print("\n[red]✗ Failed to restore original times[/red]")


def demo_summary():
    """Show demo summary and key takeaways"""
    print_section("DEMO COMPLETE")
    
    console.print("\n[green]✅ All steps executed successfully![/green]\n")
    
    # Key takeaways in a nice table
    takeaways_table = Table(title="💡 Key Takeaways - Write-Through Cache Pattern", box=box.ROUNDED, show_header=False)
    takeaways_table.add_column("", style="cyan")
    takeaways_table.add_row("• [bold]Consistency:[/bold] Database and cache are always in sync")
    takeaways_table.add_row("• [bold]Write-Through:[/bold] Updates go to both database and cache simultaneously")
    takeaways_table.add_row("• [bold]Audit Trail:[/bold] All changes are logged in flight_log table")
    takeaways_table.add_row("• [bold]Cache-Aside Reads:[/bold] Reads still benefit from cache performance")
    takeaways_table.add_row("• [bold]Data Integrity:[/bold] No stale data in cache after updates")
    
    console.print(takeaways_table)
    
    # Pattern comparison
    console.print("\n[bold]Pattern Comparison:[/bold]")
    comparison_table = Table(box=box.SIMPLE)
    comparison_table.add_column("Aspect", style="cyan bold")
    comparison_table.add_column("Cache-Aside", style="yellow")
    comparison_table.add_column("Write-Through", style="green")
    
    comparison_table.add_row("Read Performance", "Fast (cached)", "Fast (cached)")
    comparison_table.add_row("Write Performance", "Fast (DB only)", "Slower (DB + Cache)")
    comparison_table.add_row("Consistency", "May have stale data", "Always consistent")
    comparison_table.add_row("Use Case", "Read-heavy workloads", "Write-heavy with consistency needs")
    
    console.print(comparison_table)


@app.command()
def run(
    flight_id: int = typer.Option(
        115,
        "--flight-id",
        "-f",
        help="Flight ID to use for demonstration"
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Run demo step-by-step with prompts"
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed information and SQL queries"
    ),
    flush: bool = typer.Option(
        False,
        "--flush",
        help="Flush cache before running demo"
    )
):
    """Run the write-through cache pattern demonstration"""
    
    # Set global verbose flag
    global VERBOSE
    VERBOSE = verbose
    
    if VERBOSE:
        console.print("[dim]Verbose mode enabled - showing detailed information[/dim]\n")
    
    # Print header
    console.print()
    console.print(Panel.fit(
        "[bold cyan]WRITE-THROUGH CACHE PATTERN DEMONSTRATION[/bold cyan]\n"
        "[yellow]Data Consistency for Flight Updates[/yellow]",
        border_style="cyan",
        box=box.DOUBLE
    ))
    
    # Initialize cache with progress indicator
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Initializing write-through cache handler...", total=None)
        cache = WriteThroughCache()
        progress.update(task, completed=True)
    
    console.print("[green]✓[/green] Connected to database and cache\n")
    
    # Flush cache if requested
    if flush:
        console.print("[yellow]🧹 Flushing cache...[/yellow]")
        try:
            cache.cache.flush_all()
            console.print("[green]✓[/green] Cache flushed successfully\n")
        except Exception as e:
            console.print(f"[red]❌ Error flushing cache: {e}[/red]\n")
    
    # Allow user to specify flight ID in interactive mode
    if interactive:
        console.print(f"[dim]Current flight ID: {flight_id}[/dim]")
        if Confirm.ask("Would you like to use a different flight ID?", default=False):
            flight_id = IntPrompt.ask("Enter flight ID", default=flight_id)
    
    console.print(f"\n[cyan]Using flight ID:[/cyan] [bold]{flight_id}[/bold]\n")
    
    # Define demo steps
    demo_steps = [
        ("Initial Read", lambda: demo_initial_read(cache, flight_id)),
        ("Cached Read", lambda: demo_cached_read(cache, flight_id)),
        ("Write-Through Update", lambda: demo_write_through_update(cache, flight_id, flight)),
        ("Consistency Check", lambda: demo_consistency_check(cache, flight_id)),
        ("Read Updated Data", lambda: demo_read_updated_data(cache, flight_id)),
        ("Restore Original", lambda: demo_restore_original(cache, flight_id, original_departure, original_arrival)),
        ("Summary", lambda: demo_summary()),
    ]
    
    try:
        # Step 1: Initial read
        flight, source, db_latency = demo_initial_read(cache, flight_id)
        if not flight:
            return
        
        if interactive:
            console.print("\n[bold]→ Next: Cached Read[/bold]")
            if not Confirm.ask("Continue?", default=True):
                return
        else:
            time.sleep(1)
        
        # Step 2: Cached read
        demo_cached_read(cache, flight_id, db_latency)
        
        if interactive:
            console.print("\n[bold]→ Next: Write-Through Update[/bold]")
            if not Confirm.ask("Continue?", default=True):
                return
        else:
            time.sleep(1)
        
        # Step 3: Write-through update
        success, original_departure, original_arrival = demo_write_through_update(cache, flight_id, flight)
        if not success:
            return
        
        if interactive:
            console.print("\n[bold]→ Next: Consistency Check[/bold]")
            if not Confirm.ask("Continue?", default=True):
                return
        else:
            time.sleep(1)
        
        # Step 4: Consistency check
        demo_consistency_check(cache, flight_id)
        
        if interactive:
            console.print("\n[bold]→ Next: Read Updated Data[/bold]")
            if not Confirm.ask("Continue?", default=True):
                return
        else:
            time.sleep(1)
        
        # Step 5: Read updated data
        demo_read_updated_data(cache, flight_id)
        
        if interactive:
            console.print("\n[bold]→ Next: Restore Original Times[/bold]")
            if not Confirm.ask("Continue?", default=True):
                console.print("\n[yellow]⚠ Skipping restoration - database has been modified![/yellow]")
                return
        else:
            time.sleep(1)
        
        # Step 6: Restore original
        demo_restore_original(cache, flight_id, original_departure, original_arrival)
        
        if interactive:
            console.print("\n[bold]→ Next: Summary[/bold]")
            if not Confirm.ask("Continue?", default=True):
                return
        else:
            time.sleep(1)
        
        # Step 7: Summary
        demo_summary()
        
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠ Demo interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red]❌ Error during demo: {e}[/red]")
        if VERBOSE:
            import traceback
            traceback.print_exc()
    
    finally:
        # Cleanup
        console.print("\n[cyan]🧹 Cleaning up connections...[/cyan]")
        cache.close()
        console.print("[green]✓[/green] Connections closed\n")


if __name__ == "__main__":
    app()
