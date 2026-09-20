"""
Weather API Cache Demo - Cache-Aside Pattern with Lazy Loading

This demo showcases the cache-aside pattern with blocking lazy loading for weather data.
It compares performance before and after caching with configurable TTL (15, 30, or 60 minutes).
"""

import sys
import time
import random
import json
import os
import secrets
from pathlib import Path
from typing import Any, Optional
from dotenv import load_dotenv
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich import box
from rich.prompt import Confirm, IntPrompt
from rich.syntax import Syntax
from tqdm import tqdm

# Add parent directory to path to import services
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.weather_service import WeatherService

# Load environment variables
load_dotenv()

# Initialize typer app and rich console
app = typer.Typer(help="Weather API Cache-Aside Pattern Demonstration")
console = Console()

# Global verbose flag
VERBOSE = False

_RELEASE_LOCK_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
"""


def print_section(title: str):
    """Print a formatted section header using rich."""
    console.print()
    console.print(Panel(f"[bold cyan]{title}[/bold cyan]", box=box.DOUBLE))


def print_verbose_info(message: str):
    """Print verbose information if verbose mode is enabled."""
    if VERBOSE:
        console.print(f"[dim]{message}[/dim]")


class SimpleCache:
    """Simple Valkey/Redis cache with TTL support for demo purposes."""
    
    def __init__(self, default_ttl: int = 900):
        """
        Initialize Valkey cache connection.
        
        Args:
            default_ttl: Default time-to-live in seconds (default: 900 = 15 minutes)
        """
        # Import from core module
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from core import get_cache_client
        
        self.default_ttl = default_ttl
        self.cache = get_cache_client()
        self.client = self.cache.client  # For backward compatibility with ping()
        
        # Test connection
        try:
            self.client.ping()
            if VERBOSE:
                console.print(f"[green]✓[/green] Connected to Valkey at {self.cache.host}:{self.cache.port}")
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to connect to Valkey at {self.cache.host}:{self.cache.port}")
            raise e
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        try:
            value = self.cache.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            print(f"Cache GET error for key '{key}': {e}")
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache with TTL."""
        if ttl is None:
            ttl = self.default_ttl
        
        try:
            serialized_value = json.dumps(value, default=str)
            self.cache.set(key, serialized_value, ttl)
        except Exception as e:
            print(f"Cache SET error for key '{key}': {e}")
    
    def acquire_lock(self, key: str, timeout: int = 10) -> Optional[str]:
        """
        Acquire a distributed lock for a key to prevent cache stampede.
        
        Args:
            key: The cache key to lock
            timeout: Lock timeout in seconds (default: 10)
        
        Returns:
            Unique owner token if acquired, otherwise None
        """
        lock_key = f"lock:{key}"
        try:
            # SET NX (set if not exists) with expiration
            token = secrets.token_urlsafe(24)
            return token if self.client.set(
                lock_key, token, nx=True, ex=timeout
            ) else None
        except Exception as e:
            print(f"Lock ACQUIRE error for key '{key}': {e}")
            return None
    
    def release_lock(self, key: str, token: str) -> bool:
        """
        Release a distributed lock for a key.
        
        Args:
            key: The cache key to unlock
        """
        lock_key = f"lock:{key}"
        try:
            return bool(
                self.client.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, token)
            )
        except Exception as e:
            print(f"Lock RELEASE error for key '{key}': {e}")
            return False
    
    def clear(self) -> None:
        """Clear all cache entries (use with caution in production!)."""
        try:
            self.client.flushdb()
            print_verbose_info("Cache cleared successfully")
        except Exception as e:
            console.print(f"[red]Cache CLEAR error: {e}[/red]")
    
    def keys(self, pattern: str = "*") -> list:
        """Get all keys matching pattern."""
        try:
            return self.client.keys(pattern)
        except Exception as e:
            print(f"Cache KEYS error: {e}")
            return []
    
    def close(self) -> None:
        """Close Valkey connection."""
        try:
            self.cache.close()
        except Exception as e:
            print(f"Cache CLOSE error: {e}")


def format_time(seconds: float) -> str:
    """Format time in a human-readable way."""
    if seconds < 1:
        return f"{seconds * 1000:.3f}ms"
    return f"{seconds:.3f}s"


