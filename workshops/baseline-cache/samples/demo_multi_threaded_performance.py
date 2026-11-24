#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Multi-threaded Performance Test Demo

This script demonstrates how to run performance tests against a MySQL database
with Valkey caching, simulating multiple concurrent users and capturing detailed
metrics in JSON format.

Usage:
    uv run python samples/demo_multi_threaded_performance.py --threads 4 --queries 10000 --read-ratio 80
    uv run python samples/demo_multi_threaded_performance.py --interactive --verbose --flush
    uv run python samples/demo_multi_threaded_performance.py --threads 10 --queries 50000 --read-ratio 90 --random
"""

import json
import random
import threading
import sys
import os
import time
from pathlib import Path
from datetime import datetime
from sqlalchemy import text
from dotenv import load_dotenv
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
from rich import box
from rich.prompt import Confirm, IntPrompt

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import get_db_engine, get_cache_client
from glide_sync import ExpirySet, ExpiryType

# Load environment variables
load_dotenv(os.environ.get("WORKSHOP_ENV_FILE", ".env"))

# Initialize typer app and rich console
app = typer.Typer(help="Multi-threaded Performance Test with Valkey Cache")
console = Console()

# Global verbose flag
VERBOSE = False


def print_section(title: str):
    """Print a formatted section header using rich."""
    console.print()
    console.print(Panel(f"[bold cyan]{title}[/bold cyan]", box=box.DOUBLE))


def print_verbose_info(query: str, cache_key: str, sample_passenger_id: int):
    """Print verbose information about queries and cache keys."""
    if not VERBOSE:
        return
    
    console.print("\n[dim]─── Sample Query Details ───[/dim]")
    console.print(Panel(
        f"[cyan]{query}[/cyan]",
        title="[bold]SQL Query Template[/bold]",
        border_style="dim",
        box=box.ROUNDED
    ))
    console.print(f"[dim]Cache Key Format:[/dim] [yellow]{cache_key}[/yellow]")
    console.print(f"[dim]Sample Passenger ID:[/dim] [yellow]{sample_passenger_id}[/yellow]")


class PerformanceTest:
    """Manages multi-threaded performance testing with metrics collection"""
    
    def __init__(self, threads: int, queries: int, read_ratio: int, ttl: int, random_passengers: bool):
        self.threads = threads
        self.queries = queries
        self.read_ratio = read_ratio / 100.0
        self.ttl = ttl
        self.random_passengers = random_passengers
        
        self.read_count = 0
        self.write_count = 0
        self.cache_hit = 0
        self.cache_miss = 0
        self.thread_metrics = {}
        self.lock = threading.Lock()
        
        # Database configuration from environment variables
        self.db_params = {
            "host": os.getenv('DB_HOST', "localhost"),
            "database": os.getenv('DB_NAME', "flughafendb_large"),
            "user": os.getenv('DB_USER', "root"),
            "password": os.getenv('DB_PASSWORD', ""),
            "port": int(os.getenv('DB_PORT', 3306)),
            "valkey_host": os.getenv('CACHE_HOST', 'localhost'),
            "valkey_port": int(os.getenv('CACHE_PORT', 6379)),
        }
        
        # SQL queries
        self.READ_QUERY = text("""
            SELECT p.firstname, p.lastname, COUNT(*) as booking_count
            FROM flughafendb_large.passenger p
            JOIN flughafendb_large.booking b ON p.passenger_id = b.passenger_id
            WHERE p.passenger_id = :passenger
            GROUP BY p.firstname, p.lastname
        """)
        
        self.WRITE_QUERY = text("""
            INSERT INTO flughafendb_large.booking (flight_id, passenger_id, price, seat)
            VALUES(:flight, :passenger, 1000.00, :seat)
        """)
        
        # Passenger pool for non-random mode
        self.passenger_pool = []
        
        # Flight pool for valid flight IDs
        self.flight_pool = []
        
        self._setup_connections()
    
    def _setup_connections(self):
        """Initialize database and cache connections"""
        try:
            # Database engines using core module
            self.engine_rw = get_db_engine(
                host=self.db_params['host'],
                port=str(self.db_params['port']),
                user=self.db_params['user'],
                password=self.db_params['password'],
                database=self.db_params['database'],
                pool_size=self.threads,
                max_overflow=50
            )
            self.engine_ro = get_db_engine(
                host=self.db_params['host'],
                port=str(self.db_params['port']),
                user=self.db_params['user'],
                password=self.db_params['password'],
                database=self.db_params['database'],
                pool_size=self.threads,
                max_overflow=50
            )
            
            # Test connections
            with self.engine_rw.connect() as connection:
                connection.execute(text("SELECT 1"))
            with self.engine_ro.connect() as connection:
                connection.execute(text("SELECT 1"))
            console.print("[green]✓[/green] Connected to MySQL database")
            
            # Valkey connections using core module
            cache_write = get_cache_client(
                host=os.getenv('CACHE_HOST', os.getenv('VALKEY_HOST', '127.0.0.1')),
                port=int(os.getenv('CACHE_PORT', os.getenv('VALKEY_PORT', '6379')))
            )
            cache_read = get_cache_client(
                host=os.getenv('CACHE_HOST', os.getenv('VALKEY_HOST', '127.0.0.1')),
                port=int(os.getenv('CACHE_PORT', os.getenv('VALKEY_PORT', '6379')))
            )
            
            # Get underlying clients for direct access (needed for performance testing)
            self.cache_write = cache_write
            self.valkey_write = cache_write.client
            self.cache_read = cache_read
            self.valkey_read = cache_read.client
            
            # Test Valkey connection
            self.valkey_write.ping()
            console.print("[green]✓[/green] Connected to Valkey cache")
            
            # Setup passenger pool if not using random mode
            if not self.random_passengers:
                self._setup_passenger_pool()
            
            # Always setup flight pool with valid flight IDs
            self._setup_flight_pool()
            
        except Exception as e:
            console.print(f"[red]✗ Connection error: {e}[/red]")
            sys.exit(1)
    
    def _setup_passenger_pool(self):
        """Setup a limited pool of passenger IDs for non-random mode"""
        console.print(f"\n[cyan]Setting up passenger pool...[/cyan]")
        pool_size = min(self.queries, 10000)  # Limit pool size
        self.passenger_pool = list(range(4, 4 + pool_size))
        console.print(f"[green]✓[/green] Passenger pool created: {len(self.passenger_pool)} IDs")
    
    def _setup_flight_pool(self):
        """Fetch valid flight IDs from database"""
        console.print(f"\n[cyan]Fetching valid flight IDs...[/cyan]")
        try:
            with self.engine_ro.connect() as conn:
                result = conn.execute(text("SELECT flight_id FROM flight LIMIT 10000"))
                self.flight_pool = [row[0] for row in result]
            console.print(f"[green]✓[/green] Flight pool created: {len(self.flight_pool)} valid IDs")
        except Exception as e:
            console.print(f"[red]✗ Failed to fetch flight IDs: {e}[/red]")
            # Fallback to a small range if query fails
            self.flight_pool = list(range(1, 1000))
    
    def _should_read(self):
        """Determine if operation should be read or write based on read_ratio"""
        return random.random() < self.read_ratio
    
    def _get_passenger_id(self):
        """Get passenger ID based on random mode"""
        if self.random_passengers:
            return random.randrange(4, 35000)
        else:
            return random.choice(self.passenger_pool)
    
    def _execute_read(self, engine, query):
        """Execute a read query"""
        with engine.connect() as conn:
            result = conn.execute(query).fetchall()
        return result
    
    def _execute_write(self, engine, query):
        """Execute a write query"""
        with engine.connect() as conn:
            result = conn.execute(query)
        return result
    
    def _record_metric(self, timestamp, query_time_ns, operation_type):
        """Thread-safe metric recording (stores nanoseconds internally)"""
        with self.lock:
            if timestamp not in self.thread_metrics:
                self.thread_metrics[timestamp] = {
                    "count": 0,
                    "total_time_ns": 0,
                    "min_time_ns": float('inf'),
                    "max_time_ns": 0,
                    "reads": 0,
                    "writes": 0,
                    "cache_hits": 0,
                    "cache_misses": 0
                }
            
            metrics = self.thread_metrics[timestamp]
            metrics["count"] += 1
            metrics["total_time_ns"] += query_time_ns
            metrics["min_time_ns"] = min(metrics["min_time_ns"], query_time_ns)
            metrics["max_time_ns"] = max(metrics["max_time_ns"], query_time_ns)
            
            if operation_type == "read":
                metrics["reads"] += 1
            elif operation_type == "write":
                metrics["writes"] += 1
            elif operation_type == "cache_hit":
                metrics["cache_hits"] += 1
            elif operation_type == "cache_miss":
                metrics["cache_misses"] += 1
    
    def worker_thread(self, progress_task=None, progress_obj=None):
        """Worker function executed by each thread"""
        for _ in range(self.queries):
            passenger_id = self._get_passenger_id()
            flight_id = random.choice(self.flight_pool) if self.flight_pool else random.randrange(1, 1000)
            seat = f"{random.randint(1, 99)}{random.choice('ABCDEFGHIJKL')}"  # Generate seat like "12A", "5C", etc.
            cache_key = f"bookings:{passenger_id}"
            
            start_time_ns = time.time_ns()
            
            if self._should_read():
                # Read operation with cache-aside pattern
                cached_data = self.valkey_read.get(self.cache_read.key(cache_key))
                
                if cached_data:
                    # Cache hit
                    with self.lock:
                        self.read_count += 1
                        self.cache_hit += 1
                    end_time_ns = time.time_ns()
                    query_time_ns = end_time_ns - start_time_ns
                    self._record_metric(str(int(start_time_ns // 1_000_000_000)), query_time_ns, "cache_hit")
                else:
                    # Cache miss - fetch from database
                    read_query = self.READ_QUERY.bindparams(passenger=passenger_id)
                    data = self._execute_read(self.engine_ro, read_query)
                    end_time_ns = time.time_ns()
                    
                    # Update cache with TTL
                    self.valkey_write.set(self.cache_write.key(cache_key), str(data), expiry=ExpirySet(ExpiryType.MILLSEC, self.ttl))
                    
                    query_time_ns = end_time_ns - start_time_ns
                    with self.lock:
                        self.read_count += 1
                        self.cache_miss += 1
                    self._record_metric(str(int(start_time_ns // 1_000_000_000)), query_time_ns, "cache_miss")
            else:
                # Write operation - try multiple times with different seats if duplicate
                max_retries = 5
                write_success = False
                
                for retry in range(max_retries):
                    try:
                        write_query = self.WRITE_QUERY.bindparams(flight=flight_id, passenger=passenger_id, seat=seat)
                        self._execute_write(self.engine_rw, write_query)
                        write_success = True
                        break
                    except Exception as e:
                        if "Duplicate entry" in str(e) and retry < max_retries - 1:
                            # Generate a new seat and retry
                            seat = f"{random.randint(1, 30)}{random.choice('ABCDEF')}"
                            continue
                        else:
                            # Skip this write operation if we can't find a unique seat
                            break
                
                if write_success:
                    # Update cache after write with TTL
                    read_query = self.READ_QUERY.bindparams(passenger=passenger_id)
                    data = self._execute_read(self.engine_ro, read_query)
                    self.valkey_write.set(self.cache_write.key(cache_key), str(data), expiry=ExpirySet(ExpiryType.MILLSEC, self.ttl))
                    
                    end_time_ns = time.time_ns()
                    query_time_ns = end_time_ns - start_time_ns
                    
                    with self.lock:
                        self.write_count += 1
                    self._record_metric(str(int(start_time_ns // 1_000_000_000)), query_time_ns, "write")
            
            # Update progress if available
            if progress_obj and progress_task is not None:
                progress_obj.update(progress_task, advance=1)
    
    def run(self, show_progress: bool = True):
        """Execute the performance test"""
        print_section("PERFORMANCE TEST CONFIGURATION")
        
        # Configuration table
        config_table = Table(box=box.SIMPLE, show_header=False)
        config_table.add_column("Parameter", style="cyan bold")
        config_table.add_column("Value", style="yellow")
        
        config_table.add_row("Threads", str(self.threads))
        config_table.add_row("Queries per thread", str(self.queries))
        config_table.add_row("Total queries", str(self.threads * self.queries))
        config_table.add_row("Read ratio", f"{int(self.read_ratio * 100)}%")
        config_table.add_row("Write ratio", f"{int((1 - self.read_ratio) * 100)}%")
        config_table.add_row("Cache TTL", f"{self.ttl} ms")
        config_table.add_row("Passenger mode", "Random (all)" if self.random_passengers else f"Pool ({len(self.passenger_pool)} IDs)")
        
        console.print(config_table)
        
        print_section("RUNNING PERFORMANCE TEST")
        
        # Create and start threads with progress bar
        threads = []
        test_start = time.time()
        total_operations = self.threads * self.queries
        
        if show_progress:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
                console=console
            ) as progress:
                task = progress.add_task(
                    f"[cyan]Processing {total_operations:,} operations...",
                    total=total_operations
                )
                
                for i in range(self.threads):
                    thread = threading.Thread(target=self.worker_thread, args=(task, progress))
                    threads.append(thread)
                    thread.start()
                
                # Wait for all threads to complete
                for thread in threads:
                    thread.join()
        else:
            console.print(f"\n[cyan]Starting {self.threads} threads...[/cyan]")
            for i in range(self.threads):
                thread = threading.Thread(target=self.worker_thread)
                threads.append(thread)
                thread.start()
            
            # Wait for all threads to complete
            for thread in threads:
                thread.join()
        
        test_end = time.time()
        total_duration = test_end - test_start
        
        console.print(f"\n[green]✓[/green] Test completed in {total_duration:.2f} seconds")
        
        # Display results
        self._display_results(total_duration)
        
        # Save results to JSON
        log_file = self._save_results(total_duration)
        
        return log_file
    
    def _display_results(self, duration):
        """Display test results using rich tables and termgraph"""
        total_queries = self.read_count + self.write_count
        
        print_section("PERFORMANCE TEST RESULTS")
        
        # Summary metrics table
        summary_table = Table(title="📊 Summary Metrics", box=box.ROUNDED, show_lines=True)
        summary_table.add_column("Metric", style="cyan bold")
        summary_table.add_column("Value", style="yellow", justify="right")
        
        summary_table.add_row("Total Duration", f"{duration:.2f} seconds")
        summary_table.add_row("Total Queries", f"{total_queries:,}")
        summary_table.add_row("Queries per Second", f"{total_queries / duration:,.2f}")
        summary_table.add_row("Avg Latency per Query", f"{(duration * 1000) / total_queries:.3f} ms")
        
        console.print(summary_table)
        
        # Operation breakdown table
        console.print()
        ops_table = Table(title="📈 Operation Breakdown", box=box.ROUNDED, show_lines=True)
        ops_table.add_column("Operation", style="cyan bold")
        ops_table.add_column("Count", style="yellow", justify="right")
        ops_table.add_column("Percentage", style="green", justify="right")
        
        ops_table.add_row("Reads", f"{self.read_count:,}", f"{self.read_count/total_queries*100:.1f}%")
        ops_table.add_row("Writes", f"{self.write_count:,}", f"{self.write_count/total_queries*100:.1f}%")
        
        console.print(ops_table)
        
        # Cache performance table
        console.print()
        cache_table = Table(title="⚡ Cache Performance", box=box.ROUNDED, show_lines=True)
        cache_table.add_column("Metric", style="cyan bold")
        cache_table.add_column("Count", style="yellow", justify="right")
        cache_table.add_column("Percentage", style="green", justify="right")
        
        cache_table.add_row("Cache Hits", f"{self.cache_hit:,}", 
                           f"{self.cache_hit/self.read_count*100:.1f}%" if self.read_count > 0 else "N/A")
        cache_table.add_row("Cache Misses", f"{self.cache_miss:,}", 
                           f"{self.cache_miss/self.read_count*100:.1f}%" if self.read_count > 0 else "N/A")
        cache_table.add_row("Total Reads", f"{self.read_count:,}", "100.0%")
        
        console.print(cache_table)
        
        # Simple bar chart visualization using rich
        console.print()
        console.print("[bold cyan]📊 Visual Breakdown:[/bold cyan]\n")
        
        # Operation breakdown bar
        read_bar_length = int((self.read_count / total_queries) * 50)
        write_bar_length = int((self.write_count / total_queries) * 50)
        
        console.print("[yellow]Operations:[/yellow]")
        console.print(f"  Reads  [{'█' * read_bar_length}{' ' * (50 - read_bar_length)}] {self.read_count:,}")
        console.print(f"  Writes [{'█' * write_bar_length}{' ' * (50 - write_bar_length)}] {self.write_count:,}")
        
        # Cache performance bar
        if self.read_count > 0:
            hit_bar_length = int((self.cache_hit / self.read_count) * 50)
            miss_bar_length = int((self.cache_miss / self.read_count) * 50)
            
            console.print("\n[green]Cache Performance:[/green]")
            console.print(f"  Hits   [{'█' * hit_bar_length}{' ' * (50 - hit_bar_length)}] {self.cache_hit:,}")
            console.print(f"  Misses [{'█' * miss_bar_length}{' ' * (50 - miss_bar_length)}] {self.cache_miss:,}")
    
    def _save_results(self, duration):
        """Save results to JSON log file"""
        # Ensure logs directory exists
        os.makedirs('logs', exist_ok=True)
        
        # Generate log filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = f"logs/perf_test_{timestamp}.json"
        
        # Calculate aggregate metrics (convert nanoseconds to microseconds for presentation)
        aggregate_metrics = {
            "avg_time_ns": 0,
            "min_time_ns": float('inf'),
            "max_time_ns": 0
        }
        
        for ts_metrics in self.thread_metrics.values():
            if ts_metrics["count"] > 0:
                avg_ns = ts_metrics["total_time_ns"] / ts_metrics["count"]
                aggregate_metrics["avg_time_ns"] += avg_ns
                aggregate_metrics["min_time_ns"] = min(aggregate_metrics["min_time_ns"], ts_metrics["min_time_ns"])
                aggregate_metrics["max_time_ns"] = max(aggregate_metrics["max_time_ns"], ts_metrics["max_time_ns"])
        
        if self.thread_metrics:
            aggregate_metrics["avg_time_ns"] /= len(self.thread_metrics)
        
        # Convert time series metrics to microseconds for presentation
        time_series_metrics_us = {}
        for ts, metrics in self.thread_metrics.items():
            time_series_metrics_us[ts] = {
                "count": metrics["count"],
                "total_time_us": round(metrics["total_time_ns"] / 1000, 2),
                "avg_time_us": round(metrics["total_time_ns"] / metrics["count"] / 1000, 2) if metrics["count"] > 0 else 0,
                "min_time_us": round(metrics["min_time_ns"] / 1000, 2),
                "max_time_us": round(metrics["max_time_ns"] / 1000, 2),
                "reads": metrics["reads"],
                "writes": metrics["writes"],
                "cache_hits": metrics["cache_hits"],
                "cache_misses": metrics["cache_misses"]
            }
        
        # Prepare output data
        output_data = {
            "test_config": {
                "threads": self.threads,
                "queries_per_thread": self.queries,
                "total_queries": self.threads * self.queries,
                "read_ratio": int(self.read_ratio * 100),
                "write_ratio": int((1 - self.read_ratio) * 100),
                "ttl_ms": self.ttl,
                "random_passengers": self.random_passengers,
                "passenger_pool_size": len(self.passenger_pool) if not self.random_passengers else "all"
            },
            "summary": {
                "total_duration_seconds": round(duration, 2),
                "total_queries": self.read_count + self.write_count,
                "queries_per_second": round((self.read_count + self.write_count) / duration, 2),
                "reads": self.read_count,
                "writes": self.write_count,
                "cache_hits": self.cache_hit,
                "cache_misses": self.cache_miss,
                "cache_hit_rate_percent": round(self.cache_hit / self.read_count * 100, 2) if self.read_count > 0 else 0
            },
            "aggregate_metrics": {
                "avg_query_time_us": round(aggregate_metrics["avg_time_ns"] / 1000, 2),
                "min_query_time_us": round(aggregate_metrics["min_time_ns"] / 1000, 2),
                "max_query_time_us": round(aggregate_metrics["max_time_ns"] / 1000, 2)
            },
            "time_series_metrics": time_series_metrics_us
        }
        
        # Write to file
        with open(log_file, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        console.print(f"\n[green]✓[/green] Results saved to: [cyan]{log_file}[/cyan]")
        return log_file


@app.command()
def run(
    threads: int = typer.Option(
        4,
        "--threads",
        "-t",
        help="Number of concurrent threads to simulate"
    ),
    queries: int = typer.Option(
        10000,
        "--queries",
        "-q",
        help="Number of queries per thread"
    ),
    read_ratio: int = typer.Option(
        80,
        "--read-ratio",
        "-r",
        help="Percentage of read operations (0-100)"
    ),
    ttl: int = typer.Option(
        300000,
        "--ttl",
        help="Cache TTL in milliseconds"
    ),
    random: bool = typer.Option(
        False,
        "--random",
        help="Use random passenger IDs (all passengers). If not set, uses limited pool"
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Run in interactive mode with prompts"
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show SQL query and cache key format with sample"
    ),
    flush: bool = typer.Option(
        False,
        "--flush",
        "-f",
        help="Flush Valkey cache before running test"
    )
):
    """
    Run multi-threaded performance test for MySQL + Valkey cache.
    
    Examples:
    
      # Basic test with defaults
      uv run python samples/demo_multi_threaded_performance.py
      
      # High concurrency test
      uv run python samples/demo_multi_threaded_performance.py --threads 20 --queries 50000
      
      # Write-heavy workload
      uv run python samples/demo_multi_threaded_performance.py --threads 10 --queries 10000 --read-ratio 30
      
      # Interactive mode with verbose output
      uv run python samples/demo_multi_threaded_performance.py --interactive --verbose --flush
      
      # Random passenger mode (all passengers)
      uv run python samples/demo_multi_threaded_performance.py --threads 8 --queries 20000 --random
    """
    
    # Set global verbose flag
    global VERBOSE
    VERBOSE = verbose
    
    # Validate parameters
    read_ratio = max(0, min(100, read_ratio))
    
    # Print header
    console.print()
    console.print(Panel.fit(
        "[bold cyan]MULTI-THREADED PERFORMANCE TEST[/bold cyan]\n"
        "[yellow]MySQL Database + Valkey Cache Performance Analysis[/yellow]",
        border_style="cyan",
        box=box.DOUBLE
    ))
    
    # Interactive mode - allow parameter customization
    if interactive:
        console.print("\n[bold yellow]Interactive Mode:[/bold yellow] Customize test parameters\n")
        
        if Confirm.ask("Would you like to customize test parameters?", default=False):
            threads = IntPrompt.ask("Number of threads", default=threads)
            queries = IntPrompt.ask("Queries per thread", default=queries)
            read_ratio = IntPrompt.ask("Read ratio (0-100)", default=read_ratio)
            ttl = IntPrompt.ask("Cache TTL (milliseconds)", default=ttl)
            random = Confirm.ask("Use random passenger IDs?", default=random)
            flush = Confirm.ask("Flush cache before test?", default=flush)
    
    # Initialize test with progress indicator
    console.print()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Initializing performance test...", total=None)
        test = PerformanceTest(threads, queries, read_ratio, ttl, random)
        progress.update(task, completed=True)
    
    # Flush cache if requested
    if flush:
        console.print("\n[yellow]🧹 Flushing Valkey cache...[/yellow]")
        try:
            test.cache_write.flush_all()
            console.print("[green]✓[/green] Cache flushed successfully")
        except Exception as e:
            console.print(f"[red]❌ Error flushing cache: {e}[/red]")
    
    # Show verbose information
    if verbose:
        sample_passenger_id = test._get_passenger_id()
        cache_key = f"bookings:{sample_passenger_id}"
        query = str(test.READ_QUERY).strip()
        print_verbose_info(query, cache_key, sample_passenger_id)
    
    # Confirm start in interactive mode
    if interactive:
        console.print()
        if not Confirm.ask("Start performance test?", default=True):
            console.print("[yellow]Test cancelled[/yellow]")
            return
    
    # Run the test
    try:
        log_file = test.run(show_progress=True)
        
        # Final summary
        print_section("TEST COMPLETE")
        console.print("\n[green]✅ Performance test completed successfully![/green]\n")
        
        # Key takeaways
        takeaways_table = Table(title="💡 Key Insights", box=box.ROUNDED, show_header=False)
        takeaways_table.add_column("", style="cyan")
        takeaways_table.add_row("• Multi-threaded execution simulates real-world concurrent load")
        takeaways_table.add_row("• Cache-aside pattern significantly reduces database load")
        takeaways_table.add_row("• Higher cache hit rates = better performance")
        takeaways_table.add_row("• TTL controls cache freshness vs performance trade-off")
        takeaways_table.add_row(f"• Results saved to: {log_file}")
        
        console.print(takeaways_table)
        console.print()
        
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠ Test interrupted by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]❌ Test failed: {e}[/red]")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    app()
