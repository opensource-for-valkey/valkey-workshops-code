"""
RDBMS Connection Manager

Centralized connection management for relational databases.
Supports MySQL, MariaDB, and PostgreSQL via SQLAlchemy.
"""

import os
from typing import Optional
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL

# Load environment variables
load_dotenv()


def quote_identifier(engine: Engine, identifier: str) -> str:
    """Quote a SQL identifier using the configured database dialect."""
    return engine.dialect.identifier_preparer.quote_identifier(identifier)


class RDBMSConnection:
    """Factory and wrapper for RDBMS connections using SQLAlchemy."""
    
    def __init__(
        self,
        db_type: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
        **engine_kwargs
    ):
        """
        Initialize database engine based on environment variables or parameters.
        
        Args:
            db_type: Database type ('mysql', 'mariadb', 'postgresql'). 
                    Defaults to DB_ENGINE env var or 'mysql'
            host: Database host. Defaults to DB_HOST env var or 'localhost'
            port: Database port. Defaults to DB_PORT env var or '3306'
            user: Database user. Defaults to DB_USER env var or 'root'
            password: Database password. Defaults to DB_PASSWORD env var or ''
            database: Database name. Defaults to DB_NAME env var or 'flughafendb_large'
            **engine_kwargs: Additional arguments passed to create_engine()
        """
        self.db_type = (db_type or os.getenv("DB_ENGINE", "mysql")).lower()
        self.host = host or os.getenv("DB_HOST", "localhost")
        self.port = port or os.getenv("DB_PORT", "3306")
        self.user = user or os.getenv("DB_USER", "root")
        self.password = password or os.getenv("DB_PASSWORD", "")
        self.database = database or os.getenv("DB_NAME", "flughafendb_large")
        
        self.engine = self._create_engine(**engine_kwargs)
    
    def _create_engine(self, **engine_kwargs) -> Engine:
        """Create SQLAlchemy engine based on database type."""
        connection_string = self._build_connection_string()
        return create_engine(connection_string, **engine_kwargs)
    
    def _build_connection_string(self) -> URL:
        """Build a URL without interpolating or misparsing credentials."""
        if self.db_type in ["mysql", "mariadb"]:
            drivername = "mysql+pymysql"
        elif self.db_type == "postgresql":
            drivername = "postgresql+psycopg2"
        else:
            raise ValueError(f"Unsupported DB_ENGINE: {self.db_type}")

        return URL.create(
            drivername=drivername,
            username=self.user,
            password=self.password,
            host=self.host,
            port=int(self.port),
            database=self.database,
        )
    
    def get_engine(self) -> Engine:
        """
        Get the SQLAlchemy engine.
        
        Returns:
            SQLAlchemy Engine instance
        """
        return self.engine
    
    def connect(self):
        """
        Create a new connection from the engine.
        
        Returns:
            SQLAlchemy Connection object
        """
        return self.engine.connect()
    
    def dispose(self) -> None:
        """Dispose of the connection pool."""
        self.engine.dispose()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.dispose()


def get_db_engine(
    db_type: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    database: Optional[str] = None,
    **engine_kwargs
) -> Engine:
    """
    Factory function to create database engine.
    
    Args:
        db_type: Database type. Defaults to env var
        host: Database host. Defaults to env var
        port: Database port. Defaults to env var
        user: Database user. Defaults to env var
        password: Database password. Defaults to env var
        database: Database name. Defaults to env var
        **engine_kwargs: Additional arguments for create_engine()
        
    Returns:
        SQLAlchemy Engine instance
    """
    connection = RDBMSConnection(
        db_type=db_type,
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        **engine_kwargs
    )
    return connection.get_engine()


def get_db_connection(
    db_type: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    database: Optional[str] = None
) -> RDBMSConnection:
    """
    Factory function to create database connection wrapper.
    
    Args:
        db_type: Database type. Defaults to env var
        host: Database host. Defaults to env var
        port: Database port. Defaults to env var
        user: Database user. Defaults to env var
        password: Database password. Defaults to env var
        database: Database name. Defaults to env var
        
    Returns:
        RDBMSConnection instance
    """
    return RDBMSConnection(
        db_type=db_type,
        host=host,
        port=port,
        user=user,
        password=password,
        database=database
    )


# Example usage
if __name__ == "__main__":
    from sqlalchemy import text
    
    print("=" * 60)
    print("RDBMS Connection Test")
    print("=" * 60)
    
    # Test with context manager
    with get_db_connection() as db:
        print(f"\nDatabase Type: {db.db_type}")
        print(f"Host: {db.host}:{db.port}")
        print(f"Database: {db.database}")
        
        # Test query
        print("\nTesting connection with simple query...")
        try:
            with db.connect() as conn:
                result = conn.execute(text("SELECT 1 as test"))
                row = result.fetchone()
                print(f"Query result: {row}")
                print("✓ Connection successful!")
        except Exception as e:
            print(f"✗ Connection failed: {e}")
    
    print("\n" + "=" * 60)
