"""
Natural Language to SQL Query Generator
Uses Ollama with knowledge base context
"""

import json
import os
from pathlib import Path
import requests
import sys
import time
from dotenv import load_dotenv
from rich.console import Console
from rich.syntax import Syntax
from rich.panel import Panel
import sqlparse

# Load environment variables
load_dotenv(os.environ.get("WORKSHOP_ENV_FILE", ".env"))

# Initialize rich console
console = Console()


class NLPToSQL:
    def __init__(self, knowledge_base_path: str = None, model: str = None):
        # Use environment variables with fallbacks
        if knowledge_base_path is None:
            kb_path_env = os.getenv("KNOWLEDGE_BASE_PATH", "knowledge_base")
            # If path is relative, make it relative to the script's directory
            if not os.path.isabs(kb_path_env):
                # Get the directory where this script is located
                script_dir = Path(__file__).parent.parent
                knowledge_base_path = str(script_dir / kb_path_env)
            else:
                knowledge_base_path = kb_path_env
        if model is None:
            model = os.getenv("OLLAMA_MODEL", "codellama")
        
        self.kb_path = Path(knowledge_base_path)
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
        self.model = model
        self.context = self._load_knowledge_base()
        
        # Calculate context statistics
        context_lines = len(self.context.split('\n'))
        context_chars = len(self.context)
        # Rough token estimate (1 token ≈ 4 chars for English)
        estimated_tokens = context_chars // 4
        
        console.print(f"\n[bold cyan]Knowledge Base Loaded[/bold cyan]")
        console.print(f"  📁 Path: [dim]{self.kb_path.absolute()}[/dim]")
        console.print(f"  🤖 Model: [yellow]{self.model}[/yellow]")
        console.print(f"  📄 Context: [cyan]{context_lines}[/cyan] lines, [cyan]{context_chars:,}[/cyan] chars")
        console.print(f"  🔢 Estimated tokens: [magenta]~{estimated_tokens:,}[/magenta]")
        console.print()
    
    def _load_knowledge_base(self) -> str:
        """Load and format knowledge base files into context string"""
        context_parts = []
        
        # Load overview
        overview_file = self.kb_path / "database_schema_overview.json"
        if overview_file.exists():
            with open(overview_file, 'r') as f:
                overview = json.load(f)
                context_parts.append("=== DATABASE OVERVIEW ===")
                context_parts.append(f"Database: {overview.get('database_name', 'N/A')}")
                context_parts.append(f"Description: {overview.get('description', 'N/A')}")
                
                # Add table summaries
                context_parts.append("\nTABLES:")
                for table in overview.get('tables', []):
                    context_parts.append(f"- {table['name']}: {table['description']}")
        
        # Load ALL table schemas (expanded from just 5 tables)
        all_tables = [
            'airport', 'airport_geo', 'airport_reachable',
            'flight', 'flightschedule', 'flight_log',
            'passenger', 'passengerdetails', 'booking',
            'airline', 'airplane', 'airplane_type',
            'employee', 'weatherdata'
        ]
        context_parts.append("\n=== TABLE SCHEMAS ===")
        for table_name in all_tables:
            table_file = self.kb_path / f"{table_name}.json"
            if table_file.exists():
                with open(table_file, 'r') as f:
                    table_data = json.load(f)
                    context_parts.append(f"\n{table_name.upper()}:")
                    
                    # Add description if available
                    if table_data.get('description'):
                        context_parts.append(f"Description: {table_data['description']}")
                    
                    # Add columns with types
                    if table_data.get('columns'):
                        cols = [f"{col['name']} ({col.get('type', 'unknown')})" for col in table_data['columns']]
                        context_parts.append(f"Columns: {', '.join(cols)}")
                    
                    # Add foreign keys
                    if table_data.get('foreign_keys'):
                        fk_list = [f"{fk['column']} -> {fk['references_table']}.{fk.get('references_column', 'id')}" 
                                  for fk in table_data['foreign_keys']]
                        context_parts.append(f"Foreign Keys: {', '.join(fk_list)}")
                    
                    # Add indexes if available
                    if table_data.get('indexes'):
                        idx_list = [idx.get('name', 'unnamed') for idx in table_data['indexes']]
                        context_parts.append(f"Indexes: {', '.join(idx_list)}")
        
        # Load query patterns
        patterns_file = self.kb_path / "query_patterns.json"
        if patterns_file.exists():
            try:
                with open(patterns_file, 'r') as f:
                    patterns = json.load(f)
                    context_parts.append("\n=== QUERY PATTERNS ===")
                    for pattern in patterns.get('patterns', [])[:5]:
                        context_parts.append(f"\n{pattern.get('name', 'Pattern')}:")
                        context_parts.append(f"  Use: {pattern.get('use_case', 'N/A')}")
                        if pattern.get('example'):
                            context_parts.append(f"  Example: {pattern['example']}")
            except json.JSONDecodeError as e:
                console.print(f"[yellow]Warning: Could not parse {patterns_file.name}: {e}[/yellow]")
        
        # Load NL to SQL guide
        guide_file = self.kb_path / "nl_to_sql_guide.json"
        if guide_file.exists():
            try:
                with open(guide_file, 'r') as f:
                    # Read and try to parse just the first JSON object
                    content = f.read()
                    # Find the first complete JSON object
                    brace_count = 0
                    first_obj_end = 0
                    for i, char in enumerate(content):
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                first_obj_end = i + 1
                                break
                    
                    if first_obj_end > 0:
                        guide = json.loads(content[:first_obj_end])
                        context_parts.append("\n=== CONVERSION RULES ===")
                        
                        # Add entity recognition
                        if 'entity_recognition' in guide:
                            context_parts.append("\nEntity Recognition:")
                            for entity, info in list(guide['entity_recognition'].items())[:5]:
                                context_parts.append(f"- {entity}: {info.get('table', 'N/A')} table")
                        
                        # Add keyword mappings
                        if 'common_keywords_mapping' in guide:
                            context_parts.append("\nKeyword Mappings:")
                            for mapping, info in list(guide['common_keywords_mapping'].items())[:5]:
                                keywords = ', '.join(info.get('keywords', [])[:3])
                                context_parts.append(f"- {keywords} → {info.get('sql_operation', 'N/A')}")
            except (json.JSONDecodeError, Exception) as e:
                console.print(f"[yellow]Warning: Could not parse {guide_file.name}: {e}[/yellow]")
        
        # Load example queries from multiple sources
        context_parts.append("\n=== EXAMPLE QUERIES ===")
        
        # Simple examples
        simple_file = self.kb_path / "query_examples_simple.json"
        if simple_file.exists():
            try:
                with open(simple_file, 'r') as f:
                    examples = json.load(f)
                    context_parts.append("\nSimple Queries:")
                    for ex in examples.get('examples', [])[:3]:
                        desc = ex.get('description') or ex.get('name') or 'Query'
                        query = ex.get('query') or ex.get('sql', '')
                        context_parts.append(f"Q: {desc}")
                        context_parts.append(f"SQL: {query}")
            except (json.JSONDecodeError, KeyError) as e:
                console.print(f"[yellow]Warning: Could not parse {simple_file.name}[/yellow]")
        
        # Join examples
        joins_file = self.kb_path / "query_examples_joins.json"
        if joins_file.exists():
            try:
                with open(joins_file, 'r') as f:
                    examples = json.load(f)
                    context_parts.append("\nJoin Queries:")
                    for ex in examples.get('examples', [])[:3]:
                        desc = ex.get('description') or ex.get('name') or 'Query'
                        query = ex.get('query') or ex.get('sql', '')
                        context_parts.append(f"Q: {desc}")
                        context_parts.append(f"SQL: {query}")
            except (json.JSONDecodeError, KeyError) as e:
                console.print(f"[yellow]Warning: Could not parse {joins_file.name}[/yellow]")
        
        # Aggregation examples
        agg_file = self.kb_path / "query_examples_aggregations.json"
        if agg_file.exists():
            try:
                with open(agg_file, 'r') as f:
                    examples = json.load(f)
                    context_parts.append("\nAggregation Queries:")
                    for ex in examples.get('examples', [])[:3]:
                        desc = ex.get('description') or ex.get('name') or 'Query'
                        query = ex.get('query') or ex.get('sql', '')
                        context_parts.append(f"Q: {desc}")
                        context_parts.append(f"SQL: {query}")
            except (json.JSONDecodeError, KeyError) as e:
                console.print(f"[yellow]Warning: Could not parse {agg_file.name}[/yellow]")
        
        # NL to SQL examples
        nl_examples_file = self.kb_path / "nl_sql_examples.json"
        if nl_examples_file.exists():
            try:
                with open(nl_examples_file, 'r') as f:
                    examples_data = json.load(f)
                    context_parts.append("\nNatural Language Examples:")
                    for example in examples_data.get('examples', [])[:5]:
                        context_parts.append(f"Q: {example['prompt']}")
                        context_parts.append(f"SQL: {example['sql']}")
            except json.JSONDecodeError as e:
                console.print(f"[yellow]Warning: Could not parse {nl_examples_file.name}[/yellow]")
        
        return "\n".join(context_parts)
    
    def _build_prompt(self, natural_language_query: str) -> str:
        """Build the prompt for the LLM"""
        prompt = f"""You are a SQL query generator for the Flughafen airport database.

{self.context}

IMPORTANT RULES:
1. Use backticks for reserved keywords: `from`, `to`
2. Use table aliases: a (airport), f (flight), p (passenger), b (booking), al (airline)
3. Use LEFT JOIN for optional relationships (airport_geo, passengerdetails)
4. Use INNER JOIN for required relationships
5. Always add LIMIT clause for queries that might return many rows
6. Return ONLY the SQL query, no explanations
7. Use best practices to create SQL queries
8. Be explicit about table names and fields to reduce confusion
9. Use LIMIT and OFFSET to show the first 10 results

Natural Language Query: {natural_language_query}

SQL Query:"""
        return prompt
    
    def generate_sql(self, natural_language_query: str) -> dict:
        """Generate SQL from natural language using Ollama
        
        Returns:
            dict with keys: sql, tokens, time_taken, eval_count, prompt_eval_count
        """
        prompt = self._build_prompt(natural_language_query)
        
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
                "top_k": 40
            }
        }
        
        try:
            start_time = time.time()
            response = requests.post(self.ollama_url, json=payload, timeout=120)
            response.raise_for_status()
            end_time = time.time()
            
            result = response.json()
            sql_query = result.get("response", "").strip()
            
            # Clean up the response
            sql_query = self._clean_sql(sql_query)
            
            # Extract token and timing information
            return {
                "sql": sql_query,
                "time_taken": round(end_time - start_time, 2),
                "prompt_eval_count": result.get("prompt_eval_count", 0),
                "eval_count": result.get("eval_count", 0),
                "total_tokens": result.get("prompt_eval_count", 0) + result.get("eval_count", 0),
                "eval_duration_ms": result.get("eval_duration", 0) / 1_000_000,  # Convert to ms
                "prompt_eval_duration_ms": result.get("prompt_eval_duration", 0) / 1_000_000,
            }
            
        except requests.exceptions.RequestException as e:
            return {
                "sql": f"Error connecting to Ollama: {e}",
                "time_taken": 0,
                "prompt_eval_count": 0,
                "eval_count": 0,
                "total_tokens": 0,
                "eval_duration_ms": 0,
                "prompt_eval_duration_ms": 0,
            }
    
    def _clean_sql(self, sql: str) -> str:
        """Clean up generated SQL query and separate from explanations"""
        # Remove markdown code blocks if present
        sql = sql.replace("```sql", "").replace("```", "")
        
        # Remove common prefixes
        prefixes = ["SQL Query:", "Query:", "SQL:"]
        for prefix in prefixes:
            if sql.startswith(prefix):
                sql = sql[len(prefix):].strip()
        
        # Split by lines and find where SQL ends
        lines = sql.split('\n')
        sql_lines = []
        found_semicolon = False
        
        for line in lines:
            line_stripped = line.strip()
            
            # Skip empty lines at the start
            if not sql_lines and not line_stripped:
                continue
            
            # If we found a semicolon and hit a non-empty line, it's likely an explanation
            if found_semicolon and line_stripped:
                # Check if this looks like SQL continuation (unlikely after semicolon)
                # or an explanation
                line_lower = line_stripped.lower()
                
                # Common explanation patterns
                explanation_patterns = [
                    'this sql', 'this query', 'the sql', 'the query', 'the above',
                    'note:', 'explanation:', 'this will', 'this returns',
                    'here', 'above query', 'in this example', 'in the example',
                    'we are using', 'we use', 'the resulting'
                ]
                
                if any(line_lower.startswith(pattern) for pattern in explanation_patterns):
                    break
            
            # Check if this line looks like an explanation (not SQL)
            line_lower = line_stripped.lower()
            explanation_starters = [
                'this sql', 'this query', 'the sql', 'the query',
                'note:', 'explanation:', 'this will', 'this returns',
                'here', 'above', 'below', 'in this example', 'in the example',
                'we are using', 'we use', 'the resulting'
            ]
            
            is_explanation = any(
                line_lower.startswith(starter) 
                for starter in explanation_starters
            )
            
            # If we've started collecting SQL and hit an explanation, stop
            if sql_lines and is_explanation:
                break
            
            # Check if line has SQL keywords at the start (more strict)
            sql_start_keywords = ['SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 
                                  'OUTER', 'LIMIT', 'ORDER', 'GROUP', 'HAVING', 'INSERT', 
                                  'UPDATE', 'DELETE', 'WITH', 'UNION', 'AND', 'OR', 'ON']
            
            # For lines after we've started collecting, be more lenient
            if sql_lines:
                # If it's not an explanation and not empty, include it
                if line_stripped and not is_explanation:
                    sql_lines.append(line)
                    if ';' in line:
                        found_semicolon = True
                elif not line_stripped:
                    # Empty line - include if we haven't hit semicolon yet
                    if not found_semicolon:
                        sql_lines.append(line)
            else:
                # First line - must start with a SQL keyword
                first_word = line_stripped.split()[0].upper() if line_stripped.split() else ""
                if first_word in sql_start_keywords:
                    sql_lines.append(line)
        
        # Join the SQL lines back together
        sql = '\n'.join(sql_lines).strip()
        
        # Remove trailing semicolon if present (we'll add it back when displaying)
        sql = sql.rstrip(";").strip()
        
        # If we ended up with nothing, return the original (fallback)
        if not sql:
            sql = lines[0] if lines else ""
        
        return sql
    
    def validate_sql(self, sql: str) -> dict:
        """Validate and analyze SQL query
        
        Returns:
            dict with keys: is_valid, formatted_sql, errors, warnings
        """
        result = {
            "is_valid": False,
            "formatted_sql": "",
            "errors": [],
            "warnings": []
        }
        
        try:
            # Parse the SQL
            parsed = sqlparse.parse(sql)
            
            if not parsed:
                result["errors"].append("Empty or invalid SQL query")
                return result
            
            # Format the SQL
            result["formatted_sql"] = sqlparse.format(
                sql,
                reindent=True,
                keyword_case='upper',
                indent_width=2
            )
            
            # Basic validation checks
            sql_upper = sql.upper()
            
            # Check for SELECT statement
            if not any(stmt.get_type() == 'SELECT' for stmt in parsed):
                result["warnings"].append("Query does not appear to be a SELECT statement")
            
            # Check for common issues
            if 'SELECT *' in sql_upper:
                result["warnings"].append("Using SELECT * - consider specifying columns explicitly")
            
            if 'LIMIT' not in sql_upper:
                result["warnings"].append("No LIMIT clause - query might return many rows")
            
            # Check for balanced parentheses
            if sql.count('(') != sql.count(')'):
                result["errors"].append("Unbalanced parentheses")
                return result
            
            # Check for balanced quotes
            single_quotes = sql.count("'")
            if single_quotes % 2 != 0:
                result["errors"].append("Unbalanced single quotes")
                return result
            
            # If we got here, SQL is likely valid
            result["is_valid"] = True
            
        except Exception as e:
            result["errors"].append(f"Parsing error: {str(e)}")
        
        return result
    
    def pretty_print_sql(self, sql: str, title: str = "Generated SQL"):
        """Pretty print SQL with syntax highlighting using rich"""
        # Validate SQL first
        validation = self.validate_sql(sql)
        
        # Use formatted SQL if available
        display_sql = validation["formatted_sql"] if validation["formatted_sql"] else sql
        
        # Create syntax highlighted SQL
        syntax = Syntax(
            display_sql,
            "sql",
            theme="monokai",
            line_numbers=True,
            word_wrap=True
        )
        
        # Determine panel style based on validation
        if validation["errors"]:
            border_style = "red"
            title = f"❌ {title} (Invalid)"
        elif validation["warnings"]:
            border_style = "yellow"
            title = f"⚠️  {title} (Valid with warnings)"
        else:
            border_style = "green"
            title = f"✅ {title} (Valid)"
        
        # Print the SQL in a panel
        console.print(Panel(syntax, title=title, border_style=border_style))
        
        # Print validation messages
        if validation["errors"]:
            console.print("\n[bold red]Errors:[/bold red]")
            for error in validation["errors"]:
                console.print(f"  • {error}", style="red")
        
        if validation["warnings"]:
            console.print("\n[bold yellow]Warnings:[/bold yellow]")
            for warning in validation["warnings"]:
                console.print(f"  • {warning}", style="yellow")