def get_country_flag(country_code: str) -> str:
    """Convert country code to flag emoji."""
    # Map common country codes to flag emojis
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
    
    # Get weather description (lowercase for matching)
    # weather is a list in the API response
    weather_list = weather_data.get('weather', [])
    if not weather_list:
        return '❓'
    
    weather_info = weather_list[0] if isinstance(weather_list, list) else weather_list
    description = weather_info.get('description', '').lower()
    main = weather_info.get('main', '').lower()
    
    # Map weather conditions to emojis
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
    
    # weather is a list in the API response
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


def get_random_cities(count: int = 10) -> list:
    """Get random cities from the weather service."""
    all_cities = WeatherService.get_all_cities()
    return random.sample(all_cities, min(count, len(all_cities)))


def fetch_weather_without_cache(cities: list) -> tuple:
    """Fetch weather data without caching."""
    print_section("FETCHING WITHOUT CACHE (Direct API Calls)")
    
    results = []
    start_time = time.time()
    
    # Use tqdm for progress bar only in verbose mode
    iterator = tqdm(cities, desc="Fetching weather", unit="city") if VERBOSE else cities
    
    for i, city in enumerate(iterator if VERBOSE else cities, 1):
        city_start = time.time()
        weather = WeatherService.get_weather(city['country'], city['zip'])
        city_elapsed = time.time() - city_start
        
        results.append(weather)
        
        # Get emojis
        country_flag = get_country_flag(city['country'])
        weather_emoji = get_weather_emoji(weather)
        weather_details = format_weather_details(weather)
        
        # Update progress bar description if in verbose mode
        if VERBOSE and hasattr(iterator, 'set_postfix_str'):
            iterator.set_postfix_str(f"{city['name']} - {format_time(city_elapsed)}")
        
        # Display output
        if VERBOSE:
            # Verbose mode: show more details
            console.print(f"\n[dim]─── City #{i}: {city['name']} ───[/dim]")
            console.print(f"[dim]API Call:[/dim] Direct (no cache)")
            console.print(f"[dim]Latency:[/dim] [magenta]{format_time(city_elapsed)}[/magenta]")
            console.print(
                f"{weather_emoji} [cyan]{city['name']:20s}[/cyan] "
                f"{country_flag} [yellow]{city['country']}[/yellow] - "
                f"[white]{weather_details}[/white]"
            )
            
            # Show JSON sample for first API call with syntax highlighting
            if i == 1:
                console.print("\n[dim]─── Sample Weather API Response (JSON) ───[/dim]")
                json_str = json.dumps(weather, indent=2, default=str)
                syntax = Syntax(json_str, "json", theme="monokai", line_numbers=False)
                console.print(Panel(
                    syntax,
                    title="[bold cyan]Weather Data Structure[/bold cyan]",
                    border_style="cyan",
                    box=box.ROUNDED
                ))
        else:
            # Normal mode: clean line-by-line output
            console.print(
                f"  {weather_emoji} {i:2d}. [cyan]{city['name']:20s}[/cyan] "
                f"{country_flag} [yellow]{city['country']}[/yellow] - "
                f"[white]{weather_details}[/white] - "
                f"[magenta]{format_time(city_elapsed)}[/magenta]"
            )
    
    total_time = time.time() - start_time
    console.print(f"\n[bold]Total time:[/bold] [magenta]{format_time(total_time)}[/magenta]")
    
    return results, total_time


