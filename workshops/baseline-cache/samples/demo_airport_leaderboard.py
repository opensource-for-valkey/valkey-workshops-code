"""
Airport Leaderboard Demo - RDBMS vs Valkey Sorted Sets

This demo showcases the performance difference between querying airport leaderboards
from a relational database versus using Valkey Sorted Sets for cached rankings.

Key Features:
- Compare RDBMS query latency vs Valkey Sorted Set operations
- Pre-populate Valkey with top airports (not measured in comparison)
- Show SQL queries and Valkey commands in verbose mode
- Interactive mode for step-by-step execution
- Flush cache option to start fresh

Performance Comparison:
- RDBMS: Complex JOIN queries with aggregations
- Valkey: O(log(N)) sorted set operations (ZREVRANGE, ZSCORE)
"""

import sys
import time
import os
import typer
from pathlib import Path
from typing import Dict, List, Optional
from datetime import date, datetime
from dataclasses import dataclass

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from daos.airport_leaderboard import AirportLeaderboard
from core import get_cache_client
from glide_sync import RangeByIndex
from sqlalchemy import text
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.prompt import Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from tqdm import tqdm

# Initialize typer app and rich console
app = typer.Typer(help="Airport Leaderboard Demo - RDBMS vs Valkey Sorted Sets")
console = Console()

# Global verbose flag
VERBOSE = False


@dataclass
class QueryMetrics:
    """Metrics for a single query execution."""
    query_type: str
    source: str  # "RDBMS" or "Valkey"
    latency_ms: float
    result_count: int
    query_text: Optional[str] = None
    commands: Optional[List[str]] = None


def format_time_ms(ms: float) -> str:
    """Format milliseconds in a human-readable way."""
    if ms < 1:
        return f"{ms * 1000:.1f}µs"
    elif ms < 1000:
        return f"{ms:.2f}ms"
    else:
        return f"{ms / 1000:.3f}s"


def print_section(title: str):
    """Print a formatted section header."""
    console.print()
    console.print(Panel(f"[bold cyan]{title}[/bold cyan]", box=box.DOUBLE))


def populate_valkey_leaderboards(
    leaderboard: AirportLeaderboard,
    cache_client,
    query_date: date
) -> Dict[str, int]:
    """
    Pre-populate Valkey with airport leaderboards using Sorted Sets.
    This operation is NOT timed as we're comparing read performance.
    
    Args:
        leaderboard: AirportLeaderboard DAO instance
        cache_client: Valkey/Redis client
        query_date: Date to query for
    
    Returns:
        Dictionary with counts of populated entries
    """
    console.print("\n[yellow]📦 Pre-populating Valkey Sorted Sets...[/yellow]")
    
    date_str = query_date.strftime("%Y-%m-%d")
    
    # Get top airports by flights
    flights_key = f"leaderboard:flights:{date_str}"
    
    if VERBOSE:
        console.print(f"\n[dim]Valkey Commands for flights leaderboard:[/dim]")
        console.print(f"[dim]  DEL {flights_key}[/dim]")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Fetching top airports by flights...", total=None)
        top_by_flights = leaderboard.get_top_airports_by_flights(query_date, limit=100)
        progress.update(task, completed=True)
    
    # Clear existing sorted set
    cache_client.client.delete([cache_client.key(flights_key)])
    
    # Populate flights leaderboard with progress bar
    for airport in tqdm(
        top_by_flights,
        desc="Populating flights leaderboard",
        unit="airport",
        disable=VERBOSE
    ):
        score = airport['total_flights']
        # Format: IATA|AirportName|Departures|Arrivals
        member = f"{airport['iata']}|{airport['name']}|{airport['departures']}|{airport['arrivals']}"
        
        if VERBOSE and airport['rank'] <= 3:
            console.print(f"[dim]  ZADD {flights_key} {score} '{member}'[/dim]")
        
        cache_client.client.zadd(cache_client.key(flights_key), {member: score})
    
    # Get top airports by passengers
    passengers_key = f"leaderboard:passengers:{date_str}"
    
    if VERBOSE:
        console.print(f"\n[dim]Valkey Commands for passengers leaderboard:[/dim]")
        console.print(f"[dim]  DEL {passengers_key}[/dim]")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Fetching top airports by passengers...", total=None)
        top_by_passengers = leaderboard.get_top_airports_by_passengers(query_date, limit=100)
        progress.update(task, completed=True)
    
    # Clear existing sorted set
    cache_client.client.delete([cache_client.key(passengers_key)])
    
    # Populate passengers leaderboard with progress bar
    for airport in tqdm(
        top_by_passengers,
        desc="Populating passengers leaderboard",
        unit="airport",
        disable=VERBOSE
    ):
        score = airport['total_passengers']
        # Format: IATA|AirportName|DepartingPassengers|ArrivingPassengers|TotalFlights
        member = f"{airport['iata']}|{airport['name']}|{airport['departing_passengers']}|{airport['arriving_passengers']}|{airport['total_flights']}"
        
        if VERBOSE and airport['rank'] <= 3:
            console.print(f"[dim]  ZADD {passengers_key} {score} '{member}'[/dim]")
        
        cache_client.client.zadd(cache_client.key(passengers_key), {member: score})
    
    console.print(f"[green]✓[/green] Populated {len(top_by_flights):,} airports in flights leaderboard")
    console.print(f"[green]✓[/green] Populated {len(top_by_passengers):,} airports in passengers leaderboard")
    
    return {
        'flights': len(top_by_flights),
        'passengers': len(top_by_passengers)
    }


