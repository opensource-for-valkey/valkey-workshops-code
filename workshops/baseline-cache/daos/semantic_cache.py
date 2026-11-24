"""
Semantic Search DAO for NLP to SQL with Caching
Uses embeddings to find similar queries and caches results in Valkey/Redis
"""

import json
import time
import os
import re
from typing import Dict, Any, List
import numpy as np
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.environ.get("WORKSHOP_ENV_FILE", ".env"))

from valkey_client_manager import ValkeyClientManager, scan_keys
from rich.console import Console
print = Console(soft_wrap=True).print

# Import the semantic search core (lazy loaded)
try:
    from core.semantic_search import SemanticSearch
except ModuleNotFoundError:
    # If running as a script, add parent directory to path
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from core.semantic_search import SemanticSearch

# Import the NLP to SQL converter
try:
    from daos.nlp_to_sql import NLPToSQL
except ModuleNotFoundError:
    from nlp_to_sql import NLPToSQL


class SemanticSQLCache:
    """
    Semantic search cache for SQL queries using embeddings and Valkey/Redis
    
    Key structure:
    - semantic:prompt:<hash>  -> db:query:<hash2>  (maps prompt to query result key)
    - db:query:<hash2>        -> {sql, time_taken, tokens, etc.}  (NLP result)
    - db:cache:<hash2>        -> <actual query result>  (SQL execution result)
    - embedding:prompt:<hash> -> <embedding vector>  (prompt embedding)
    """
    
    def __init__(
        self,
        valkey_host: str = None,
        valkey_port: int = None,
        embedding_model: str = None,
        similarity_threshold: float = None,
        ollama_model: str = None,
        use_mmr: bool = False,
        mmr_lambda: float = 0.5,
        verbose: bool = False
    ):
        # Use environment variables with fallbacks
        if valkey_host is None:
            valkey_host = os.getenv("VECTOR_HOST", os.getenv("VALKEY_HOST", "127.0.0.1"))
        if valkey_port is None:
            valkey_port = int(os.getenv("VECTOR_PORT", os.getenv("VALKEY_PORT", "6379")))
        if embedding_model is None:
            embedding_model = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        if similarity_threshold is None:
            similarity_threshold = float(os.getenv("SIMILARITY_THRESHOLD", "0.70"))
        if ollama_model is None:
            ollama_model = os.getenv("OLLAMA_MODEL", "codellama")
        
        self.verbose = verbose
        self.key_prefix = os.getenv("CACHE_KEY_PREFIX", "baseline:attendee:")
        if not re.fullmatch(r"[A-Za-z0-9:_{}-]+:", self.key_prefix):
            raise ValueError("CACHE_KEY_PREFIX must be a nonempty literal prefix ending in ':'")
        self.embedding_model_name = embedding_model
        self.use_mmr = use_mmr
        self.mmr_lambda = mmr_lambda
        
        # Connect to Valkey
        if verbose:
            print(f"\n{'='*70}")
            print(f"Valkey Connection")
            print(f"{'='*70}")
            print(f"Host: {valkey_host}")
            print(f"Port: {valkey_port}")
        
        self.client_manager = ValkeyClientManager(env_prefix="VECTOR", fallback_prefix="VALKEY", url=f"valkey://{valkey_host}:{valkey_port}")
        self.valkey_client = self.client_manager.client
        
        # Test connection and show info
        try:
            self.valkey_client.ping()
            if verbose:
                print(f"✅ Connected successfully")
                info = dict(line.split(":", 1) for line in self.valkey_client.info().decode().splitlines() if ":" in line)
                print(f"   Version: {info.get('valkey_version', 'unknown')}")
                print(f"   Memory: {info.get('used_memory_human', 'unknown')}")
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            raise
        
        # Lazy-loaded semantic search instance
        self._semantic_search = None
        
        # Initialize NLP to SQL converter
        self.nlp_converter = NLPToSQL(model=ollama_model)
        
        # Similarity threshold for considering queries as "similar"
        self.similarity_threshold = similarity_threshold
        
        if verbose:
            print(f"\n{'='*70}")
            print(f"Configuration")
            print(f"{'='*70}")
            print(f"Similarity threshold: {similarity_threshold}")
            print(f"Ollama model: {ollama_model}")
            print(f"Embedding model: {embedding_model}")
            print(f"Use MMR reranking: {use_mmr}")
            if use_mmr:
                print(f"MMR lambda (relevance/diversity): {mmr_lambda}")
        
        # Create vector search index if it doesn't exist
        self._create_index(verbose=verbose)
    
    @property
    def semantic_search(self) -> SemanticSearch:
        """Lazy-load the semantic search instance"""
        if self._semantic_search is None:
            self._semantic_search = SemanticSearch(
                valkey_client=self.valkey_client,
                embedding_model=self.embedding_model_name,
                use_mmr=self.use_mmr,
                mmr_lambda=self.mmr_lambda,
                verbose=self.verbose
            )
        return self._semantic_search
    
    def _create_index(self, verbose=False):
        """Create vector search index for prompt embeddings"""
        # Lazy load semantic search to create the index
        self.semantic_search.create_vector_index(
            index_name=f"{self.key_prefix}prompt_embeddings",
            key_prefix=f"{self.key_prefix}embedding:prompt:",
            additional_fields=[("prompt", "TAG"), ("query_key", "TAG")],
            verbose=verbose
        )
    
    def _hash_text(self, text: str) -> str:
        """Generate SHA1 hash of text"""
        return SemanticSearch.hash_text(text)
    
    def _generate_embedding(self, text: str) -> np.ndarray:
        """Generate embedding vector for text"""
        return self.semantic_search.generate_embedding(text)
    
    def _search_similar_prompts(self, embedding: np.ndarray, k: int = 5) -> List[Dict]:
        """Search for similar prompts using vector search or fallback to brute force"""
        return self.semantic_search.search_similar(
            embedding=embedding,
            index_name=f"{self.key_prefix}prompt_embeddings",
            key_prefix=f"{self.key_prefix}embedding:prompt:",
            k=k
        )

    def get_or_generate_sql(self, prompt: str, verbose: bool = True) -> Dict[str, Any]:
        """
        Get SQL for a prompt, using cache if similar query exists
        
        Returns:
            Dict with keys: sql, time_taken, tokens, cache_hit, similar_prompt, etc.
        """
        start_time = time.time()
        
        # Exact matches avoid both model loading and embedding generation.
        prompt_hash = self._hash_text(prompt)
        
        # Check if we have an exact match first
        semantic_key = f"{self.key_prefix}semantic:prompt:{prompt_hash}"
        cached_query_key = self.valkey_client.get(semantic_key)
        
        if cached_query_key:
            cached_query_key = cached_query_key.decode('utf-8')
            if verbose:
                print(f"\n🎯 Exact cache hit!")
                print(f"   Semantic key: {semantic_key}")
                print(f"   Query key: {cached_query_key}")
            
            # Get the cached query result
            query_data = self.valkey_client.get(cached_query_key)
            if query_data:
                result = json.loads(query_data.decode('utf-8'))
                result['cache_hit'] = True
                result['cache_type'] = 'exact'
                result['lookup_time'] = round(time.time() - start_time, 3)
                if verbose:
                    print(f"   SQL: {result.get('sql', 'N/A')[:80]}...")
                return result
        
        # Generate the embedding only after the exact lookup misses.
        prompt_embedding = self._generate_embedding(prompt)
        # Search for similar prompts
        if verbose:
            print(f"🔍 Searching for similar prompts...")
            print(f"   Prompt hash: {prompt_hash}")
            print(f"   Embedding dimension: {len(prompt_embedding)}")
        
        similar_prompts = self._search_similar_prompts(prompt_embedding, k=5)
        
        if verbose:
            # Check how many embeddings are in the cache
            embedding_count = len(list(scan_keys(self.valkey_client, f"{self.key_prefix}embedding:prompt:*", count=100)))
            print(f"   Embeddings in cache: {embedding_count}")
            
            if similar_prompts:
                print(f"\n📊 Found {len(similar_prompts)} similar prompt(s):")
                for i, sim in enumerate(similar_prompts, 1):
                    print(f"   {i}. Similarity: {sim.get('similarity', 0):.3f} | Prompt: {sim.get('prompt', 'N/A')[:60]}...")
                print(f"   Threshold: {self.similarity_threshold}")
            else:
                print(f"   ⚠️  No similar prompts found (vector search returned empty)")
                if embedding_count > 0:
                    print(f"   ⚠️  WARNING: {embedding_count} embeddings exist but search returned nothing!")
        
        # Check if any similar prompt meets the threshold
        for similar in similar_prompts:
            if similar['similarity'] >= self.similarity_threshold:
                if verbose:
                    print(f"✨ Found similar prompt (similarity: {similar['similarity']:.3f})")
                    print(f"   Original: {similar['prompt']}")
                    print(f"   Current:  {prompt}")
                
                # Get the cached query result
                query_data = self.valkey_client.get(similar['query_key'])
                if query_data:
                    result = json.loads(query_data.decode('utf-8'))
                    result['cache_hit'] = True
                    result['cache_type'] = 'semantic'
                    result['similarity'] = similar['similarity']
                    result['similar_prompt'] = similar['prompt']
                    result['lookup_time'] = round(time.time() - start_time, 3)
                    
                    # Also cache this exact prompt for future exact matches
                    self.valkey_client.set(semantic_key, similar['query_key'])
                    
                    return result
        
        # No similar prompt found, generate new SQL
        if verbose:
            print(f"🤖 No similar prompt found. Generating new SQL with LLM...")
        
        result = self.nlp_converter.generate_sql(prompt)
        result['cache_hit'] = False
        result['lookup_time'] = round(time.time() - start_time, 3)
        
        # Cache the result
        sql_hash = self._hash_text(result['sql'])
        query_key = f"{self.key_prefix}db:query:{sql_hash}"
        
        if verbose:
            print(f"\n{'─'*70}")
            print(f"💾 Caching new result:")
            print(f"{'─'*70}")
        
        # Store the query result
        self.valkey_client.set(query_key, json.dumps(result))
        if verbose:
            print(f"\n1️⃣  Query Result Key:")
            print(f"   Key: {query_key}")
            print(f"   Value: {json.dumps(result, indent=2)}")
        
        # Store the semantic mapping
        self.valkey_client.set(semantic_key, query_key)
        if verbose:
            print(f"\n2️⃣  Semantic Mapping Key:")
            print(f"   Key: {semantic_key}")
            print(f"   Value: {query_key}")
        
        # Store the embedding for vector search
        embedding_key = f"{self.key_prefix}embedding:prompt:{prompt_hash}"
        embedding_data = {
            "prompt": prompt,
            "query_key": query_key,
            "embedding": prompt_embedding.astype(np.float32).tobytes()
        }
        self.valkey_client.hset(
            embedding_key,
            field_value_map=embedding_data
        )
        if verbose:
            print(f"\n3️⃣  Embedding Hash Key:")
            print(f"   Key: {embedding_key}")
            print(f"   Fields:")
            print(f"     - prompt: {prompt}")
            print(f"     - query_key: {query_key}")
            print(f"     - embedding: <{len(prompt_embedding)} dimensional vector>")
            print(f"   Vector preview: [{prompt_embedding[:3].tolist()}...{prompt_embedding[-3:].tolist()}]")
            print(f"{'─'*70}\n")
        
        return result
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        stats = {
            "total_prompts": len(list(scan_keys(self.valkey_client, f"{self.key_prefix}semantic:prompt:*"))),
            "total_queries": len(list(scan_keys(self.valkey_client, f"{self.key_prefix}db:query:*"))),
            "total_embeddings": len(list(scan_keys(self.valkey_client, f"{self.key_prefix}embedding:prompt:*"))),
        }
        return stats
    
    def clear_cache(self):
        """Clear all cached data"""
        print("Clearing cache...")
        
        # Delete all semantic keys
        for key in scan_keys(self.valkey_client, f"{self.key_prefix}semantic:prompt:*"):
            self.valkey_client.delete([key])
        
        for key in scan_keys(self.valkey_client, f"{self.key_prefix}db:query:*"):
            self.valkey_client.delete([key])
        
        for key in scan_keys(self.valkey_client, f"{self.key_prefix}embedding:prompt:*"):
            self.valkey_client.delete([key])
        
        print("✅ Cache cleared")
    
    def drop_index(self):
        """Drop the vector search index if it exists"""
        # Use semantic search to drop the index
        self.semantic_search.drop_index(f"{self.key_prefix}prompt_embeddings", verbose=True)

    def close(self):
        """Release the native vector connection owned by this DAO."""
        self.client_manager.close()


