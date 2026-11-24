"""
Airport Leaderboard DAO

Provides leaderboard and statistics queries for airports including:
- Flight count for a specific airport on a given date
- Top airports by flight count on a given date
- Top airports by passenger count on a given date
"""

import os
from rich.console import Console
print = Console(soft_wrap=True).print
import sys
from pathlib import Path

# Add parent directory to path when running as script
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date, datetime
from typing import List, Dict, Optional
from dotenv import load_dotenv
from sqlalchemy import text
from core import get_db_engine

# Load environment variables
load_dotenv(os.environ.get("WORKSHOP_ENV_FILE", ".env"))


class AirportLeaderboard:
    """Airport statistics and leaderboard queries."""
    
    def __init__(self):
        """Initialize database connection."""
        self.db_engine = get_db_engine()
    
    def get_airport_flights_on_date(
        self, 
        airport_iata: str, 
        flight_date: Optional[date] = None
    ) -> Dict:
        """
        Get the number of flights for a specific airport on a given date.
        Counts both departures and arrivals.
        
        Args:
            airport_iata: IATA code of the airport (e.g., 'JFK', 'LAX')
            flight_date: Date to query flights for (defaults to today)
        
        Returns:
            Dictionary with airport info and flight counts:
            {
                'airport_id': int,
                'iata': str,
                'icao': str,
                'name': str,
                'date': str,
                'departures': int,
                'arrivals': int,
                'total_flights': int
            }
        """
        if flight_date is None:
            flight_date = date.today()
        
        query = text("""
            SELECT 
                a.airport_id,
                a.iata,
                a.icao,
                a.name,
                :flight_date as date,
                COUNT(DISTINCT CASE WHEN f.from = a.airport_id THEN f.flight_id END) as departures,
                COUNT(DISTINCT CASE WHEN f.to = a.airport_id THEN f.flight_id END) as arrivals,
                COUNT(DISTINCT f.flight_id) as total_flights
            FROM airport a
            LEFT JOIN flight f ON (f.from = a.airport_id OR f.to = a.airport_id)
                AND DATE(f.departure) = :flight_date
            WHERE a.iata = :airport_iata
                AND a.iata IS NOT NULL
            GROUP BY a.airport_id, a.iata, a.icao, a.name
        """)
        
        with self.db_engine.connect() as conn:
            result = conn.execute(
                query, 
                {
                    "airport_iata": airport_iata.upper(),
                    "flight_date": flight_date.strftime("%Y-%m-%d")
                }
            )
            row = result.fetchone()
            
            if row:
                return dict(row._mapping)
            return None
    
    def get_top_airports_by_flights(
        self, 
        flight_date: Optional[date] = None, 
        limit: int = 10
    ) -> List[Dict]:
        """
        Get top airports by flight count on a given date.
        
        Args:
            flight_date: Date to query flights for (defaults to today)
            limit: Number of top airports to return (default: 10)
        
        Returns:
            List of dictionaries with airport info and flight counts:
            [
                {
                    'rank': int,
                    'airport_id': int,
                    'iata': str,
                    'icao': str,
                    'name': str,
                    'departures': int,
                    'arrivals': int,
                    'total_flights': int
                },
                ...
            ]
        """
        if flight_date is None:
            flight_date = date.today()
        
        query = text("""
            SELECT 
                a.airport_id,
                a.iata,
                a.icao,
                a.name,
                COUNT(DISTINCT CASE WHEN f.from = a.airport_id THEN f.flight_id END) as departures,
                COUNT(DISTINCT CASE WHEN f.to = a.airport_id THEN f.flight_id END) as arrivals,
                COUNT(DISTINCT f.flight_id) as total_flights
            FROM airport a
            INNER JOIN flight f ON (f.from = a.airport_id OR f.to = a.airport_id)
            WHERE DATE(f.departure) = :flight_date
                AND a.iata IS NOT NULL
            GROUP BY a.airport_id, a.iata, a.icao, a.name
            HAVING total_flights > 0
            ORDER BY total_flights DESC, a.name ASC
            LIMIT :limit
        """)
        
        with self.db_engine.connect() as conn:
            result = conn.execute(
                query,
                {
                    "flight_date": flight_date.strftime("%Y-%m-%d"),
                    "limit": limit
                }
            )
            rows = result.fetchall()
            
            # Add rank to results
            return [
                {**dict(row._mapping), 'rank': idx + 1}
                for idx, row in enumerate(rows)
            ]
    
    def get_top_airports_by_passengers(
        self, 
        flight_date: Optional[date] = None, 
        limit: int = 10
    ) -> List[Dict]:
        """
        Get top airports by passenger count on a given date.
        
        Args:
            flight_date: Date to query passengers for (defaults to today)
            limit: Number of top airports to return (default: 10)
        
        Returns:
            List of dictionaries with airport info and passenger counts:
            [
                {
                    'rank': int,
                    'airport_id': int,
                    'iata': str,
                    'icao': str,
                    'name': str,
                    'departing_passengers': int,
                    'arriving_passengers': int,
                    'total_passengers': int,
                    'total_flights': int
                },
                ...
            ]
        """
        if flight_date is None:
            flight_date = date.today()
        
        query = text("""
            SELECT 
                a.airport_id,
                a.iata,
                a.icao,
                a.name,
                COUNT(DISTINCT CASE WHEN f.from = a.airport_id THEN b.booking_id END) as departing_passengers,
                COUNT(DISTINCT CASE WHEN f.to = a.airport_id THEN b.booking_id END) as arriving_passengers,
                COUNT(DISTINCT b.booking_id) as total_passengers,
                COUNT(DISTINCT f.flight_id) as total_flights
            FROM airport a
            INNER JOIN flight f ON (f.from = a.airport_id OR f.to = a.airport_id)
            INNER JOIN booking b ON b.flight_id = f.flight_id
            WHERE DATE(f.departure) = :flight_date
                AND a.iata IS NOT NULL
            GROUP BY a.airport_id, a.iata, a.icao, a.name
            HAVING total_passengers > 0
            ORDER BY total_passengers DESC, a.name ASC
            LIMIT :limit
        """)
        
        with self.db_engine.connect() as conn:
            result = conn.execute(
                query,
                {
                    "flight_date": flight_date.strftime("%Y-%m-%d"),
                    "limit": limit
                }
            )
            rows = result.fetchall()
            
            # Add rank to results
            return [
                {**dict(row._mapping), 'rank': idx + 1}
                for idx, row in enumerate(rows)
            ]
    

    def close(self):
        """Close database connection."""
        self.db_engine.dispose()