def query_rdbms_top_flights(
    leaderboard: AirportLeaderboard,
    query_date: date,
    limit: int
) -> QueryMetrics:
    """Query top airports by flights from RDBMS."""
    start = time.time()
    results = leaderboard.get_top_airports_by_flights(query_date, limit=limit)
    latency = (time.time() - start) * 1000
    
    query_text = f"""
SELECT 
    a.airport_id, a.iata, a.icao, a.name,
    COUNT(DISTINCT CASE WHEN f.from = a.airport_id THEN f.flight_id END) as departures,
    COUNT(DISTINCT CASE WHEN f.to = a.airport_id THEN f.flight_id END) as arrivals,
    COUNT(DISTINCT f.flight_id) as total_flights
FROM airport a
INNER JOIN flight f ON (f.from = a.airport_id OR f.to = a.airport_id)
WHERE DATE(f.departure) = '{query_date.strftime("%Y-%m-%d")}'
    AND a.iata IS NOT NULL
GROUP BY a.airport_id, a.iata, a.icao, a.name
HAVING COUNT(DISTINCT f.flight_id) > 0
ORDER BY total_flights DESC, a.name ASC
LIMIT {limit}
"""
    
    if VERBOSE:
        console.print(f"\n[dim]SQL Query:[/dim]")
        console.print(f"[dim]{query_text.strip()}[/dim]")
    
    return QueryMetrics(
        query_type="Top Airports by Flights",
        source="RDBMS",
        latency_ms=latency,
        result_count=len(results),
        query_text=query_text.strip()
    )


def query_valkey_top_flights(
    cache_client,
    query_date: date,
    limit: int
) -> QueryMetrics:
    """Query top airports by flights from Valkey Sorted Set."""
    date_str = query_date.strftime("%Y-%m-%d")
    flights_key = f"leaderboard:flights:{date_str}"
    
    commands = [
        f"ZREVRANGE {flights_key} 0 {limit - 1} WITHSCORES"
    ]
    
    if VERBOSE:
        console.print(f"\n[dim]Valkey Commands:[/dim]")
        for cmd in commands:
            console.print(f"[dim]  {cmd}[/dim]")
    
    start = time.time()
    results = cache_client.client.zrange_withscores(cache_client.key(flights_key), RangeByIndex(0, limit - 1), reverse=True)
    latency = (time.time() - start) * 1000
    
    return QueryMetrics(
        query_type="Top Airports by Flights",
        source="Valkey",
        latency_ms=latency,
        result_count=len(results),
        commands=commands
    )