def main():
    """Simple validation of semantic search functionality"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Semantic Cache DAO - Validation and Management")
    parser.add_argument('--flush', action='store_true', help='Clear all cache data and drop the index')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('--mmr', action='store_true', help='Enable MMR (Maximal Marginal Relevance) reranking for diversity')
    parser.add_argument('--mmr-lambda', type=float, default=0.5, help='MMR lambda parameter (0=diversity, 1=relevance). Default: 0.5')
    args = parser.parse_args()
    
    print("=" * 70)
    print("Semantic Cache DAO")
    print("=" * 70)
    
    try:
        # Initialize cache
        print("\n1. Initializing SemanticSQLCache...")
        cache = SemanticSQLCache(
            verbose=args.verbose,
            use_mmr=args.mmr,
            mmr_lambda=args.mmr_lambda
        )
        
        # Handle flush flag
        if args.flush:
            print("\n🗑️  Flushing cache and index...")
            cache.clear_cache()
            cache.drop_index()
            print("\n🔄 Recreating index...")
            cache._create_index(verbose=args.verbose)
            print("\n✅ Flush complete! Cache and index are ready for use.")
        
        # Test queries
        test_queries = [
            "Show me all passengers on flight 115",
            "Get passenger list for flight 115",  # Similar query
            "Find airport details for JFK",
        ]
        
        print("\n2. Testing semantic search with sample queries...")
        if args.mmr:
            print(f"   (Using MMR reranking with lambda={args.mmr_lambda})")
        for i, query in enumerate(test_queries, 1):
            print(f"\n{'─'*70}")
            print(f"Query {i}: {query}")
            print('─'*70)
            
            result = cache.get_or_generate_sql(query, verbose=args.verbose)
            
            print(f"SQL: {result['sql']}")
            print(f"Cache hit: {result['cache_hit']}")
            if result['cache_hit']:
                print(f"Cache type: {result.get('cache_type', 'unknown')}")
                if result.get('cache_type') == 'semantic':
                    print(f"Similarity: {result.get('similarity', 0):.3f}")
            else:
                print(f"Time taken: {result.get('time_taken', 0):.6f}s")
        
        # Show stats
        print(f"\n{'='*70}")
        print("3. Cache Statistics")
        print('='*70)
        stats = cache.get_cache_stats()
        for key, value in stats.items():
            print(f"{key}: {value}")
        
        print(f"\n{'='*70}")
        print("✅ Validation complete!")
        print('='*70)
        
    except Exception as e:
        print(f"\n❌ Error during validation: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