def fetch_weather_with_cache(cities: list, cache: SimpleCache, run_number: int = 1) -> tuple:
    """Fetch weather data with caching and distributed locking."""
    print_section(f"FETCHING WITH CACHE (Run #{run_number})")
    
    results = []
    cache_hits = 0
    cache_misses = 0
    lock_waits = 0
    start_time = time.time()
    
    # Use tqdm for progress bar only in verbose mode
    iterator = tqdm(cities, desc=f"Run #{run_number}", unit="city") if VERBOSE else cities
    
    for i, city in enumerate(iterator if VERBOSE else cities, 1):
        city_start = time.time()
        cache_key = f"weather:{city['country'].lower()}:{city['zip']}"
        
        print_verbose_info(f"Cache key: {cache_key}")
        
        # Try to get from cache first
        cached_data = cache.get(cache_key)
        
        if cached_data:
            weather = cached_data
            cache_hits += 1
            status = "CACHE HIT"
            status_color = "green"
            status_icon = "✓"
        else:
            # Cache miss - try to acquire lock to prevent stampede
            lock_token = cache.acquire_lock(cache_key, timeout=10)
            
            if lock_token:
                try:
                    # Double-check cache after acquiring lock (another thread might have populated it)
                    cached_data = cache.get(cache_key)
                    if cached_data:
                        weather = cached_data
                        cache_hits += 1
                        status = "CACHE HIT (after lock)"
                        status_color = "green"
                        status_icon = "✓"
                    else:
                        # Fetch from API and store in cache
                        weather = WeatherService.get_weather(city['country'], city['zip'])
                        cache.set(cache_key, weather)
                        cache_misses += 1
                        status = "CACHE MISS (populated)"
                        status_color = "yellow"
                        status_icon = "⚡"
                finally:
                    # Always release the lock
                    cache.release_lock(cache_key, lock_token)
            else:
                # Could not acquire lock, wait and retry getting from cache
                lock_waits += 1
                status = "LOCK WAIT"
                status_color = "yellow"
                status_icon = "⏳"
                max_retries = 20
                retry_delay = 0.5
                
                for retry in range(max_retries):
                    time.sleep(retry_delay)
                    cached_data = cache.get(cache_key)
                    if cached_data:
                        weather = cached_data
                        cache_hits += 1
                        status = f"CACHE HIT (waited {(retry + 1) * retry_delay:.1f}s)"
                        status_color = "green"
                        status_icon = "✓"
                        break
                else:
                    # Timeout waiting for lock, fetch anyway
                    weather = WeatherService.get_weather(city['country'], city['zip'])
                    cache.set(cache_key, weather)
                    cache_misses += 1
                    status = "CACHE MISS (timeout)"
                    status_color = "yellow"
                    status_icon = "⚡"
            
        city_elapsed = time.time() - city_start
        results.append(weather)
        
        # Get emojis
        country_flag = get_country_flag(city['country'])
        weather_emoji = get_weather_emoji(weather)
        
        # Update progress bar if in verbose mode
        if VERBOSE and hasattr(iterator, 'set_postfix_str'):
            iterator.set_postfix_str(f"{city['name']} - {status}")
        
        # Display output
        if VERBOSE:
            # Verbose mode: show cache key and more details
            console.print(f"\n[dim]─── City #{i}: {city['name']} ───[/dim]")
            console.print(f"[dim]Cache Key:[/dim] [yellow]{cache_key}[/yellow]")
            console.print(f"[dim]Status:[/dim] [{status_color}]{status}[/{status_color}]")
            console.print(f"[dim]Latency:[/dim] [magenta]{format_time(city_elapsed)}[/magenta]")
            
            # Show weather details
            if run_number == 2:
                weather_details = format_weather_details(weather)
                console.print(
                    f"{status_icon} {weather_emoji} [cyan]{city['name']:20s}[/cyan] "
                    f"{country_flag} [yellow]{city['country']}[/yellow] - "
                    f"[white]{weather_details}[/white]"
                )
            else:
                console.print(
                    f"{status_icon} [cyan]{city['name']:20s}[/cyan] "
                    f"{country_flag} [yellow]{city['country']}[/yellow]"
                )
            
            # Show JSON sample for first API call (cache miss) with syntax highlighting
            if i == 1 and status.startswith("CACHE MISS"):
                console.print("\n[dim]─── Sample Weather API Response (JSON) ───[/dim]")
                json_str = json.dumps(weather, indent=2, default=str)
                syntax = Syntax(json_str, "json", theme="monokai", line_numbers=False)
                console.print(Panel(
                    syntax,
                    title="[bold cyan]Weather Data Structure[/bold cyan]",
                    border_style="cyan",
                    box=box.ROUNDED
                ))
        else:
            # Normal mode: clean line-by-line output
            # For Run #2, show detailed weather information
            if run_number == 2:
                weather_details = format_weather_details(weather)
                console.print(
                    f"  {status_icon} {i:2d}. {weather_emoji} [cyan]{city['name']:20s}[/cyan] "
                    f"{country_flag} [yellow]{city['country']}[/yellow] - "
                    f"[white]{weather_details}[/white] - "
                    f"[magenta]{format_time(city_elapsed):>8s}[/magenta] "
                    f"[[{status_color}]{status}[/{status_color}]]"
                )
            else:
                # For Run #1, keep it simpler
                console.print(
                    f"  {status_icon} {i:2d}. [cyan]{city['name']:20s}[/cyan] "
                    f"{country_flag} [yellow]{city['country']}[/yellow] - "
                    f"[magenta]{format_time(city_elapsed):>8s}[/magenta] "
                    f"[[{status_color}]{status}[/{status_color}]]"
                )
    
    total_time = time.time() - start_time
    
    # Create statistics table
    stats_table = Table(title="Cache Statistics", box=box.ROUNDED, show_header=False)
    stats_table.add_column("Metric", style="cyan bold")
    stats_table.add_column("Value", style="white", justify="right")
    
    stats_table.add_row("Hits", f"[green]{cache_hits}[/green]")
    stats_table.add_row("Misses", f"[yellow]{cache_misses}[/yellow]")
    if lock_waits > 0:
        stats_table.add_row("Lock Waits", f"[yellow]{lock_waits}[/yellow]")
    stats_table.add_row("Hit Rate", f"[magenta]{(cache_hits / len(cities) * 100):.1f}%[/magenta]")
    stats_table.add_row("Total Time", f"[magenta]{format_time(total_time)}[/magenta]")
    
    console.print()
    console.print(stats_table)
    
    return results, total_time, cache_hits, cache_misses