def query_rdbms_top_passengers(
    leaderboard: AirportLeaderboard,
    query_date: date,
    limit: int
) -> QueryMetrics:
    """Query top airports by passengers from RDBMS."""
    start = time.time()
    results = leaderboard.get_top_airports_by_passengers(query_date, limit=limit)
    latency = (time.time() - start) * 1000
    
    query_text = f"""
SELECT 
    a.airport_id, a.iata, a.icao, a.name,
    COUNT(DISTINCT CASE WHEN f.from = a.airport_id THEN b.booking_id END) as departing_passengers,
    COUNT(DISTINCT CASE WHEN f.to = a.airport_id THEN b.booking_id END) as arriving_passengers,
    COUNT(DISTINCT b.booking_id) as total_passengers,
    COUNT(DISTINCT f.flight_id) as total_flights
FROM airport a
INNER JOIN flight f ON (f.from = a.airport_id OR f.to = a.airport_id)
INNER JOIN booking b ON b.flight_id = f.flight_id
WHERE DATE(f.departure) = '{query_date.strftime("%Y-%m-%d")}'
    AND a.iata IS NOT NULL
GROUP BY a.airport_id, a.iata, a.icao, a.name
HAVING COUNT(DISTINCT b.booking_id) > 0
ORDER BY total_passengers DESC, a.name ASC
LIMIT {limit}
"""
    
    if VERBOSE:
        console.print(f"\n[dim]SQL Query:[/dim]")
        console.print(f"[dim]{query_text.strip()}[/dim]")
    
    return QueryMetrics(
        query_type="Top Airports by Passengers",
        source="RDBMS",
        latency_ms=latency,
        result_count=len(results),
        query_text=query_text.strip()
    )


def query_valkey_top_passengers(
    cache_client,
    query_date: date,
    limit: int
) -> QueryMetrics:
    """Query top airports by passengers from Valkey Sorted Set."""
    date_str = query_date.strftime("%Y-%m-%d")
    passengers_key = f"leaderboard:passengers:{date_str}"
    
    commands = [
        f"ZREVRANGE {passengers_key} 0 {limit - 1} WITHSCORES"
    ]
    
    if VERBOSE:
        console.print(f"\n[dim]Valkey Commands:[/dim]")
        for cmd in commands:
            console.print(f"[dim]  {cmd}[/dim]")
    
    start = time.time()
    results = cache_client.client.zrange_withscores(cache_client.key(passengers_key), RangeByIndex(0, limit - 1), reverse=True)
    latency = (time.time() - start) * 1000
    
    return QueryMetrics(
        query_type="Top Airports by Passengers",
        source="Valkey",
        latency_ms=latency,
        result_count=len(results),
        commands=commands
    )


def query_rdbms_airport_rank(
    leaderboard: AirportLeaderboard,
    airport_iata: str,
    query_date: date
) -> QueryMetrics:
    """Query specific airport's rank from RDBMS."""
    # Get all airports sorted by flights to find rank
    start = time.time()
    all_airports = leaderboard.get_top_airports_by_flights(query_date, limit=1000)
    
    # Find the airport
    rank = None
    for airport in all_airports:
        if airport['iata'] == airport_iata:
            rank = airport['rank']
            break
    
    latency = (time.time() - start) * 1000
    
    query_text = f"""
-- First query to get all airports ranked
SELECT 
    a.airport_id, a.iata, a.icao, a.name,
    COUNT(DISTINCT f.flight_id) as total_flights
FROM airport a
INNER JOIN flight f ON (f.from = a.airport_id OR f.to = a.airport_id)
WHERE DATE(f.departure) = '{query_date.strftime("%Y-%m-%d")}'
    AND a.iata IS NOT NULL
GROUP BY a.airport_id, a.iata, a.icao, a.name
HAVING COUNT(DISTINCT f.flight_id) > 0
ORDER BY total_flights DESC, a.name ASC
LIMIT 1000

-- Then find rank of '{airport_iata}' in application code
"""
    
    if VERBOSE:
        console.print(f"\n[dim]SQL Query:[/dim]")
        console.print(f"[dim]{query_text.strip()}[/dim]")
    
    return QueryMetrics(
        query_type=f"Airport Rank ({airport_iata})",
        source="RDBMS",
        latency_ms=latency,
        result_count=1 if rank else 0,
        query_text=query_text.strip()
    )


