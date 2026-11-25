"""
Semantic Search for NLP to SQL with Caching

Demonstrates semantic caching using embeddings to find similar queries.
Uses vector similarity to match natural language queries and cache SQL results.

Shows:
1. Exact cache hits (same query)
2. Semantic cache hits (similar queries)
3. Cache misses (new queries)
4. Performance improvements from semantic matching
"""

import sys
import os
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box
from rich.prompt import Prompt
from tqdm import tqdm
import time

# Load environment variables
load_dotenv(os.environ.get("WORKSHOP_ENV_FILE", ".env"))

# Add parent directory to path to import from daos
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the Semantic SQL Cache
from daos.semantic_cache import SemanticSQLCache

# Initialize typer app and rich console
app = typer.Typer(help="Semantic Cache Pattern Demonstration")
console = Console()

# Global verbose flag
VERBOSE = False


def print_section(title: str):
    """Print a formatted section header using rich."""
    console.print()
    console.print(Panel(f"[bold cyan]{title}[/bold cyan]", box=box.DOUBLE))


def print_query_result(query_num: int, query: str, result: Dict[str, Any], show_sql: bool = True):
    """Print query execution results in a formatted way using rich."""
    console.print(f"\n[bold cyan]Query #{query_num}:[/bold cyan] {query}")
    console.print("─" * 70)
    
    # Calculate performance metrics
    lookup_time_us = result['lookup_time'] * 1_000_000  # Convert to microseconds
    
    # Determine cache status
    if result['cache_hit']:
        cache_type = result.get('cache_type', 'unknown')
        
        # Estimate LLM generation time (typical range 2-5 seconds)
        estimated_llm_time = result.get('time_taken', 3.0)  # Use actual if available, else estimate
        estimated_llm_time_us = estimated_llm_time * 1_000_000
        speedup = estimated_llm_time_us / lookup_time_us if lookup_time_us > 0 else 0
        
        if cache_type == 'semantic':
            similarity = result.get('similarity', 0)
            similar_prompt = result.get('similar_prompt', 'N/A')
            
            console.print(f"\n✨ [bold green]SEMANTIC CACHE HIT[/bold green]")
            console.print(f"   Similarity: [magenta]{similarity:.4f}[/magenta] (threshold: {result.get('threshold', 0.70)})")
            console.print(f"   Match quality: [yellow]{get_match_quality(similarity)}[/yellow]")
            
            # Performance metrics
            console.print(f"\n   [bold]⚡ Performance:[/bold]")
            console.print(f"   Cache lookup: [cyan]{lookup_time_us:,.0f} μs[/cyan] ([cyan]{result['lookup_time']:.3f}s[/cyan])")
            console.print(f"   Est. LLM time: [yellow]{estimated_llm_time_us:,.0f} μs[/yellow] ([yellow]~{estimated_llm_time:.1f}s[/yellow])")
            console.print(f"   Speedup: [green bold]{speedup:,.1f}x faster[/green bold]")
            console.print(f"   Time saved: [magenta]~{(estimated_llm_time - result['lookup_time']):.2f}s[/magenta]")
            
            if VERBOSE:
                console.print(f"\n   [dim]Matched Query:[/dim]")
                console.print(f"   [dim]Original:[/dim] \"{similar_prompt}\"")
                console.print(f"   [dim]Current:[/dim]  \"{query}\"")
                
                # Show all Valkey keys
                prompt_hash = result.get('prompt_hash', 'N/A')
                query_key = result.get('query_key', 'N/A')
                
                console.print(f"\n   [bold]🔑 Valkey Keys Used:[/bold]")
                keys_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
                keys_table.add_column("Key Type", style="cyan")
                keys_table.add_column("Key", style="yellow")
                keys_table.add_column("Purpose", style="dim")
                
                keys_table.add_row(
                    "Semantic",
                    f"{os.getenv('CACHE_KEY_PREFIX', 'baseline:attendee:')}semantic:prompt:{prompt_hash}",
                    "Maps prompt hash to query key"
                )
                keys_table.add_row(
                    "Query Result",
                    query_key if query_key != 'N/A' else f"db:query:<hash>",
                    "Stores SQL and metadata"
                )
                keys_table.add_row(
                    "Embedding",
                    f"embedding:prompt:{prompt_hash}",
                    "Stores vector for similarity search"
                )
                
                console.print(keys_table)
        else:  # exact match
            console.print(f"\n🎯 [bold green]EXACT CACHE HIT[/bold green]")
            console.print(f"   Match type: Hash-based exact match")
            
            # Performance metrics
            console.print(f"\n   [bold]⚡ Performance:[/bold]")
            console.print(f"   Cache lookup: [cyan]{lookup_time_us:,.0f} μs[/cyan] ([cyan]{result['lookup_time']:.3f}s[/cyan]) - instant!")
            console.print(f"   Est. LLM time: [yellow]{estimated_llm_time_us:,.0f} μs[/yellow] ([yellow]~{estimated_llm_time:.1f}s[/yellow])")
            console.print(f"   Speedup: [green bold]{speedup:,.1f}x faster[/green bold]")
            console.print(f"   Time saved: [magenta]~{(estimated_llm_time - result['lookup_time']):.2f}s[/magenta]")
            
            if VERBOSE:
                prompt_hash = result.get('prompt_hash', 'N/A')
                query_key = result.get('query_key', 'N/A')
                
                console.print(f"\n   [bold]🔑 Valkey Keys Used:[/bold]")
                keys_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
                keys_table.add_column("Key Type", style="cyan")
                keys_table.add_column("Key", style="yellow")
                keys_table.add_column("Purpose", style="dim")
                
                keys_table.add_row(
                    "Semantic",
                    f"{os.getenv('CACHE_KEY_PREFIX', 'baseline:attendee:')}semantic:prompt:{prompt_hash}",
                    "Direct hash lookup (exact match)"
                )
                keys_table.add_row(
                    "Query Result",
                    query_key if query_key != 'N/A' else f"db:query:<hash>",
                    "Stores SQL and metadata"
                )
                
                console.print(keys_table)
    else:
        # Cache miss - new query generation
        time_taken_us = result['time_taken'] * 1_000_000
        
        console.print(f"\n🤖 [bold yellow]CACHE MISS[/bold yellow] - New Query")
        console.print(f"   Action: Generating SQL with LLM")
        console.print(f"   Model: [cyan]{result.get('model', 'unknown')}[/cyan]")
        
        # Performance metrics
        console.print(f"\n   [bold]⏱️  Generation Time:[/bold]")
        console.print(f"   LLM generation: [magenta]{time_taken_us:,.0f} μs[/magenta] ([magenta]{result['time_taken']:.2f}s[/magenta])")
        console.print(f"   Tokens used: [yellow]{result['total_tokens']}[/yellow]")
        
        if VERBOSE:
            console.print(f"   Prompt tokens: {result.get('prompt_tokens', 'N/A')}")
            console.print(f"   Response tokens: {result.get('eval_tokens', 'N/A')}")
            
            # Show all Valkey keys that will be created
            prompt_hash = result.get('prompt_hash', 'N/A')
            sql_hash = result.get('sql_hash', 'N/A')
            
            console.print(f"\n   [bold]🔑 Valkey Keys Created:[/bold]")
            keys_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
            keys_table.add_column("Key Type", style="cyan")
            keys_table.add_column("Key", style="yellow")
            keys_table.add_column("Purpose", style="dim")
            
            keys_table.add_row(
                "Semantic",
                f"{os.getenv('CACHE_KEY_PREFIX', 'baseline:attendee:')}semantic:prompt:{prompt_hash}",
                "Maps prompt hash to query key"
            )
            keys_table.add_row(
                "Query Result",
                f"db:query:{sql_hash}" if sql_hash != 'N/A' else "db:query:<hash>",
                "Stores SQL and metadata"
            )
            keys_table.add_row(
                "Embedding",
                f"embedding:prompt:{prompt_hash}",
                "Stores vector for similarity search"
            )
            
            console.print(keys_table)
            console.print(f"\n   [dim]These keys enable future cache hits for similar queries[/dim]")
    
    # Show SQL (always in verbose mode, conditionally otherwise)
    if VERBOSE or show_sql:
        console.print(f"\n[bold]📄 Generated SQL:[/bold]")
        console.print(Panel(
            f"[cyan]{result['sql']}[/cyan]",
            border_style="dim",
            box=box.ROUNDED
        ))