def run_demo(ttl_minutes: int = 15, num_cities: int = 10, interactive: bool = False, flush: bool = False):
    """
    Run the weather API cache demo.
    
    Args:
        ttl_minutes: Cache TTL in minutes (15, 30, or 60)
        num_cities: Number of random cities to test (default: 10)
        interactive: Run step-by-step with prompts
        flush: Flush cache before running demo
    """
    # Print header
    console.print()
    console.print(Panel.fit(
        "[bold cyan]WEATHER API CACHE DEMO - Cache-Aside Pattern[/bold cyan]\n"
        "[yellow]Performance Comparison with Lazy Loading[/yellow]",
        border_style="cyan",
        box=box.DOUBLE
    ))
    
    # Show configuration
    config_table = Table(title="Configuration", box=box.ROUNDED, show_header=False)
    config_table.add_column("Setting", style="cyan bold")
    config_table.add_column("Value", style="white")
    
    config_table.add_row("Cache TTL", f"{ttl_minutes} minutes ({ttl_minutes * 60} seconds)")
    config_table.add_row("Number of cities", str(num_cities))
    config_table.add_row("Cache key format", "weather:<country>:<zip>")
    config_table.add_row("Verbose mode", "Enabled" if VERBOSE else "Disabled")
    
    console.print()
    console.print(config_table)
    
    # Initialize cache with progress indicator
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Initializing cache connection...", total=None)
        cache = SimpleCache(default_ttl=ttl_minutes * 60)
        progress.update(task, completed=True)
    
    console.print("[green]✓[/green] Connected to database and cache\n")
    
    # Flush cache if requested
    if flush:
        console.print("[yellow]🧹 Flushing cache...[/yellow]")
        try:
            cache.clear()
            console.print("[green]✓[/green] Cache flushed successfully\n")
        except Exception as e:
            console.print(f"[red]❌ Error flushing cache: {e}[/red]\n")
    
    # Select random cities
    cities = get_random_cities(num_cities)
    
    # Show selected cities
    cities_table = Table(title="Selected Cities", box=box.ROUNDED)
    cities_table.add_column("#", style="dim", justify="right")
    cities_table.add_column("City", style="cyan")
    cities_table.add_column("Country", style="yellow")
    cities_table.add_column("ZIP", style="white")
    
    for i, city in enumerate(cities, 1):
        country_flag = get_country_flag(city['country'])
        cities_table.add_row(str(i), city['name'], f"{country_flag} {city['country']}", city['zip'])
    
    console.print()
    console.print(cities_table)
    
    # Phase 1: Fetch without cache
    if interactive:
        console.print("\n[bold cyan]→ Phase 1: Fetch without cache[/bold cyan]")
        if not Confirm.ask("Continue?", default=True):
            cache.close()
            return
    
    _, time_without_cache = fetch_weather_without_cache(cities)
    
    if interactive:
        console.print("\n[bold cyan]→ Phase 2: First fetch with cache (populating)[/bold cyan]")
        if not Confirm.ask("Continue?", default=True):
            cache.close()
            return
    else:
        console.print()
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task("[dim]⏳ Preparing cache test...[/dim]", total=None)
            time.sleep(1)
            progress.update(task, completed=True)
    
    # Phase 2: First fetch with cache (all misses)
    _, time_first_cache, _, _ = fetch_weather_with_cache(cities, cache, run_number=1)
    
    if interactive:
        console.print("\n[bold cyan]→ Phase 3: Second fetch with cache (using cache)[/bold cyan]")
        if not Confirm.ask("Continue?", default=True):
            cache.close()
            return
    else:
        console.print()
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task("[dim]⏳ Preparing second fetch...[/dim]", total=None)
            time.sleep(1)
            progress.update(task, completed=True)
    
    # Phase 3: Second fetch with cache (all hits)
    _, time_second_cache, hits, misses = fetch_weather_with_cache(cities, cache, run_number=2)
    
    # Summary
    print_section("PERFORMANCE SUMMARY")
    
    # Calculate benefits first
    speedup = time_without_cache / time_second_cache if time_second_cache > 0 else 0
    time_saved = time_without_cache - time_second_cache
    efficiency = (time_saved / time_without_cache * 100) if time_without_cache > 0 else 0
    
    # Create performance comparison table with visual indicators
    perf_table = Table(title="📊 Performance Comparison", box=box.ROUNDED, show_lines=True)
    perf_table.add_column("", style="white", width=2)
    perf_table.add_column("Scenario", style="cyan bold")
    perf_table.add_column("Time", style="magenta", justify="right")
    perf_table.add_column("vs Baseline", style="white", justify="right")
    perf_table.add_column("Note", style="dim")
    
    perf_table.add_row("🐌", "Without cache", format_time(time_without_cache), "1.0x", "Direct API calls")
    
    first_speedup = time_without_cache / time_first_cache if time_first_cache > 0 else 0
    perf_table.add_row(
        "⚡", 
        "With cache (1st run)", 
        format_time(time_first_cache), 
        f"[yellow]{first_speedup:.1f}x[/yellow]",
        "Populating cache"
    )
    
    perf_table.add_row(
        "🚀", 
        "With cache (2nd run)", 
        format_time(time_second_cache), 
        f"[green bold]{speedup:.1f}x[/green bold]",
        "Using cache"
    )
    
    console.print()
    console.print(perf_table)
    
    # Create benefits table with emojis
    benefits_table = Table(title="💡 Cache Benefits", box=box.ROUNDED, show_header=False)
    benefits_table.add_column("", style="white", width=2)
    benefits_table.add_column("Metric", style="cyan bold")
    benefits_table.add_column("Value", style="white", justify="right")
    
    benefits_table.add_row("⏱️", "Time saved", f"[green bold]{format_time(time_saved)}[/green bold]")
    benefits_table.add_row("⚡", "Speedup", f"[green bold]{speedup:.1f}x faster[/green bold]")
    benefits_table.add_row("📈", "Efficiency", f"[green bold]{efficiency:.1f}% reduction[/green bold]")
    
    # Add per-city average
    avg_time_cached = time_second_cache / len(cities) if len(cities) > 0 else 0
    avg_time_uncached = time_without_cache / len(cities) if len(cities) > 0 else 0
    benefits_table.add_row("", "", "")  # Separator
    benefits_table.add_row("🏙️", "Avg per city (cached)", f"[cyan]{format_time(avg_time_cached)}[/cyan]")
    benefits_table.add_row("🏙️", "Avg per city (uncached)", f"[dim]{format_time(avg_time_uncached)}[/dim]")
    
    console.print()
    console.print(benefits_table)
    
    # Show cache contents with visual box
    cache_keys = cache.keys("weather:*")
    cache_info = Table(title="📦 Cache Status", box=box.ROUNDED, show_header=False)
    cache_info.add_column("", style="white", width=2)
    cache_info.add_column("Property", style="cyan bold")
    cache_info.add_column("Value", style="white")
    
    cache_info.add_row("🗄️", "Total entries", f"[green]{len(cache_keys)}[/green] weather records")
    cache_info.add_row("⏰", "TTL", f"[yellow]{ttl_minutes}[/yellow] minutes ([dim]{ttl_minutes * 60} seconds[/dim])")
    cache_info.add_row("✅", "Hit rate (Run #2)", f"[green bold]{(hits / len(cities) * 100):.1f}%[/green bold]")
    
    if cache_keys and VERBOSE:
        sample_keys = [k.decode() if isinstance(k, bytes) else k for k in cache_keys[:3]]
        cache_info.add_row("🔑", "Sample keys", f"[dim]{', '.join(sample_keys)}[/dim]")
    
    console.print()
    console.print(cache_info)
    
    # Key takeaways with emojis
    console.print()
    takeaways_table = Table(title="🎯 Key Takeaways", box=box.ROUNDED, show_header=False)
    takeaways_table.add_column("", style="white", width=2)
    takeaways_table.add_column("", style="cyan")
    
    takeaways_table.add_row("⚡", "Cache-aside pattern reduces API call latency significantly")
    takeaways_table.add_row("🔒", "Distributed locking prevents cache stampede")
    takeaways_table.add_row("⏰", "TTL ensures data freshness while maintaining performance")
    takeaways_table.add_row("🔄", "Lazy loading populates cache on-demand")
    takeaways_table.add_row("🌍", "Weather data includes real-time conditions with emojis")
    
    console.print(takeaways_table)
    
    # Cleanup with progress indicator
    console.print()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True
    ) as progress:
        task = progress.add_task("[cyan]🧹 Cleaning up connections...[/cyan]", total=None)
        cache.close()
        progress.update(task, completed=True)
    
    console.print("[green]✓[/green] Connections closed successfully")