def query_valkey_airport_rank(
    cache_client,
    airport_iata: str,
    query_date: date
) -> QueryMetrics:
    """Query specific airport's rank from Valkey Sorted Set."""
    date_str = query_date.strftime("%Y-%m-%d")
    flights_key = f"leaderboard:flights:{date_str}"
    
    # Find the member with matching IATA
    commands = [
        f"ZSCAN {flights_key} 0 MATCH {airport_iata}|*",
        f"ZREVRANK {flights_key} {airport_iata}|*"
    ]
    
    if VERBOSE:
        console.print(f"\n[dim]Valkey Commands:[/dim]")
        console.print(f"[dim]  ZSCAN {flights_key} 0 MATCH {airport_iata}|*[/dim]")
    
    start = time.time()
    
    # Use ZSCAN with pattern matching to find the member starting with IATA
    cursor = 0
    target_member = None
    
    while True:
        cursor, members = cache_client.client.zscan(
            cache_client.key(flights_key), 
            cursor=str(cursor), 
            match=f"{airport_iata}|*",
            count=100
        )
        
        if members:
            # ZSCAN returns list of (member, score) tuples
            target_member = members[0][0] if isinstance(members[0], tuple) else members[0]
            break
        
        if cursor in {0, "0", b"0"}:
            break
    
    # Get rank
    rank = None
    if target_member:
        if VERBOSE:
            console.print(f"[dim]  ZREVRANK {flights_key} '{target_member}'[/dim]")
        rank = cache_client.client.zrevrank(cache_client.key(flights_key), target_member)
    
    latency = (time.time() - start) * 1000
    
    return QueryMetrics(
        query_type=f"Airport Rank ({airport_iata})",
        source="Valkey",
        latency_ms=latency,
        result_count=1 if rank is not None else 0,
        commands=commands
    )


def create_comparison_table(metrics_list: List[QueryMetrics]) -> Table:
    """Create a comparison table for RDBMS vs Valkey."""
    table = Table(
        title="⚡ Performance Comparison: RDBMS vs Valkey Sorted Sets",
        box=box.ROUNDED,
        show_lines=True
    )
    
    table.add_column("Query Type", style="cyan bold")
    table.add_column("Source", style="white")
    table.add_column("Latency", style="magenta", justify="right")
    table.add_column("Results", style="green", justify="right")
    table.add_column("Speedup", style="yellow", justify="center")
    
    # Group by query type
    query_groups = {}
    for metric in metrics_list:
        if metric.query_type not in query_groups:
            query_groups[metric.query_type] = {}
        query_groups[metric.query_type][metric.source] = metric
    
    # Add rows
    for query_type, sources in query_groups.items():
        rdbms = sources.get('RDBMS')
        valkey = sources.get('Valkey')
        
        if rdbms and valkey:
            speedup = rdbms.latency_ms / valkey.latency_ms if valkey.latency_ms > 0 else 0
            speedup_str = f"[green bold]{speedup:.1f}x faster[/green bold]"
            
            # Add RDBMS row
            table.add_row(
                query_type,
                "🗄️  RDBMS",
                f"[red]{format_time_ms(rdbms.latency_ms)}[/red]",
                f"{rdbms.result_count:,}",
                ""
            )
            
            # Add Valkey row
            table.add_row(
                "",
                "⚡ Valkey",
                f"[green]{format_time_ms(valkey.latency_ms)}[/green]",
                f"{valkey.result_count:,}",
                speedup_str
            )
    
    return table


