"""
Stampede Prevention Demo - Distributed Locking for Cache Stampede

This demo showcases how distributed locking prevents cache stampede when multiple
concurrent requests try to fetch the same data. It simulates high-traffic scenarios
for major cities where many clients request weather data simultaneously.

Key Features:
- Distributed locking with Redis/Valkey
- Exponential backoff for lock contention
- Fail-fast behavior when lock is held
- Concurrent request simulation
- Performance metrics and visualization
"""

import sys
import time
import random
import json
import threading
from pathlib import Path
from typing import Any, Optional, List, Dict
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich import box
from rich.prompt import Confirm
from rich.live import Live
from rich.layout import Layout
from tqdm import tqdm

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from daos.weather_api_cache import WeatherAPICache
from services.weather_service import WeatherService

# Initialize typer app and rich console
app = typer.Typer(help="Stampede Prevention Demo with Distributed Locking")
console = Console()

# Global verbose flag
VERBOSE = False


@dataclass
class RequestMetrics:
    """Metrics for a single request."""
    thread_id: int
    city_name: str
    cache_key: str
    start_time: float
    end_time: float = 0.0
    status: str = "pending"
    lock_acquired: bool = False
    wait_time: float = 0.0
    retries: int = 0
    api_called: bool = False
    
    @property
    def duration(self) -> float:
        """Total duration of the request."""
        if self.end_time > 0:
            return self.end_time - self.start_time
        return 0.0
    
    @property
    def status_emoji(self) -> str:
        """Get emoji for status."""
        status_map = {
            "pending": "⏳",
            "cache_hit": "✓",
            "cache_miss_locked": "🔒",
            "cache_miss_api": "⚡",
            "lock_wait": "⏱️",
            "timeout": "⏰",
            "error": "❌"
        }
        return status_map.get(self.status, "❓")