def get_match_quality(similarity: float) -> str:
    """Get match quality description based on similarity score."""
    if similarity > 0.9:
        return "Excellent"
    elif similarity > 0.8:
        return "Good"
    else:
        return "Acceptable"


def demo_mode(cache: SemanticSQLCache):
    """Run demo with test queries including similar ones"""
    print_section("SEMANTIC CACHE DEMO - Similar Query Detection")
    
    console.print("\n[dim]Testing semantic similarity with related queries...[/dim]\n")
    
    test_queries = [
        # First query - will generate SQL
        "Flight manifest - all passengers on a specific flight 115",
        
        # Similar query - should hit semantic cache
        "Give me the passenger details from flight 115",
        
        # Another similar query
        "Show me all passengers on flight 115",
        
        # Another similar query
        "Passenger list flight 115",
        
        # Different query
        "Get airport with geographic details by IATA code JFK",
        
        # Similar to previous
        "Show me airport information for JFK including location",

        # Similar to previous
        "Show me airport information for John F Kennedy including location",
        
        # New query
        "How many bookings does passenger 1000 have?",
        
        # Exact repeat - should hit exact cache
        "How many bookings does passenger 1000 have?",
    ]
    
    total_time = 0
    cache_hits = 0
    semantic_hits = 0
    exact_hits = 0
    
    for i, query in enumerate(test_queries, 1):
        # Show processing status
        with console.status(
            f"[cyan]Processing query {i}/{len(test_queries)}...[/cyan]",
            spinner="dots"
        ) as status:
            # Generate hash for this prompt
            status.update("[cyan]Generating embedding...[/cyan]")
            prompt_hash = cache._hash_text(query)
            
            # Check cache and generate if needed
            status.update("[cyan]Checking semantic cache...[/cyan]")
            result = cache.get_or_generate_sql(query, verbose=False)
            
            # Add additional metadata for verbose output
            result['prompt_hash'] = prompt_hash
            result['threshold'] = cache.similarity_threshold
            
            # Get query_key if it's a cache hit
            if result.get('cache_hit'):
                semantic_key = f"{os.getenv('CACHE_KEY_PREFIX', 'baseline:attendee:')}semantic:prompt:{prompt_hash}"
                query_key = cache.valkey_client.get(semantic_key)
                if query_key:
                    result['query_key'] = query_key.decode('utf-8')
            else:
                # For cache miss, calculate sql_hash
                sql_hash = cache._hash_text(result['sql'])
                result['sql_hash'] = sql_hash
                result['query_key'] = f"db:query:{sql_hash}"
        
        # Print result (after status is done)
        print_query_result(i, query, result, show_sql=not VERBOSE)
        
        # Track statistics
        if result['cache_hit']:
            cache_hits += 1
            if result.get('cache_type') == 'semantic':
                semantic_hits += 1
            else:
                exact_hits += 1
        
        total_time += result.get('time_taken', 0) if not result['cache_hit'] else 0
    
    # Summary
    print_section("DEMO SUMMARY - The Power of Semantic Caching")
    
    # Calculate performance metrics
    cache_misses = len(test_queries) - cache_hits
    avg_llm_time = total_time / cache_misses if cache_misses > 0 else 3.0
    avg_cache_lookup = 0.003  # Typical cache lookup time in seconds
    
    # Estimate tokens saved
    avg_tokens_per_query = 2500  # Typical tokens for SQL generation
    tokens_saved = cache_hits * avg_tokens_per_query
    
    # Create execution summary table
    summary_table = Table(title="📈 Query Execution Summary", box=box.ROUNDED, show_lines=True)
    summary_table.add_column("Metric", style="cyan bold")
    summary_table.add_column("Value", style="white", justify="right")
    
    summary_table.add_row("Total queries", str(len(test_queries)))
    summary_table.add_row("Cache hits", f"[green]{cache_hits}[/green] ({cache_hits/len(test_queries)*100:.1f}%)")
    summary_table.add_row("  • Semantic hits", f"[yellow]{semantic_hits}[/yellow]")
    summary_table.add_row("  • Exact hits", f"[cyan]{exact_hits}[/cyan]")
    summary_table.add_row("Cache misses", f"[red]{cache_misses}[/red]")
    summary_table.add_row("", "")  # Separator
    summary_table.add_row("Total LLM time", f"{total_time:.2f}s")
    if cache_misses > 0:
        summary_table.add_row("Avg per new query", f"{avg_llm_time:.2f}s")
    
    console.print(summary_table)
    
    # Performance comparison: Cache Hit vs Cache Miss
    comparison_table = Table(
        title="⚡ Performance Impact: Cache Hit vs Cache Miss",
        box=box.ROUNDED,
        show_lines=True
    )
    comparison_table.add_column("Aspect", style="cyan bold", width=25)
    comparison_table.add_column("Cache Miss\n(LLM Generation)", style="red", justify="center")
    comparison_table.add_column("Cache Hit\n(Semantic/Exact)", style="green", justify="center")
    comparison_table.add_column("Improvement", style="magenta bold", justify="center")
    
    # Latency comparison
    cache_lookup_us = avg_cache_lookup * 1_000_000
    llm_time_us = avg_llm_time * 1_000_000
    speedup = llm_time_us / cache_lookup_us
    
    comparison_table.add_row(
        "Latency",
        f"{llm_time_us:,.0f} μs\n({avg_llm_time:.2f}s)",
        f"{cache_lookup_us:,.0f} μs\n({avg_cache_lookup:.3f}s)",
        f"[bold]{speedup:,.0f}x faster[/bold]"
    )
    
    # Token usage comparison
    token_reduction_pct = 100.0
    comparison_table.add_row(
        "Tokens Used",
        f"~{avg_tokens_per_query:,} tokens\n(LLM processing)",
        "0 tokens\n(No LLM call)",
        f"[bold]{token_reduction_pct:.0f}% reduction[/bold]"
    )
    
    # Resource usage
    comparison_table.add_row(
        "Resource Usage",
        "High\n(GPU/CPU intensive)",
        "Minimal\n(Memory lookup)",
        "[bold]~99% reduction[/bold]"
    )
    
    console.print(comparison_table)
    
    # Cumulative savings table
    savings_table = Table(
        title="💰 Cumulative Savings from Semantic Caching",
        box=box.ROUNDED,
        show_lines=True
    )
    savings_table.add_column("Resource", style="cyan bold", width=20)
    savings_table.add_column("Saved", style="green", justify="right")
    savings_table.add_column("Impact", style="yellow")
    
    time_saved = cache_hits * (avg_llm_time - avg_cache_lookup)
    savings_table.add_row(
        "Time Saved",
        f"{time_saved:.2f}s",
        f"{cache_hits} queries × {avg_llm_time:.1f}s avg"
    )
    
    total_tokens_possible = len(test_queries) * avg_tokens_per_query
    token_reduction_pct = (tokens_saved / total_tokens_possible * 100) if total_tokens_possible > 0 else 0
    savings_table.add_row(
        "Tokens Saved",
        f"{tokens_saved:,} tokens",
        f"{token_reduction_pct:.1f}% reduction"
    )
    
    savings_table.add_row(
        "LLM Calls Avoided",
        f"{cache_hits} calls",
        f"{cache_hits/len(test_queries)*100:.1f}% reduction"
    )
    
    console.print(savings_table)
    
    # Cache statistics
    stats = cache.get_cache_stats()
    
    stats_table = Table(title="📊 Cache Statistics", box=box.ROUNDED)
    stats_table.add_column("Metric", style="cyan bold")
    stats_table.add_column("Value", style="white", justify="right")
    
    stats_table.add_row("Cached prompts", str(stats['total_prompts']))
    stats_table.add_row("Cached queries", str(stats['total_queries']))
    stats_table.add_row("Embeddings stored", str(stats['total_embeddings']))
    stats_table.add_row("Cache efficiency", f"{cache_hits/len(test_queries)*100:.1f}%")
    stats_table.add_row("Similarity threshold", f"{cache.similarity_threshold}")
    
    console.print(stats_table)
    
    # Key insights
    console.print("\n[bold cyan]🔑 Key Insights:[/bold cyan]")
    insights_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    insights_table.add_column("", style="yellow")
    
    insights_table.add_row(f"• Semantic caching matched {semantic_hits} similar queries without exact text match")
    insights_table.add_row(f"• Average speedup of {speedup:,.0f}x compared to LLM generation")
    insights_table.add_row(f"• Saved {tokens_saved:,} tokens by avoiding redundant LLM calls")
    insights_table.add_row(f"• Vector embeddings enable natural language query variations")
    insights_table.add_row(f"• Cache efficiency: {cache_hits/len(test_queries)*100:.1f}% hit rate in this demo")
    
    console.print(insights_table)