@app.command()
def run_demo(
    date_str: str = typer.Option(
        None,
        "--date",
        help="Date in YYYY-MM-DD format (defaults to today)"
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Run step-by-step with prompts"
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show SQL queries and Valkey commands"
    ),
    flush: bool = typer.Option(
        False,
        "--flush",
        "-f",
        help="Flush cache before running demo"
    )
):
    """
    Run the airport leaderboard comparison demo.
    
    Compares RDBMS query performance vs Valkey Sorted Sets for airport rankings.
    """
    global VERBOSE
    VERBOSE = verbose
    
    # Parse date or use today
    if date_str:
        try:
            query_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]Error: Invalid date format '{date_str}'. Use YYYY-MM-DD[/red]")
            raise typer.Exit(1)
    else:
        query_date = date.today()
    
    # Print header
    console.print()
    console.print(Panel.fit(
        "[bold cyan]AIRPORT LEADERBOARD DEMO[/bold cyan]\n"
        "[yellow]RDBMS vs Valkey Sorted Sets Performance Comparison[/yellow]",
        border_style="cyan",
        box=box.DOUBLE
    ))
    
    # Show configuration
    config_table = Table(title="Configuration", box=box.ROUNDED, show_header=False)
    config_table.add_column("Setting", style="cyan bold")
    config_table.add_column("Value", style="white")
    
    config_table.add_row("Query Date", query_date.strftime("%Y-%m-%d"))
    config_table.add_row("Interactive Mode", "Enabled" if interactive else "Disabled")
    config_table.add_row("Verbose Mode", "Enabled" if verbose else "Disabled")
    config_table.add_row("Flush Cache", "Yes" if flush else "No")
    
    console.print()
    console.print(config_table)
    
    # Initialize connections
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Initializing connections...", total=None)
        leaderboard = AirportLeaderboard()
        cache_client = get_cache_client()
        progress.update(task, completed=True)
    
    console.print("[green]✓[/green] Connected to RDBMS and Valkey\n")
    
    # Flush cache if requested
    if flush:
        console.print("[yellow]🧹 Flushing caches...[/yellow]")
        
        # Flush Valkey cache
        try:
            cache_client.flush_all()
            console.print("[green]✓[/green] Valkey cache flushed successfully")
        except Exception as e:
            console.print(f"[red]❌ Error flushing Valkey cache: {e}[/red]")
        
        # Flush RDBMS buffer cache
        try:
            db_engine = leaderboard.db_engine
            db_type = os.getenv("DB_ENGINE", "mysql").lower()
            
            with db_engine.connect() as conn:
                if db_type in ["mysql", "mariadb"]:
                    # Try to flush query cache (deprecated in MySQL 8.0+)
                    try:
                        conn.execute(text("RESET QUERY CACHE"))
                        console.print("[green]✓[/green] MySQL query cache flushed")
                    except Exception:
                        # Query cache removed in MySQL 8.0+
                        console.print("[dim]  MySQL query cache not available (MySQL 8.0+ removed it)[/dim]")
                    
                    # Flush table caches to force re-reading from disk
                    try:
                        conn.execute(text("FLUSH TABLES"))
                        console.print("[green]✓[/green] MySQL table cache flushed")
                    except Exception as flush_err:
                        console.print(f"[yellow]⚠[/yellow]  Table flush skipped: {flush_err}")
                    
                    # Note: Flushing InnoDB buffer pool requires SUPER privilege
                    console.print("[dim]  (InnoDB buffer pool not flushed - requires SUPER privilege)[/dim]")
                    
                elif db_type == "postgresql":
                    # PostgreSQL doesn't have a direct command to flush buffer cache
                    console.print("[dim]  PostgreSQL buffer cache flush requires OS-level commands[/dim]")
                
                console.print()
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow]  RDBMS cache flush error: {e}\n")
    
    # Pre-populate Valkey (not timed)
    populate_valkey_leaderboards(leaderboard, cache_client, query_date)
    
    if interactive:
        console.print()
        if not Confirm.ask("Continue with performance comparison?", default=True):
            return
    
    # Run comparisons
    metrics_list = []
    
    # Test 1: Top 10 airports by flights
    print_section("TEST 1: Top 10 Airports by Flight Count")
    
    console.print("\n[cyan]Querying RDBMS...[/cyan]")
    rdbms_flights = query_rdbms_top_flights(leaderboard, query_date, 10)
    metrics_list.append(rdbms_flights)
    console.print(f"[green]✓[/green] RDBMS: {format_time_ms(rdbms_flights.latency_ms)}")
    
    console.print("\n[cyan]Querying Valkey...[/cyan]")
    valkey_flights = query_valkey_top_flights(cache_client, query_date, 10)
    metrics_list.append(valkey_flights)
    console.print(f"[green]✓[/green] Valkey: {format_time_ms(valkey_flights.latency_ms)}")
    
    speedup = rdbms_flights.latency_ms / valkey_flights.latency_ms if valkey_flights.latency_ms > 0 else 0
    console.print(f"\n[yellow]⚡ Speedup: {speedup:.1f}x faster with Valkey[/yellow]")
    
    # Show leaderboard results
    console.print()
    results_table = Table(title="🏆 Top 10 Airports by Flight Count", box=box.ROUNDED)
    results_table.add_column("Rank", style="cyan", justify="right")
    results_table.add_column("Airport", style="white")
    results_table.add_column("IATA", style="yellow", justify="center")
    results_table.add_column("Departures", style="green", justify="right")
    results_table.add_column("Arrivals", style="blue", justify="right")
    results_table.add_column("Total Flights", style="magenta bold", justify="right")
    
    top_flights = leaderboard.get_top_airports_by_flights(query_date, limit=10)
    for airport in top_flights:
        results_table.add_row(
            f"#{airport['rank']}",
            airport['name'],
            airport['iata'] or 'N/A',
            f"{airport['departures']:,}",
            f"{airport['arrivals']:,}",
            f"{airport['total_flights']:,}"
        )
    console.print(results_table)
    
    if interactive:
        console.print()
        if not Confirm.ask("Continue with next test?", default=True):
            console.print()
            console.print(create_comparison_table(metrics_list))
            return
    
    # Test 2: Top 10 airports by passengers
    print_section("TEST 2: Top 10 Airports by Passenger Count")
    
    console.print("\n[cyan]Querying RDBMS...[/cyan]")
    rdbms_passengers = query_rdbms_top_passengers(leaderboard, query_date, 10)
    metrics_list.append(rdbms_passengers)
    console.print(f"[green]✓[/green] RDBMS: {format_time_ms(rdbms_passengers.latency_ms)}")
    
    console.print("\n[cyan]Querying Valkey...[/cyan]")
    valkey_passengers = query_valkey_top_passengers(cache_client, query_date, 10)
    metrics_list.append(valkey_passengers)
    console.print(f"[green]✓[/green] Valkey: {format_time_ms(valkey_passengers.latency_ms)}")
    
    speedup = rdbms_passengers.latency_ms / valkey_passengers.latency_ms if valkey_passengers.latency_ms > 0 else 0
    console.print(f"\n[yellow]⚡ Speedup: {speedup:.1f}x faster with Valkey[/yellow]")
    
    # Show leaderboard results
    console.print()
    results_table = Table(title="🏆 Top 10 Airports by Passenger Count", box=box.ROUNDED)
    results_table.add_column("Rank", style="cyan", justify="right")
    results_table.add_column("Airport", style="white")
    results_table.add_column("IATA", style="yellow", justify="center")
    results_table.add_column("Departing", style="green", justify="right")
    results_table.add_column("Arriving", style="blue", justify="right")
    results_table.add_column("Total Passengers", style="magenta bold", justify="right")
    results_table.add_column("Flights", style="dim", justify="right")
    
    top_passengers = leaderboard.get_top_airports_by_passengers(query_date, limit=10)
    for airport in top_passengers:
        results_table.add_row(
            f"#{airport['rank']}",
            airport['name'],
            airport['iata'] or 'N/A',
            f"{airport['departing_passengers']:,}",
            f"{airport['arriving_passengers']:,}",
            f"{airport['total_passengers']:,}",
            f"{airport['total_flights']:,}"
        )
    console.print(results_table)
    
    if interactive:
        console.print()
        if not Confirm.ask("Continue with next test?", default=True):
            console.print()
            console.print(create_comparison_table(metrics_list))
            return
    
    # Test 3: Get rank for specific airport
    print_section("TEST 3: Get Rank for Specific Airport (JFK)")
    
    console.print("\n[cyan]Querying RDBMS...[/cyan]")
    rdbms_rank = query_rdbms_airport_rank(leaderboard, "JFK", query_date)
    metrics_list.append(rdbms_rank)
    console.print(f"[green]✓[/green] RDBMS: {format_time_ms(rdbms_rank.latency_ms)}")
    
    console.print("\n[cyan]Querying Valkey...[/cyan]")
    valkey_rank = query_valkey_airport_rank(cache_client, "JFK", query_date)
    metrics_list.append(valkey_rank)
    console.print(f"[green]✓[/green] Valkey: {format_time_ms(valkey_rank.latency_ms)}")
    
    speedup = rdbms_rank.latency_ms / valkey_rank.latency_ms if valkey_rank.latency_ms > 0 else 0
    console.print(f"\n[yellow]⚡ Speedup: {speedup:.1f}x faster with Valkey[/yellow]")
    
    # Show airport rank result
    console.print()
    jfk_data = leaderboard.get_airport_flights_on_date("JFK", query_date)
    if jfk_data:
        # Get rank from RDBMS
        all_airports = leaderboard.get_top_airports_by_flights(query_date, limit=1000)
        jfk_rank_rdbms = None
        for airport in all_airports:
            if airport['iata'] == 'JFK':
                jfk_rank_rdbms = airport['rank']
                break
        
        # Get rank from Valkey
        date_str = query_date.strftime("%Y-%m-%d")
        flights_key = f"leaderboard:flights:{date_str}"
        
        cursor = 0
        target_member = None
        while True:
            cursor, members = cache_client.client.zscan(
                cache_client.key(flights_key), 
                cursor=str(cursor), 
                match=f"JFK|*",
                count=100
            )
            if members:
                target_member = members[0][0] if isinstance(members[0], tuple) else members[0]
                break
            if cursor in {0, "0", b"0"}:
                break
        
        jfk_rank_valkey = None
        if target_member:
            jfk_rank_valkey = cache_client.client.zrevrank(cache_client.key(flights_key), target_member)
            if jfk_rank_valkey is not None:
                jfk_rank_valkey += 1  # Convert 0-based to 1-based rank
        
        results_table = Table(title="✈️ JFK Airport Ranking", box=box.ROUNDED)
        results_table.add_column("Metric", style="cyan bold")
        results_table.add_column("RDBMS", style="red", justify="right")
        results_table.add_column("Valkey", style="green", justify="right")
        
        results_table.add_row("Airport", f"{jfk_data['name']} ({jfk_data['iata']})", "")
        results_table.add_row("ICAO Code", jfk_data['icao'], "")
        
        if jfk_rank_rdbms or jfk_rank_valkey:
            results_table.add_row(
                "Rank by Flights", 
                f"#{jfk_rank_rdbms}" if jfk_rank_rdbms else "N/A",
                f"#{jfk_rank_valkey}" if jfk_rank_valkey else "N/A"
            )
        
        results_table.add_row("Departures", f"{jfk_data['departures']:,}", "")
        results_table.add_row("Arrivals", f"{jfk_data['arrivals']:,}", "")
        results_table.add_row("Total Flights", f"[bold]{jfk_data['total_flights']:,}[/bold]", "")
        
        console.print(results_table)
    
    # Summary
    print_section("PERFORMANCE SUMMARY")
    console.print()
    console.print(create_comparison_table(metrics_list))
    
    # Calculate overall stats
    total_rdbms_time = sum(m.latency_ms for m in metrics_list if m.source == "RDBMS")
    total_valkey_time = sum(m.latency_ms for m in metrics_list if m.source == "Valkey")
    overall_speedup = total_rdbms_time / total_valkey_time if total_valkey_time > 0 else 0
    
    console.print()
    summary_panel = Panel(
        f"[cyan]Total RDBMS Time:[/cyan] [red]{format_time_ms(total_rdbms_time)}[/red]\n"
        f"[cyan]Total Valkey Time:[/cyan] [green]{format_time_ms(total_valkey_time)}[/green]\n"
        f"[cyan]Overall Speedup:[/cyan] [yellow bold]{overall_speedup:.1f}x faster[/yellow bold]",
        title="📊 Overall Statistics",
        border_style="green",
        box=box.ROUNDED
    )
    console.print(summary_panel)
    
    # Cleanup
    leaderboard.close()
    cache_client.close()
    console.print("\n[dim]Connections closed[/dim]")


if __name__ == "__main__":
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]Demo interrupted by user[/yellow]")
        raise typer.Exit(0)
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)