@dataclass
class StampedeMetrics:
    """Aggregate metrics for stampede prevention test."""
    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    api_calls: int = 0
    lock_acquisitions: int = 0
    lock_waits: int = 0
    timeouts: int = 0
    errors: int = 0
    total_wait_time: float = 0.0
    request_details: List[RequestMetrics] = field(default_factory=list)
    
    @property
    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate."""
        if self.total_requests == 0:
            return 0.0
        return (self.cache_hits / self.total_requests) * 100
    
    @property
    def avg_wait_time(self) -> float:
        """Calculate average wait time."""
        if self.lock_waits == 0:
            return 0.0
        return self.total_wait_time / self.lock_waits
    
    @property
    def stampede_prevented(self) -> bool:
        """Check if stampede was prevented (0 or 1 API call for concurrent requests)."""
        return self.api_calls <= 1 and self.total_requests > 1
    
    @property
    def min_latency(self) -> float:
        """Get minimum latency across all requests."""
        if not self.request_details:
            return 0.0
        return min(req.duration for req in self.request_details if req.duration > 0)
    
    @property
    def max_latency(self) -> float:
        """Get maximum latency across all requests."""
        if not self.request_details:
            return 0.0
        return max(req.duration for req in self.request_details if req.duration > 0)
    
    @property
    def avg_latency(self) -> float:
        """Get average latency across all requests."""
        if not self.request_details:
            return 0.0
        durations = [req.duration for req in self.request_details if req.duration > 0]
        return sum(durations) / len(durations) if durations else 0.0
    
    @property
    def cache_hit_latency(self) -> float:
        """Get average latency for cache hits."""
        cache_hits = [req.duration for req in self.request_details 
                     if req.status == "cache_hit" and req.duration > 0]
        return sum(cache_hits) / len(cache_hits) if cache_hits else 0.0
    
    @property
    def api_call_latency(self) -> float:
        """Get average latency for API calls."""
        api_calls = [req.duration for req in self.request_details 
                    if req.status == "cache_miss_api" and req.duration > 0]
        return sum(api_calls) / len(api_calls) if api_calls else 0.0


def format_time(seconds: float) -> str:
    """Format time in a human-readable way."""
    if seconds < 1:
        return f"{seconds * 1000:.1f}ms"
    return f"{seconds:.3f}s"


def get_country_flag(country_code: str) -> str:
    """Convert country code to flag emoji."""
    flag_map = {
        'US': '🇺🇸', 'MX': '🇲🇽', 'CA': '🇨🇦', 'GB': '🇬🇧', 'FR': '🇫🇷',
        'DE': '🇩🇪', 'IT': '🇮🇹', 'ES': '🇪🇸', 'JP': '🇯🇵', 'CN': '🇨🇳',
        'BR': '🇧🇷', 'AR': '🇦🇷', 'AU': '🇦🇺', 'IN': '🇮🇳', 'RU': '🇷🇺',
        'KR': '🇰🇷', 'NL': '🇳🇱', 'SE': '🇸🇪', 'NO': '🇳🇴', 'DK': '🇩🇰',
        'FI': '🇫🇮', 'PL': '🇵🇱', 'CH': '🇨🇭', 'AT': '🇦🇹', 'BE': '🇧🇪',
        'PT': '🇵🇹', 'GR': '🇬🇷', 'CZ': '🇨🇿', 'IE': '🇮🇪', 'NZ': '🇳🇿',
        'SG': '🇸🇬', 'HK': '🇭🇰', 'TH': '🇹🇭', 'MY': '🇲🇾', 'ID': '🇮🇩',
        'PH': '🇵🇭', 'VN': '🇻🇳', 'ZA': '🇿🇦', 'EG': '🇪🇬', 'TR': '🇹🇷',
        'SA': '🇸🇦', 'AE': '🇦🇪', 'IL': '🇮🇱', 'CL': '🇨🇱', 'CO': '🇨🇴',
        'PE': '🇵🇪', 'VE': '🇻🇪', 'UA': '🇺🇦', 'RO': '🇷🇴', 'HU': '🇭🇺',
    }
    return flag_map.get(country_code.upper(), '🏳️')


def get_weather_emoji(weather_data: dict) -> str:
    """Get weather emoji based on weather condition."""
    if not weather_data:
        return '❓'
    
    weather_list = weather_data.get('weather', [])
    if not weather_list:
        return '❓'
    
    weather_info = weather_list[0] if isinstance(weather_list, list) else weather_list
    description = weather_info.get('description', '').lower()
    main = weather_info.get('main', '').lower()
    
    if 'clear' in main or 'clear' in description:
        return '☀️'
    elif 'cloud' in main or 'cloud' in description:
        if 'few' in description or 'scattered' in description:
            return '🌤️'
        elif 'broken' in description or 'overcast' in description:
            return '☁️'
        return '⛅'
    elif 'rain' in main or 'rain' in description or 'drizzle' in main:
        if 'light' in description:
            return '🌦️'
        return '🌧️'
    elif 'thunder' in main or 'thunder' in description:
        return '⛈️'
    elif 'snow' in main or 'snow' in description:
        return '🌨️'
    elif 'mist' in main or 'fog' in main or 'haze' in main:
        return '🌫️'
    elif 'wind' in description:
        return '💨'
    else:
        return '🌡️'


def format_weather_details(weather_data: dict) -> str:
    """Format weather details in a compact string."""
    if not weather_data:
        return "N/A"
    
    temp = weather_data.get('main', {}).get('temp', 'N/A')
    feels_like = weather_data.get('main', {}).get('feels_like', 'N/A')
    
    weather_list = weather_data.get('weather', [])
    if weather_list:
        weather_info = weather_list[0] if isinstance(weather_list, list) else weather_list
        description = weather_info.get('description', 'N/A')
    else:
        description = 'N/A'
    
    if temp != 'N/A':
        temp_str = f"{temp:.1f}°F"
        feels_str = f"feels {feels_like:.1f}°F" if feels_like != 'N/A' else ""
        return f"{temp_str} ({feels_str}), {description}"
    return description


def print_section(title: str):
    """Print a formatted section header."""
    console.print()
    console.print(Panel(f"[bold cyan]{title}[/bold cyan]", box=box.DOUBLE))


def fetch_weather_with_stampede_protection(
    city: Dict[str, str],
    cache: WeatherAPICache,
    thread_id: int,
    metrics: StampedeMetrics,
    lock_ttl_seconds: float = 60.0,
    max_retries: int = 5,
    base_delay: float = 0.1
) -> Optional[Dict[str, Any]]:
    """
    Fetch weather data with stampede protection using distributed locking.
    
    Args:
        city: City information (name, country, zip)
        cache: Weather API cache instance
        thread_id: Thread identifier
        metrics: Shared metrics object
        lock_ttl_seconds: Lock TTL in seconds
        max_retries: Maximum number of retries for lock acquisition
        base_delay: Base delay for exponential backoff (seconds)
    
    Returns:
        Weather data or None on error
    """
    cache_key = f"weather:{city['country'].lower()}:{city['zip']}"
    request_metric = RequestMetrics(
        thread_id=thread_id,
        city_name=city['name'],
        cache_key=cache_key,
        start_time=time.time()
    )
    
    try:
        # Try to get from cache first
        cached_data = cache.get(cache_key)
        
        if cached_data:
            # Cache hit - no lock needed
            request_metric.status = "cache_hit"
            request_metric.end_time = time.time()
            metrics.cache_hits += 1
            metrics.request_details.append(request_metric)
            
            if VERBOSE:
                console.print(
                    f"[green]Thread {thread_id:2d}:[/green] "
                    f"Cache HIT for {city['name']} - {format_time(request_metric.duration)}"
                )
            
            return cached_data
        
        # Cache miss - try to acquire lock with configurable TTL
        lock_token = cache.acquire_lock(cache_key, timeout=int(lock_ttl_seconds))
        
        if lock_token:
            # We got the lock - we're responsible for fetching
            request_metric.lock_acquired = True
            metrics.lock_acquisitions += 1
            
            try:
                # Double-check cache after acquiring lock
                cached_data = cache.get(cache_key)
                if cached_data:
                    request_metric.status = "cache_hit"
                    request_metric.end_time = time.time()
                    metrics.cache_hits += 1
                    
                    if VERBOSE:
                        console.print(
                            f"[green]Thread {thread_id:2d}:[/green] "
                            f"Cache HIT (after lock) for {city['name']}"
                        )
                    
                    return cached_data
                
                # Fetch from API
                if VERBOSE:
                    console.print(
                        f"[yellow]Thread {thread_id:2d}:[/yellow] "
                        f"Fetching from API for {city['name']}..."
                    )
                
                weather_data = WeatherService.get_weather(city['country'], city['zip'])
                cache.set(cache_key, weather_data)
                
                request_metric.status = "cache_miss_api"
                request_metric.api_called = True
                request_metric.end_time = time.time()
                metrics.cache_misses += 1
                metrics.api_calls += 1
                
                if VERBOSE:
                    console.print(
                        f"[cyan]Thread {thread_id:2d}:[/cyan] "
                        f"API call completed for {city['name']} - {format_time(request_metric.duration)}"
                    )
                
                return weather_data
                
            finally:
                # Always release the lock
                cache.release_lock(cache_key, lock_token)
        
        else:
            # Could not acquire lock - another thread is fetching
            # Use exponential backoff to retry
            request_metric.status = "lock_wait"
            metrics.lock_waits += 1
            
            if VERBOSE:
                console.print(
                    f"[yellow]Thread {thread_id:2d}:[/yellow] "
                    f"Lock held by another thread for {city['name']}, waiting..."
                )
            
            wait_start = time.time()
            
            for retry in range(max_retries):
                # Exponential backoff: base_delay * 2^retry + random jitter
                delay = base_delay * (2 ** retry) + random.uniform(0, 0.1)
                time.sleep(delay)
                
                request_metric.retries += 1
                
                # Try to get from cache
                cached_data = cache.get(cache_key)
                if cached_data:
                    request_metric.wait_time = time.time() - wait_start
                    request_metric.status = "cache_hit"
                    request_metric.end_time = time.time()
                    metrics.cache_hits += 1
                    metrics.total_wait_time += request_metric.wait_time
                    
                    if VERBOSE:
                        console.print(
                            f"[green]Thread {thread_id:2d}:[/green] "
                            f"Cache HIT after {request_metric.retries} retries "
                            f"({format_time(request_metric.wait_time)} wait) for {city['name']}"
                        )
                    
                    return cached_data
            
            # Timeout - fail fast
            request_metric.status = "timeout"
            request_metric.end_time = time.time()
            metrics.timeouts += 1
            
            if VERBOSE:
                console.print(
                    f"[red]Thread {thread_id:2d}:[/red] "
                    f"Timeout after {max_retries} retries for {city['name']}"
                )
            
            return None
    
    except Exception as e:
        request_metric.status = "error"
        request_metric.end_time = time.time()
        metrics.errors += 1
        
        if VERBOSE:
            console.print(f"[red]Thread {thread_id:2d}:[/red] Error: {e}")
        
        return None
    
    finally:
        metrics.request_details.append(request_metric)


def simulate_concurrent_requests(
    city: Dict[str, str],
    cache: WeatherAPICache,
    num_requests: int = 1000,
    num_threads: int = 4,
    lock_ttl_ms: int = 60000
) -> StampedeMetrics:
    """
    Simulate concurrent requests to the same resource using a thread pool.
    
    Args:
        city: City information
        cache: Weather API cache instance
        num_requests: Number of concurrent requests to simulate
        num_threads: Number of worker threads to use
        lock_ttl_ms: Lock TTL in milliseconds
    
    Returns:
        Aggregate metrics
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    metrics = StampedeMetrics(total_requests=num_requests)
    
    # Convert lock TTL from milliseconds to seconds
    lock_ttl_seconds = lock_ttl_ms / 1000
    
    # Use ThreadPoolExecutor for better thread management
    start_time = time.time()
    
    # Create progress bar
    with tqdm(
        total=num_requests,
        desc=f"Processing {num_requests} requests",
        unit="req",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        disable=VERBOSE  # Disable if verbose mode is on
    ) as pbar:
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            # Submit all requests
            futures = []
            for i in range(num_requests):
                future = executor.submit(
                    fetch_weather_with_stampede_protection,
                    city, cache, i + 1, metrics, lock_ttl_seconds
                )
                futures.append(future)
            
            # Wait for all to complete and update progress
            for future in as_completed(futures):
                try:
                    future.result()
                    pbar.update(1)
                    
                    # Update progress bar description with current stats
                    cache_hits = metrics.cache_hits
                    api_calls = metrics.api_calls
                    pbar.set_postfix_str(
                        f"Cache: {cache_hits}, API: {api_calls}, "
                        f"Hit Rate: {(cache_hits / (cache_hits + api_calls) * 100) if (cache_hits + api_calls) > 0 else 0:.1f}%"
                    )
                except Exception as e:
                    pbar.update(1)
                    if VERBOSE:
                        console.print(f"[red]Request failed: {e}[/red]")
    
    total_time = time.time() - start_time
    
    if VERBOSE:
        console.print(f"\n[dim]All requests completed in {format_time(total_time)} using {num_threads} threads[/dim]")
    
    return metrics