# Example usage
if __name__ == "__main__":
    import argparse
    from datetime import date
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Airport Leaderboard Demo")
    parser.add_argument(
        "--date",
        type=str,
        help="Date in YYYY-MM-DD format (defaults to today)",
        default=None
    )
    args = parser.parse_args()
    
    # Parse date or use today
    if args.date:
        try:
            query_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"Error: Invalid date format '{args.date}'. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        query_date = date.today()
    
    leaderboard = AirportLeaderboard()
    
    print("=" * 80)
    print("Airport Leaderboard Demo")
    print("=" * 80)
    print(f"Query Date: {query_date.strftime('%Y-%m-%d')}")
    
    # Example 1: Get flights for a specific airport on a date
    print(f"\n1. Flights for JFK on {query_date}:")
    print("-" * 80)
    result = leaderboard.get_airport_flights_on_date("JFK", query_date)
    if result:
        print(f"   Airport: {result['name']} ({result['iata']})")
        print(f"   Date: {result['date']}")
        print(f"   Departures: {result['departures']}")
        print(f"   Arrivals: {result['arrivals']}")
        print(f"   Total Flights: {result['total_flights']}")
    else:
        print("   No data found")
    
    # Example 2: Top 5 airports by flights on a date
    print(f"\n2. Top 5 Airports by Flight Count on {query_date}:")
    print("-" * 80)
    results = leaderboard.get_top_airports_by_flights(query_date, limit=5)
    for airport in results:
        print(f"   #{airport['rank']}: {airport['name']} ({airport['iata']}) - "
              f"{airport['total_flights']} flights "
              f"({airport['departures']} dep, {airport['arrivals']} arr)")
    
    # Example 3: Top 5 airports by passengers on a date
    print(f"\n3. Top 5 Airports by Passenger Count on {query_date}:")
    print("-" * 80)
    results = leaderboard.get_top_airports_by_passengers(query_date, limit=5)
    for airport in results:
        print(f"   #{airport['rank']}: {airport['name']} ({airport['iata']}) - "
              f"{airport['total_passengers']:,} passengers on {airport['total_flights']} flights")
    
    # Cleanup
    leaderboard.close()
    print("\n" + "=" * 80)