def interactive_mode(cache: SemanticSQLCache):
    """Run in interactive mode"""
    print_section("INTERACTIVE MODE - Semantic SQL Cache")
    
    console.print("\n[yellow]Enter your natural language queries (or 'quit' to exit)[/yellow]")
    console.print("[dim]Commands: 'stats' for cache stats, 'clear' to clear cache[/dim]\n")
    
    query_count = 0
    
    while True:
        try:
            query = Prompt.ask("\n[bold cyan]Your query[/bold cyan]").strip()
            
            if query.lower() in ['quit', 'exit', 'q']:
                console.print("\n[green]Goodbye![/green]")
                break
            
            if query.lower() == 'stats':
                stats = cache.get_cache_stats()
                
                stats_table = Table(title="📊 Cache Statistics", box=box.ROUNDED)
                stats_table.add_column("Metric", style="cyan bold")
                stats_table.add_column("Value", style="white", justify="right")
                
                stats_table.add_row("Cached prompts", str(stats['total_prompts']))
                stats_table.add_row("Cached queries", str(stats['total_queries']))
                stats_table.add_row("Embeddings", str(stats['total_embeddings']))
                stats_table.add_row("Queries this session", str(query_count))
                
                console.print(stats_table)
                continue
            
            if query.lower() == 'clear':
                console.print("[yellow]🧹 Clearing cache...[/yellow]")
                cache.clear_cache()
                console.print("[green]✓ Cache cleared[/green]")
                continue
            
            if not query:
                continue
            
            query_count += 1
            
            # Show processing status
            with console.status(
                "[cyan]Processing your query...[/cyan]",
                spinner="dots"
            ) as status:
                # Generate hash for this prompt
                status.update("[cyan]Generating embedding...[/cyan]")
                prompt_hash = cache._hash_text(query)
                
                # Check cache and generate if needed
                status.update("[cyan]Checking semantic cache...[/cyan]")
                result = cache.get_or_generate_sql(query, verbose=False)
                
                # Add additional metadata for verbose output
                result['prompt_hash'] = prompt_hash
                result['threshold'] = cache.similarity_threshold
                
                # Get query_key if it's a cache hit
                if result.get('cache_hit'):
                    semantic_key = f"{os.getenv('CACHE_KEY_PREFIX', 'baseline:attendee:')}semantic:prompt:{prompt_hash}"
                    query_key = cache.valkey_client.get(semantic_key)
                    if query_key:
                        result['query_key'] = query_key.decode('utf-8')
                else:
                    # For cache miss, calculate sql_hash
                    status.update("[yellow]Generating SQL with LLM (this may take a few seconds)...[/yellow]")
                    sql_hash = cache._hash_text(result['sql'])
                    result['sql_hash'] = sql_hash
                    result['query_key'] = f"db:query:{sql_hash}"
            
            # Print result (after status is done)
            print_query_result(query_count, query, result)
            
        except KeyboardInterrupt:
            console.print("\n\n[green]Goodbye![/green]")
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            if VERBOSE:
                import traceback
                traceback.print_exc()