def create_metrics_table(metrics: StampedeMetrics, city_name: str) -> Table:
    """Create a rich table with metrics."""
    table = Table(
        title=f"📊 Stampede Prevention Metrics - {city_name}",
        box=box.ROUNDED,
        show_lines=True
    )
    
    table.add_column("Metric", style="cyan bold")
    table.add_column("Value", style="white", justify="right")
    table.add_column("Details", style="dim")
    
    table.add_row(
        "Total Requests",
        f"[white]{metrics.total_requests}[/white]",
        "Concurrent threads"
    )
    
    table.add_row(
        "Cache Hits",
        f"[green]{metrics.cache_hits}[/green]",
        f"{metrics.cache_hit_rate:.1f}% hit rate"
    )
    
    table.add_row(
        "Cache Misses",
        f"[yellow]{metrics.cache_misses}[/yellow]",
        "Required API call"
    )
    
    table.add_row(
        "API Calls",
        f"[cyan bold]{metrics.api_calls}[/cyan bold]",
        "🎯 Should be 1 for stampede prevention"
    )
    
    table.add_row(
        "Lock Acquisitions",
        f"[magenta]{metrics.lock_acquisitions}[/magenta]",
        "Threads that got the lock"
    )
    
    table.add_row(
        "Lock Waits",
        f"[yellow]{metrics.lock_waits}[/yellow]",
        f"Avg wait: {format_time(metrics.avg_wait_time)}"
    )
    
    if metrics.timeouts > 0:
        table.add_row(
            "Timeouts",
            f"[red]{metrics.timeouts}[/red]",
            "Failed to get data"
        )
    
    if metrics.errors > 0:
        table.add_row(
            "Errors",
            f"[red]{metrics.errors}[/red]",
            "Request errors"
        )
    
    # Add stampede prevention status
    if metrics.stampede_prevented:
        if metrics.api_calls == 0:
            table.add_row(
                "Stampede Prevention",
                "[green bold]✓ SUCCESS[/green bold]",
                "All requests served from cache"
            )
        else:
            table.add_row(
                "Stampede Prevention",
                "[green bold]✓ SUCCESS[/green bold]",
                "Only 1 API call for all requests"
            )
    else:
        table.add_row(
            "Stampede Prevention",
            "[red bold]✗ FAILED[/red bold]",
            f"{metrics.api_calls} API calls made"
        )
    
    # Add latency metrics
    table.add_row("", "", "")  # Separator
    table.add_row(
        "Min Latency",
        f"[cyan]{format_time(metrics.min_latency)}[/cyan]",
        "Fastest request"
    )
    
    table.add_row(
        "Avg Latency",
        f"[cyan]{format_time(metrics.avg_latency)}[/cyan]",
        "Average across all requests"
    )
    
    table.add_row(
        "Max Latency",
        f"[cyan]{format_time(metrics.max_latency)}[/cyan]",
        "Slowest request (likely API call)"
    )
    
    # Show cache vs API latency comparison if both exist
    if metrics.cache_hits > 0 and metrics.api_calls > 0:
        speedup = metrics.api_call_latency / metrics.cache_hit_latency if metrics.cache_hit_latency > 0 else 0
        table.add_row("", "", "")  # Separator
        table.add_row(
            "Cache Hit Latency",
            f"[green]{format_time(metrics.cache_hit_latency)}[/green]",
            "Average for cached data"
        )
        table.add_row(
            "API Call Latency",
            f"[yellow]{format_time(metrics.api_call_latency)}[/yellow]",
            "Average for API calls"
        )
        table.add_row(
            "Cache Speedup",
            f"[green bold]{speedup:.1f}x faster[/green bold]",
            "Cache vs API performance"
        )
    
    return table


