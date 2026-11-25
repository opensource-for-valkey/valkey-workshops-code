"""
Write-Behind Cache Pattern Demo

Demonstrates eventual consistency and fast writes when updating flight information.
In write-behind (write-back) caching, updates are written to the cache immediately
and queued for asynchronous database updates.

This demo shows:
1. Reading flight data (cache-aside pattern)
2. Fast writes to cache with queued database updates (write-behind pattern)
3. Background queue processing
4. Eventual consistency verification
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
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich import box
from rich.prompt import Confirm, IntPrompt

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from daos.write_behind_cache import WriteBehindCache

# Load environment variables
load_dotenv(os.environ.get("WORKSHOP_ENV_FILE", ".env"))

# Initialize typer app and rich console
app = typer.Typer(help="Write-Behind Cache Pattern Demonstration")
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


def demo_initial_read(cache: WriteBehindCache, flight_id: int) -> tuple:
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


def demo_cached_read(cache: WriteBehindCache, flight_id: int, db_latency: float) -> tuple:
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
    
    print_flight_info(flight, "Cached Flight Data")
    return flight, source, latency


def demo_write_behind_update(cache: WriteBehindCache, flight_id: int, flight: Dict) -> tuple:
    """Step 3: Update flight times - Write-Behind Pattern"""
    print_section("STEP 3: Update Flight Times - Write-Behind Pattern (Fast!)")
    
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
    
    console.print("\n[dim]Executing write-behind update (cache + queue)...[/dim]")
    
    # Measure write latency
    start_time = time.perf_counter()
    success, cache_key = cache.update_flight_departure(
        flight_id=flight_id,
        new_departure=new_departure,
        new_arrival=new_arrival,
        user="demo_user",
        comment="Flight delayed by 2 hours due to weather"
    )
    write_latency = (time.perf_counter() - start_time) * 1000
    
    if success:
        # Show verbose info
        if VERBOSE:
            console.print(f"\n[dim]Cache Key:[/dim] [yellow]{cache_key}[/yellow]")
        
        console.print(f"\n[green]✓ Write-behind update completed in {write_latency:.3f} ms[/green]")
        console.print("[dim]  → Cache updated immediately (fast!)[/dim]")
        console.print("[dim]  → Database update queued for async processing[/dim]")
        
        # Show queue status
        queue_length = cache.get_queue_length()
        console.print(f"\n[cyan]Queue Status:[/cyan] {queue_length} pending update(s)")
        
        # Performance highlight
        console.print(f"\n[bold green]⚡ Write Performance:[/bold green] [bold]{write_latency:.3f} ms[/bold] (cache-speed!)")
        console.print("[dim]Compare to write-through: ~50-200ms (database-speed)[/dim]")
    else:
        console.print("\n[red]✗ Write-behind update failed[/red]")
    
    return success, current_departure, current_arrival, write_latency


def demo_consistency_check_before(cache: WriteBehindCache, flight_id: int):
    """Step 4: Verify data consistency before queue processing"""
    print_section("STEP 4: Consistency Check - Before Queue Processing")
    
    console.print("\n[dim]Checking consistency between database and cache...[/dim]")
    console.print("[yellow]⚠ Inconsistency is EXPECTED in write-behind pattern[/yellow]")
    console.print("[dim]Cache has new data, database update is still queued[/dim]")
    
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
    
    queue_length = consistency.get("queue_length", 0)
    console.print(f"\n[cyan]Queue Status:[/cyan] {queue_length} pending update(s)")
    
    if consistency["consistent"]:
        console.print("\n[green]✓ Data is CONSISTENT (unexpected!)[/green]")
    else:
        console.print("\n[yellow]⚠ Data INCONSISTENCY detected (expected in write-behind)[/yellow]")
        console.print("[dim]This is normal - eventual consistency model[/dim]")
        
        # Show side-by-side comparison
        table = Table(title="Consistency Check", box=box.ROUNDED, show_lines=True)
        table.add_column("Field", style="cyan bold")
        table.add_column("Database (Old)", style="yellow")
        table.add_column("Cache (New)", style="green")
        table.add_column("Match", style="magenta")
        
        db_data = consistency["db_data"]
        cache_data = consistency["cache_data"]
        
        for key in ["departure", "arrival"]:
            db_val = str(db_data.get(key, "N/A"))
            cache_val = str(cache_data.get(key, "N/A"))
            match = "✓" if db_val == cache_val else "✗"
            table.add_row(key, db_val, cache_val, match)
        
        console.print(table)


def demo_process_queue(cache: WriteBehindCache):
    """Step 5: Process queue - Background worker simulation"""
    print_section("STEP 5: Process Queue - Background Worker Simulation")
    
    queue_length = cache.get_queue_length()
    console.print(f"\n[cyan]Queue Status:[/cyan] {queue_length} pending update(s)")
    
    if queue_length == 0:
        console.print("[yellow]⚠ Queue is empty, nothing to process[/yellow]")
        return 0, 0, []
    
    console.print("\n[dim]Processing queued database updates...[/dim]")
    
    # Show progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Processing queue...", total=queue_length)
        
        processed, failed, queries = cache.process_queue(batch_size=queue_length)
        
        progress.update(task, completed=queue_length)
    
    # Show results
    console.print(f"\n[green]✓ Processed:[/green] {processed} update(s)")
    if failed > 0:
        console.print(f"[red]✗ Failed:[/red] {failed} update(s)")
    
    # Show verbose info
    if VERBOSE and queries:
        console.print(f"\n[dim]─── SQL Queries Executed ({len(queries)} total) ───[/dim]")
        for i, query in enumerate(queries[:6], 1):  # Show first 6 queries
            console.print(Panel(
                f"[cyan]{query}[/cyan]",
                title=f"[bold]Query {i}: {'SELECT' if 'SELECT' in query else 'UPDATE' if 'UPDATE' in query else 'INSERT'}[/bold]",
                border_style="dim",
                box=box.ROUNDED
            ))
        if len(queries) > 6:
            console.print(f"[dim]... and {len(queries) - 6} more queries[/dim]")
    
    return processed, failed, queries


def demo_consistency_check_after(cache: WriteBehindCache, flight_id: int):
    """Step 6: Verify data consistency after queue processing"""
    print_section("STEP 6: Consistency Check - After Queue Processing")
    
    console.print("\n[dim]Checking consistency after queue processing...[/dim]")
    console.print("[green]✓ Consistency is EXPECTED now[/green]")
    console.print("[dim]Database has been updated with queued changes[/dim]")
    
    consistency = cache.verify_consistency(flight_id)
    
    # Show verbose info
    if VERBOSE:
        console.print("\n[dim]─── Verbose Details ───[/dim]")
        console.print(f"[dim]Cache Key:[/dim] [yellow]{consistency.get('cache_key')}[/yellow]")
    
    queue_length = consistency.get("queue_length", 0)
    console.print(f"\n[cyan]Queue Status:[/cyan] {queue_length} pending update(s)")
    
    if consistency["consistent"]:
        console.print("\n[green]✓ Data is now CONSISTENT between database and cache[/green]")
        console.print("[dim]Eventual consistency achieved![/dim]")
        
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
        console.print("\n[red]✗ Data still INCONSISTENT (unexpected!)[/red]")
        console.print(f"[yellow]Reason:[/yellow] {consistency.get('reason', 'Unknown')}")


def demo_read_updated_data(cache: WriteBehindCache, flight_id: int):
    """Step 7: Read updated data"""
    print_section("STEP 7: Read Updated Flight Data")
    
    console.print("\n[dim]Reading updated flight data (expecting CACHE_HIT)...[/dim]")
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


def demo_restore_original(cache: WriteBehindCache, flight_id: int, original_departure: datetime, original_arrival: datetime):
    """Step 8: Restore original times"""
    print_section("STEP 8: Restore Original Flight Times")
    
    console.print("\n[yellow]Restoring original departure and arrival times...[/yellow]")
    console.print("[dim]This ensures the demo doesn't permanently modify the database[/dim]")
    
    success, cache_key = cache.update_flight_departure(
        flight_id=flight_id,
        new_departure=original_departure,
        new_arrival=original_arrival,
        user="demo_user",
        comment="Restoring original flight times after demo"
    )
    
    if success:
        console.print("\n[green]✓ Restore queued successfully[/green]")
        
        # Show verbose info
        if VERBOSE:
            console.print(f"[dim]Cache Key:[/dim] [yellow]{cache_key}[/yellow]")
        
        # Flush queue to apply immediately
        console.print("\n[dim]Flushing queue to apply changes immediately...[/dim]")
        processed = cache.flush_queue()
        console.print(f"[green]✓ Queue flushed:[/green] {processed} update(s) processed")
        
        # Verify restoration
        restored_flight, source, latency, cache_key, query = cache.get_flight(flight_id)
        
        # Show verbose info
        print_verbose_info(cache_key, query, source)
        
        # Show performance info
        if not VERBOSE:
            source_color = "green" if source == "CACHE_HIT" else "yellow"
            console.print(f"\n[{source_color}]Source:[/{source_color}] {source} | [magenta]Latency:[/magenta] {latency:.3f} ms")
        else:
            console.print(f"\n[magenta]Latency:[/magenta] {latency:.3f} ms")
        
        print_flight_info(restored_flight, "Restored Flight Data")
    else:
        console.print("\n[red]✗ Failed to restore original times[/red]")


def demo_summary(write_latency: float):
    """Show demo summary and key takeaways"""
    print_section("DEMO COMPLETE")
    
    console.print("\n[green]✅ All steps executed successfully![/green]\n")
    
    # Key takeaways in a nice table
    takeaways_table = Table(title="💡 Key Takeaways - Write-Behind Cache Pattern", box=box.ROUNDED, show_header=False)
    takeaways_table.add_column("", style="cyan")
    takeaways_table.add_row("• [bold]Fast Writes:[/bold] Updates complete at cache-speed (< 5ms typically)")
    takeaways_table.add_row("• [bold]Eventual Consistency:[/bold] Database updates happen asynchronously")
    takeaways_table.add_row("• [bold]Queue-Based:[/bold] Updates are queued in Valkey List for processing")
    takeaways_table.add_row("• [bold]Background Worker:[/bold] Processes queue in batches")
    takeaways_table.add_row("• [bold]High Throughput:[/bold] Ideal for write-heavy workloads")
    takeaways_table.add_row("• [bold]Trade-off:[/bold] Temporary inconsistency for performance")
    
    console.print(takeaways_table)
    
    # Pattern comparison
    console.print("\n[bold]Pattern Comparison:[/bold]")
    comparison_table = Table(box=box.SIMPLE)
    comparison_table.add_column("Aspect", style="cyan bold")
    comparison_table.add_column("Write-Through", style="yellow")
    comparison_table.add_column("Write-Behind", style="green")
    
    comparison_table.add_row("Write Performance", "Slower (DB speed)", "Fast (cache speed)")
    comparison_table.add_row("Consistency", "Immediate", "Eventual")
    comparison_table.add_row("Complexity", "Simple", "Requires queue worker")
    comparison_table.add_row("Use Case", "Consistency critical", "High write throughput")
    comparison_table.add_row("Typical Latency", "50-200ms", f"{write_latency:.1f}ms")
    
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
        help="Flush cache and queue before running demo"
    )
):
    """Run the write-behind cache pattern demonstration"""
    
    # Set global verbose flag
    global VERBOSE
    VERBOSE = verbose
    
    if VERBOSE:
        console.print("[dim]Verbose mode enabled - showing detailed information[/dim]\n")
    
    # Print header
    console.print()
    console.print(Panel.fit(
        "[bold cyan]WRITE-BEHIND CACHE PATTERN DEMONSTRATION[/bold cyan]\n"
        "[yellow]Fast Writes with Eventual Consistency[/yellow]",
        border_style="cyan",
        box=box.DOUBLE
    ))
    
    # Initialize cache with progress indicator
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Initializing write-behind cache handler...", total=None)
        cache = WriteBehindCache()
        progress.update(task, completed=True)
    
    console.print("[green]✓[/green] Connected to database and cache\n")
    
    # Flush cache and queue if requested
    if flush:
        console.print("[yellow]🧹 Flushing cache and queue...[/yellow]")
        try:
            cache.cache.flush_all()
            # Also clear the queue
            while cache.get_queue_length() > 0:
                cache.cache.client.lpop(cache.QUEUE_KEY)
            console.print("[green]✓[/green] Cache and queue flushed successfully\n")
        except Exception as e:
            console.print(f"[red]❌ Error flushing: {e}[/red]\n")
    
    # Allow user to specify flight ID in interactive mode
    if interactive:
        console.print(f"[dim]Current flight ID: {flight_id}[/dim]")
        if Confirm.ask("Would you like to use a different flight ID?", default=False):
            flight_id = IntPrompt.ask("Enter flight ID", default=flight_id)
    
    console.print(f"\n[cyan]Using flight ID:[/cyan] [bold]{flight_id}[/bold]\n")
    
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
            console.print("\n[bold]→ Next: Write-Behind Update (Fast!)[/bold]")
            if not Confirm.ask("Continue?", default=True):
                return
        else:
            time.sleep(1)
        
        # Step 3: Write-behind update
        success, original_departure, original_arrival, write_latency = demo_write_behind_update(cache, flight_id, flight)
        if not success:
            return
        
        if interactive:
            console.print("\n[bold]→ Next: Consistency Check (Before Queue Processing)[/bold]")
            if not Confirm.ask("Continue?", default=True):
                return
        else:
            time.sleep(1)
        
        # Step 4: Consistency check before
        demo_consistency_check_before(cache, flight_id)
        
        if interactive:
            console.print("\n[bold]→ Next: Process Queue[/bold]")
            if not Confirm.ask("Continue?", default=True):
                return
        else:
            time.sleep(1)
        
        # Step 5: Process queue
        demo_process_queue(cache)
        
        if interactive:
            console.print("\n[bold]→ Next: Consistency Check (After Queue Processing)[/bold]")
            if not Confirm.ask("Continue?", default=True):
                return
        else:
            time.sleep(1)
        
        # Step 6: Consistency check after
        demo_consistency_check_after(cache, flight_id)
        
        if interactive:
            console.print("\n[bold]→ Next: Read Updated Data[/bold]")
            if not Confirm.ask("Continue?", default=True):
                return
        else:
            time.sleep(1)
        
        # Step 7: Read updated data
        demo_read_updated_data(cache, flight_id)
        
        if interactive:
            console.print("\n[bold]→ Next: Restore Original Times[/bold]")
            if not Confirm.ask("Continue?", default=True):
                console.print("\n[yellow]⚠ Skipping restoration - database has been modified![/yellow]")
                return
        else:
            time.sleep(1)
        
        # Step 8: Restore original
        demo_restore_original(cache, flight_id, original_departure, original_arrival)
        
        if interactive:
            console.print("\n[bold]→ Next: Summary[/bold]")
            if not Confirm.ask("Continue?", default=True):
                return
        else:
            time.sleep(1)
        
        # Step 9: Summary
        demo_summary(write_latency)
        
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