@app.command()
def run(
    ttl: int = typer.Option(
        15,
        "--ttl",
        "-t",
        help="Cache TTL in minutes (15, 30, or 60)"
    ),
    num_cities: int = typer.Option(
        10,
        "--cities",
        "-c",
        help="Number of random cities to test (1-95)"
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
        help="Show detailed information and cache keys"
    ),
    flush: bool = typer.Option(
        False,
        "--flush",
        "-f",
        help="Flush cache before running demo"
    )
):
    """Run the weather API cache-aside pattern demonstration"""
    
    # Set global verbose flag
    global VERBOSE
    VERBOSE = verbose
    
    if VERBOSE:
        console.print("[dim]Verbose mode enabled - showing detailed information[/dim]\n")
    
    # Validate inputs
    if ttl not in [15, 30, 60]:
        console.print(f"[yellow]⚠ Warning: TTL {ttl} is not standard (15, 30, 60). Using anyway.[/yellow]")
    
    if num_cities < 1 or num_cities > 95:
        console.print(f"[red]❌ Number of cities must be between 1 and 95. Got: {num_cities}[/red]")
        return
    
    # Allow user to customize in interactive mode
    if interactive:
        console.print(f"[dim]Current configuration: TTL={ttl} minutes, Cities={num_cities}[/dim]")
        if Confirm.ask("Would you like to customize these settings?", default=False):
            ttl = IntPrompt.ask("Enter TTL in minutes", default=ttl)
            num_cities = IntPrompt.ask("Enter number of cities", default=num_cities)
    
    try:
        # Run the demo
        run_demo(ttl_minutes=ttl, num_cities=num_cities, interactive=interactive, flush=flush)
        
        # Final message with summary
        print_section("DEMO COMPLETE")
        
        completion_panel = Panel.fit(
            "[green bold]✅ Weather API Cache Demo Completed Successfully![/green bold]\n\n"
            "[cyan]What you learned:[/cyan]\n"
            "  • Cache-aside pattern with lazy loading\n"
            "  • Distributed locking to prevent cache stampede\n"
            "  • Performance benefits of caching API calls\n"
            "  • Real-time weather data visualization\n\n"
            "[dim]Try different options:[/dim]\n"
            "  [yellow]--ttl 30 --cities 20[/yellow]  (more cities, longer TTL)\n"
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