def create_request_timeline_table(metrics: StampedeMetrics) -> Table:
    """Create a timeline table showing request details."""
    table = Table(
        title="⏱️ Request Timeline",
        box=box.ROUNDED,
        show_header=True
    )
    
    table.add_column("Thread", style="dim", justify="right")
    table.add_column("Status", style="white")
    table.add_column("Duration", style="magenta", justify="right")
    table.add_column("Lock", style="cyan", justify="center")
    table.add_column("Retries", style="yellow", justify="right")
    table.add_column("Wait Time", style="yellow", justify="right")
    
    # Sort by start time
    sorted_requests = sorted(metrics.request_details, key=lambda x: x.start_time)
    
    for req in sorted_requests:
        status_color = {
            "cache_hit": "green",
            "cache_miss_api": "cyan",
            "lock_wait": "yellow",
            "timeout": "red",
            "error": "red"
        }.get(req.status, "white")
        
        status_text = {
            "cache_hit": "Cache Hit",
            "cache_miss_api": "API Call",
            "lock_wait": "Lock Wait",
            "timeout": "Timeout",
            "error": "Error"
        }.get(req.status, req.status)
        
        lock_icon = "🔒" if req.lock_acquired else "⏳" if req.status == "lock_wait" else "—"
        
        table.add_row(
            f"{req.thread_id}",
            f"{req.status_emoji} [{status_color}]{status_text}[/{status_color}]",
            format_time(req.duration),
            lock_icon,
            str(req.retries) if req.retries > 0 else "—",
            format_time(req.wait_time) if req.wait_time > 0 else "—"
        )
    
    return table