def interactive_mode(converter: NLPToSQL, verbose: bool = False):
    """Run in interactive mode"""
    console.print("\n" + "=" * 60, style="bold cyan")
    console.print("INTERACTIVE MODE", style="bold cyan")
    console.print("=" * 60, style="bold cyan")
    console.print("Enter your natural language queries (or 'quit' to exit)")
    if verbose:
        console.print("[dim]Verbose mode: Will show full prompt for first query[/dim]")
    console.print("=" * 60 + "\n", style="bold cyan")
    
    first_query = True
    
    while True:
        try:
            query = input("\n🔍 Your query: ").strip()
            
            if query.lower() in ['quit', 'exit', 'q']:
                console.print("Goodbye!", style="bold green")
                break
            
            if not query:
                continue
            
            # Show prompt for first query if verbose
            if verbose and first_query:
                prompt = converter._build_prompt(query)
                console.print("\n[bold yellow]📝 Full Prompt (first query only):[/bold yellow]")
                console.print(Panel(
                    prompt,
                    title="Prompt sent to LLM",
                    border_style="yellow",
                    expand=False
                ))
                first_query = False
            
            console.print("\n⏳ Generating SQL...", style="yellow")
            result = converter.generate_sql(query)
            
            # Pretty print the SQL with validation
            console.print()
            converter.pretty_print_sql(result['sql'], title=f"Query: {query[:50]}...")
            
            # Print stats with detailed token breakdown
            console.print(f"\n[bold]📊 Stats:[/bold]")
            console.print(f"   ⏱️  Time: [cyan]{result['time_taken']}s[/cyan]")
            console.print(f"   📥 Input Tokens: [yellow]{result['prompt_eval_count']:,}[/yellow]")
            console.print(f"   📤 Output Tokens: [green]{result['eval_count']:,}[/green]")
            console.print(f"   🔢 Total Tokens: [cyan]{result['total_tokens']:,}[/cyan]")
            if result['time_taken'] > 0:
                console.print(f"   ⚡ Generation Speed: [cyan]{result['eval_count'] / result['time_taken']:,.1f} tokens/s[/cyan]")
            
            # Show token ratio
            if result['prompt_eval_count'] > 0:
                ratio = result['eval_count'] / result['prompt_eval_count']
                console.print(f"   📊 Output/Input Ratio: [magenta]{ratio:.2f}[/magenta]")
            
        except KeyboardInterrupt:
            console.print("\n\nGoodbye!", style="bold green")
            break
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] {e}")