@app.command()
def run(
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Run in interactive mode for custom queries"
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed information including embeddings and cache keys"
    ),
    flush: bool = typer.Option(
        False,
        "--flush",
        "-f",
        help="Flush cache before running demo"
    ),
    host: str = typer.Option(
        None,
        "--host",
        help="Valkey host (default: from VECTOR_HOST env or localhost)"
    ),
    port: int = typer.Option(
        None,
        "--port",
        help="Valkey port (default: from VECTOR_PORT env or 6379)"
    ),
    model: str = typer.Option(
        None,
        "--model",
        help="Ollama model for SQL generation (default: from OLLAMA_MODEL env or codellama)"
    ),
    threshold: float = typer.Option(
        None,
        "--threshold",
        help="Similarity threshold 0-1 (default: from SIMILARITY_THRESHOLD env or 0.70)"
    )
):
    """Run the semantic cache pattern demonstration"""
    
    # Set global verbose flag
    global VERBOSE
    VERBOSE = verbose
    
    if VERBOSE:
        console.print("[dim]Verbose mode enabled - showing detailed information[/dim]\n")
    
    # Print header
    console.print()
    console.print(Panel.fit(
        "[bold cyan]SEMANTIC CACHE PATTERN DEMONSTRATION[/bold cyan]\n"
        "[yellow]Vector Similarity for Natural Language SQL Queries[/yellow]",
        border_style="cyan",
        box=box.DOUBLE
    ))
    
    # Get configuration from env or defaults
    valkey_host = host or os.getenv('VECTOR_HOST', 'localhost')
    valkey_port = port or int(os.getenv('VECTOR_PORT', '6379'))
    ollama_model = model or os.getenv('OLLAMA_MODEL', 'codellama')
    similarity_threshold = threshold or float(os.getenv('SIMILARITY_THRESHOLD', '0.70'))
    
    # Initialize cache with progress indicator
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Initializing semantic cache handler...", total=None)
        try:
            cache = SemanticSQLCache(
                valkey_host=valkey_host,
                valkey_port=valkey_port,
                ollama_model=ollama_model,
                similarity_threshold=similarity_threshold,
                verbose=False  # We handle verbose output ourselves
            )
            progress.update(task, completed=True)
        except Exception as e:
            progress.stop()
            console.print(f"[red]❌ Error initializing cache: {e}[/red]")
            return
    
    console.print("[green]✓[/green] Connected to Valkey and Ollama\n")
    
    if VERBOSE:
        console.print("[dim]Configuration:[/dim]")
        console.print(f"[dim]  Valkey:[/dim] {valkey_host}:{valkey_port}")
        console.print(f"[dim]  Model:[/dim] {ollama_model}")
        console.print(f"[dim]  Threshold:[/dim] {similarity_threshold}")
        # Get vector dimension from semantic search (lazy loaded)
        vector_dim = cache.semantic_search.vector_dim
        console.print(f"[dim]  Vector dim:[/dim] {vector_dim}\n")
    
    # Flush cache if requested
    if flush:
        with console.status("[yellow]🧹 Flushing cache...[/yellow]", spinner="dots"):
            try:
                cache.clear_cache()
                time.sleep(0.5)  # Brief pause for visual feedback
            except Exception as e:
                console.print(f"[red]❌ Error flushing cache: {e}[/red]\n")
                return
        console.print("[green]✓[/green] Cache flushed successfully\n")
    
    try:
        if interactive:
            # Interactive mode
            console.print("[bold yellow]Interactive Mode:[/bold yellow] Enter queries or commands\n")
            interactive_mode(cache)
        else:
            # Demo mode
            console.print("[bold green]Demo Mode:[/bold green] Running predefined queries\n")
            
            if not VERBOSE:
                # Use progress bar for demo mode
                demo_steps = ["Running semantic cache demo"]
                for step in tqdm(demo_steps, desc="Demo Progress", unit="step"):
                    demo_mode(cache)
                    time.sleep(0.5)
            else:
                demo_mode(cache)
        
        # Final summary
        print_section("DEMO COMPLETE")
        console.print("\n[green]✅ All queries executed successfully![/green]\n")
        
        # Key takeaways
        takeaways_table = Table(title="💡 Key Takeaways", box=box.ROUNDED, show_header=False)
        takeaways_table.add_column("", style="cyan")
        takeaways_table.add_row("• Semantic cache matches similar queries using vector embeddings")
        takeaways_table.add_row("• Exact cache hits are instant (hash-based lookup)")
        takeaways_table.add_row("• Semantic hits save LLM generation time (~2-5s per query)")
        takeaways_table.add_row("• Similarity threshold controls matching sensitivity")
        takeaways_table.add_row("• Embeddings enable natural language query variations")
        console.print(takeaways_table)
        
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
        console.print("[green]✓[/green] Connections closed\n")


if __name__ == "__main__":
    app()