def run_stampede_test(
    city: Dict[str, str],
    cache: WeatherAPICache,
    num_requests: int = 1000,
    num_threads: int = 4,
    lock_ttl_ms: int = 60000,
    test_number: int = 1
) -> StampedeMetrics:
    """Run a single stampede prevention test."""
    print_section(f"TEST #{test_number}: {city['name']}, {city['country']} ({num_requests} concurrent requests)")
    
    console.print(f"[dim]Cache key: weather:{city['country'].lower()}:{city['zip']}[/dim]")
    console.print(f"[dim]Simulating {num_requests} concurrent requests using {num_threads} worker threads...[/dim]")
    console.print(f"[dim]Lock TTL: {lock_ttl_ms}ms ({lock_ttl_ms/1000:.1f}s)[/dim]\n")
    
    # Run the test (tqdm progress bar is shown inside simulate_concurrent_requests)
    metrics = simulate_concurrent_requests(city, cache, num_requests, num_threads, lock_ttl_ms)
    
    # Get weather data from cache to display
    cache_key = f"weather:{city['country'].lower()}:{city['zip']}"
    weather_data = cache.get(cache_key)
    
    # Display weather result
    if weather_data:
        console.print()
        country_flag = get_country_flag(city['country'])
        weather_emoji = get_weather_emoji(weather_data)
        weather_details = format_weather_details(weather_data)
        
        console.print(
            f"  ✓ {weather_emoji} [cyan]{city['name']:20s}[/cyan] "
            f"{country_flag} [yellow]{city['country']}[/yellow] - "
            f"[white]{weather_details}[/white]"
        )
    
    # Display results
    console.print()
    console.print(create_metrics_table(metrics, city['name']))
    
    if VERBOSE:
        console.print()
        console.print(create_request_timeline_table(metrics))
    
    return metrics