def demo_mode(converter: NLPToSQL, verbose: bool = False):
    """Run demo with test queries"""
    console.print("\n" + "=" * 60, style="bold cyan")
    console.print("DEMO MODE - Running test queries", style="bold cyan")
    if verbose:
        console.print("[dim]Verbose mode: Will show full prompt for first query[/dim]")
    console.print("=" * 60 + "\n", style="bold cyan")
    
    test_queries = [
        "Get airport with geographic details by IATA code JFK",
        "Show me all flights from JFK to LAX",
        "Find 10 passengers from United States",
        "How many bookings does passenger 1000 have?",
        "Flight manifest - all passengers on a specific flight 115",
    ]
    
    total_time = 0
    total_tokens = 0
    
    for i, query in enumerate(test_queries, 1):
        console.print(f"\n[bold]{i}. Natural Language:[/bold] [italic]{query}[/italic]")
        console.print("-" * 60, style="dim")
        
        # Show prompt for first query if verbose
        if verbose and i == 1:
            prompt = converter._build_prompt(query)
            console.print("\n[bold yellow]📝 Full Prompt (first query only):[/bold yellow]")
            console.print(Panel(
                prompt,
                title="Prompt sent to LLM",
                border_style="yellow",
                expand=False
            ))
            console.print()
        
        result = converter.generate_sql(query)
        
        # Pretty print the SQL with validation
        converter.pretty_print_sql(result['sql'], title=f"Query {i}")
        
        # Display detailed stats
        console.print(f"\n[bold]📊 Stats:[/bold]")
        console.print(f"   ⏱️  [cyan]{result['time_taken']}s[/cyan] | "
                     f"📥 [yellow]{result['prompt_eval_count']:,}[/yellow] in | "
                     f"📤 [green]{result['eval_count']:,}[/green] out | "
                     f"⚡ [cyan]{result['eval_count'] / result['time_taken']:,.1f} tok/s[/cyan]")
        
        total_time += result['time_taken']
        total_tokens += result['total_tokens']
        console.print()
    
    console.print("\n" + "=" * 60, style="bold green")
    console.print(f"📈 SUMMARY: {len(test_queries)} queries in {total_time:.2f}s | {total_tokens:,} total tokens", style="bold green")
    console.print("=" * 60, style="bold green")


def main():
    """Main entry point"""
    print("=" * 60)
    print("Natural Language to SQL Query Generator")
    print("=" * 60)
    
    # Parse arguments
    model = None  # Will use .env default
    mode = "demo"
    verbose = False
    
    # Check for flags and arguments
    args = sys.argv[1:]
    for arg in args:
        if arg == "--verbose" or arg == "-v":
            verbose = True
        elif arg == "interactive":
            mode = "interactive"
        elif not arg.startswith("-"):
            model = arg
    
    # Initialize converter (will use OLLAMA_MODEL from .env if model is None)
    try:
        converter = NLPToSQL(model=model)
    except Exception as e:
        print(f"Error initializing converter: {e}")
        return
    
    # Run in selected mode
    if mode == "interactive":
        interactive_mode(converter, verbose=verbose)
    else:
        demo_mode(converter, verbose=verbose)
        
        # Offer interactive mode
        print("\n" + "=" * 60)
        response = input("Would you like to try interactive mode? (y/n): ").strip().lower()
        if response == 'y':
            interactive_mode(converter, verbose=verbose)


if __name__ == "__main__":
    main()