def run_demo(
    num_requests: int = 1000,
    num_threads: int = 4,
    num_cities: int = 3,
    lock_ttl_ms: int = 60000,
    interactive: bool = False,
    flush: bool = False
):
    """
    Run the stampede prevention demo.
    
    Args:
        num_requests: Number of concurrent requests per city
        num_threads: Number of worker threads to use
        num_cities: Number of cities to test
        lock_ttl_ms: Lock TTL in milliseconds
        interactive: Run step-by-step with prompts
        flush: Flush cache before running demo
    """
    # Print header
    console.print()
    console.print(Panel.fit(
        "[bold cyan]STAMPEDE PREVENTION DEMO[/bold cyan]\n"
        "[yellow]Distributed Locking for Cache Stampede Prevention[/yellow]",
        border_style="cyan",
        box=box.DOUBLE
    ))
    
    # Show configuration
    config_table = Table(title="Configuration", box=box.ROUNDED, show_header=False)
    config_table.add_column("Setting", style="cyan bold")
    config_table.add_column("Value", style="white")
    
    config_table.add_row("Concurrent requests per city", str(num_requests))
    config_table.add_row("Worker threads", str(num_threads))
    config_table.add_row("Number of cities", str(num_cities))
    
    # Show lock TTL with warning if too small
    lock_ttl_seconds = lock_ttl_ms / 1000
    if lock_ttl_ms < 1000:
        config_table.add_row(
            "Lock TTL", 
            f"[yellow]{lock_ttl_ms}ms ({lock_ttl_seconds:.1f}s) ⚠️[/yellow]"
        )
    else:
        config_table.add_row("Lock TTL", f"{lock_ttl_ms}ms ({lock_ttl_seconds:.1f}s)")
    
    config_table.add_row("Max retries", "5")
    config_table.add_row("Backoff strategy", "Exponential (0.1s base)")
    config_table.add_row("Verbose mode", "Enabled" if VERBOSE else "Disabled")
    
    console.print()
    console.print(config_table)
    
    # Initialize cache
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Initializing cache connection...", total=None)
        cache = WeatherAPICache(default_ttl=900, verbose=VERBOSE)
        progress.update(task, completed=True)
    
    console.print("[green]✓[/green] Connected to cache\n")
    
    # Flush cache if requested
    if flush:
        console.print("[yellow]🧹 Flushing cache...[/yellow]")
        try:
            cache.clear()
            console.print("[green]✓[/green] Cache flushed successfully\n")
        except Exception as e:
            console.print(f"[red]❌ Error flushing cache: {e}[/red]\n")
    
    # Select major cities (high-traffic scenarios)
    major_cities = [
        {"name": "New York", "country": "US", "zip": "10001"},
        {"name": "Los Angeles", "country": "US", "zip": "90001"},
        {"name": "Chicago", "country": "US", "zip": "60601"},
        {"name": "Houston", "country": "US", "zip": "77001"},
        {"name": "Miami", "country": "US", "zip": "33101"},
    ]
    
    cities = random.sample(major_cities, min(num_cities, len(major_cities)))
    
    # Show selected cities
    cities_table = Table(title="Selected Major Cities", box=box.ROUNDED)
    cities_table.add_column("#", style="dim", justify="right")
    cities_table.add_column("City", style="cyan")
    cities_table.add_column("ZIP", style="white")
    cities_table.add_column("Expected Traffic", style="yellow")
    
    for i, city in enumerate(cities, 1):
        cities_table.add_row(
            str(i),
            f"🏙️ {city['name']}, {city['country']}",
            city['zip'],
            f"{num_requests} concurrent requests"
        )
    
    console.print()
    console.print(cities_table)
    
    # Run tests
    all_metrics = []
    
    for i, city in enumerate(cities, 1):
        if interactive and i > 1:
            console.print()
            if not Confirm.ask(f"Continue with test #{i}?", default=True):
                break
        
        metrics = run_stampede_test(city, cache, num_requests, num_threads, lock_ttl_ms, i)
        all_metrics.append(metrics)
        
        if not interactive:
            time.sleep(1)  # Brief pause between tests
    
    # Summary
    print_section("OVERALL SUMMARY")
    
    # Aggregate metrics
    total_requests = sum(m.total_requests for m in all_metrics)
    total_api_calls = sum(m.api_calls for m in all_metrics)
    total_cache_hits = sum(m.cache_hits for m in all_metrics)
    total_lock_waits = sum(m.lock_waits for m in all_metrics)
    total_timeouts = sum(m.timeouts for m in all_metrics)
    successful_preventions = sum(1 for m in all_metrics if m.stampede_prevented)
    
    summary_table = Table(title="📈 Aggregate Results", box=box.ROUNDED, show_lines=True)
    summary_table.add_column("Metric", style="cyan bold")
    summary_table.add_column("Value", style="white", justify="right")
    summary_table.add_column("Analysis", style="dim")
    
    summary_table.add_row(
        "Total Tests",
        f"[white]{len(all_metrics)}[/white]",
        f"{num_cities} cities tested"
    )
    
    summary_table.add_row(
        "Total Requests",
        f"[white]{total_requests}[/white]",
        f"{total_requests // len(all_metrics)} per city"
    )
    
    summary_table.add_row(
        "Total API Calls",
        f"[cyan bold]{total_api_calls}[/cyan bold]",
        f"🎯 Ideal: {len(all_metrics)} (1 per city)"
    )
    
    summary_table.add_row(
        "API Call Reduction",
        f"[green bold]{((total_requests - total_api_calls) / total_requests * 100):.1f}%[/green bold]",
        f"Prevented {total_requests - total_api_calls} unnecessary calls"
    )
    
    summary_table.add_row(
        "Cache Hits",
        f"[green]{total_cache_hits}[/green]",
        f"{(total_cache_hits / total_requests * 100):.1f}% hit rate"
    )
    
    summary_table.add_row(
        "Lock Waits",
        f"[yellow]{total_lock_waits}[/yellow]",
        "Threads that waited for lock"
    )
    
    if total_timeouts > 0:
        summary_table.add_row(
            "Timeouts",
            f"[red]{total_timeouts}[/red]",
            "Consider increasing max retries"
        )
    
    summary_table.add_row(
        "Stampede Prevention Success",
        f"[green bold]{successful_preventions}/{len(all_metrics)}[/green bold]",
        "Tests with only 1 API call"
    )
    
    # Add aggregate latency metrics
    all_durations = []
    cache_hit_durations = []
    api_call_durations = []
    
    for m in all_metrics:
        for req in m.request_details:
            if req.duration > 0:
                all_durations.append(req.duration)
                if req.status == "cache_hit":
                    cache_hit_durations.append(req.duration)
                elif req.status == "cache_miss_api":
                    api_call_durations.append(req.duration)
    
    if all_durations:
        summary_table.add_row("", "", "")  # Separator
        summary_table.add_row(
            "Min Latency",
            f"[cyan]{format_time(min(all_durations))}[/cyan]",
            "Fastest request overall"
        )
        summary_table.add_row(
            "Avg Latency",
            f"[cyan]{format_time(sum(all_durations) / len(all_durations))}[/cyan]",
            "Average across all requests"
        )
        summary_table.add_row(
            "Max Latency",
            f"[cyan]{format_time(max(all_durations))}[/cyan]",
            "Slowest request overall"
        )
    
    if cache_hit_durations and api_call_durations:
        avg_cache = sum(cache_hit_durations) / len(cache_hit_durations)
        avg_api = sum(api_call_durations) / len(api_call_durations)
        speedup = avg_api / avg_cache if avg_cache > 0 else 0
        
        summary_table.add_row("", "", "")  # Separator
        summary_table.add_row(
            "Avg Cache Hit Latency",
            f"[green]{format_time(avg_cache)}[/green]",
            f"{len(cache_hit_durations)} cache hits"
        )
        summary_table.add_row(
            "Avg API Call Latency",
            f"[yellow]{format_time(avg_api)}[/yellow]",
            f"{len(api_call_durations)} API calls"
        )
        summary_table.add_row(
            "Overall Cache Speedup",
            f"[green bold]{speedup:.1f}x faster[/green bold]",
            "Cache vs API performance"
        )
    
    console.print()
    console.print(summary_table)
    
    # Key takeaways
    console.print()
    takeaways_table = Table(title="🎯 Key Takeaways", box=box.ROUNDED, show_header=False)
    takeaways_table.add_column("", style="white", width=2)
    takeaways_table.add_column("", style="cyan")
    
    takeaways_table.add_row("🔒", "Distributed locking prevents cache stampede effectively")
    takeaways_table.add_row("⚡", "Only one thread makes the API call, others wait for cache")
    takeaways_table.add_row("🔄", "Exponential backoff reduces contention and improves efficiency")
    takeaways_table.add_row("⏰", "Lock timeout ensures system doesn't hang indefinitely")
    takeaways_table.add_row("🎯", f"Prevented {total_requests - total_api_calls} unnecessary API calls")
    takeaways_table.add_row("💰", "Significant cost savings for high-traffic scenarios")
    
    console.print(takeaways_table)
    
    # Cleanup
    console.print()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True
    ) as progress:
        task = progress.add_task("[cyan]🧹 Cleaning up...[/cyan]", total=None)
        cache.close()
        progress.update(task, completed=True)
    
    console.print("[green]✓[/green] Connections closed successfully")


@app.command()
def run(
    requests: int = typer.Option(
        1000,
        "--requests",
        "-r",
        help="Number of concurrent requests per city (1-10000)"
    ),
    threads: int = typer.Option(
        4,
        "--threads",
        "-t",
        help="Number of worker threads to use (1-100)"
    ),
    cities: int = typer.Option(
        3,
        "--cities",
        "-c",
        help="Number of cities to test (1-5)"
    ),
    lock_ttl: int = typer.Option(
        60000,
        "--lock-ttl",
        "-l",
        help="Lock TTL in milliseconds (10-60000). Too small = stampede risk!"
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
        help="Show detailed thread-level information"
    ),
    flush: bool = typer.Option(
        False,
        "--flush",
        "-f",
        help="Flush cache before running demo"
    )
):
    """Run the stampede prevention demonstration"""
    
    # Set global verbose flag
    global VERBOSE
    VERBOSE = verbose
    
    if VERBOSE:
        console.print("[dim]Verbose mode enabled - showing thread-level details[/dim]\n")
    
    # Validate inputs
    if requests < 1 or requests > 10000:
        console.print(f"[red]❌ Number of requests must be between 1 and 10000. Got: {requests}[/red]")
        return
    
    if threads < 1 or threads > 100:
        console.print(f"[red]❌ Number of threads must be between 1 and 100. Got: {threads}[/red]")
        return
    
    if cities < 1 or cities > 5:
        console.print(f"[red]❌ Number of cities must be between 1 and 5. Got: {cities}[/red]")
        return
    
    if lock_ttl < 10 or lock_ttl > 60000:
        console.print(f"[red]❌ Lock TTL must be between 100 and 60000 milliseconds. Got: {lock_ttl}[/red]")
        return
    
    # Warn if lock TTL is too small
    if lock_ttl < 1000:
        console.print(f"[yellow]⚠️  Warning: Lock TTL of {lock_ttl}ms is very small. This may cause stampede![/yellow]\n")
    
    try:
        run_demo(
            num_requests=requests,
            num_threads=threads,
            num_cities=cities,
            lock_ttl_ms=lock_ttl,
            interactive=interactive,
            flush=flush
        )
        
        # Final message
        print_section("DEMO COMPLETE")
        
        completion_panel = Panel.fit(
            "[green bold]✅ Stampede Prevention Demo Completed Successfully![/green bold]\n\n"
            "[cyan]What you learned:[/cyan]\n"
            "  • Distributed locking prevents cache stampede\n"
            "  • Exponential backoff for lock contention\n"
            "  • Fail-fast behavior with timeouts\n"
            "  • Significant API call reduction in high-traffic scenarios\n\n"
            "[dim]Try different options:[/dim]\n"
            "  [yellow]--requests 2000 --cities 5[/yellow]  (more load)\n"
            "  [yellow]--interactive --verbose[/yellow]  (step-by-step with details)\n"
            "  [yellow]--flush[/yellow]  (start with clean cache)",
            border_style="green",
            box=box.DOUBLE
        )
        console.print()
        console.print(completion_panel)
        console.print()
        
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠ Demo interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red]❌ Error during demo: {e}[/red]")
        if VERBOSE:
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    app()
