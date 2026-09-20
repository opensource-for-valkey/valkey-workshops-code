import streamlit as st
import time
import json
import pandas as pd
import plotly.express as px
import os
from dotenv import load_dotenv
from sqlalchemy import text
from core import get_cache_client, get_db_engine, quote_identifier

# Load environment variables
load_dotenv()

# --- CONNECTIVITY ---
@st.cache_resource
def get_db_connection():
    """Get database engine (supports MySQL, MariaDB, PostgreSQL)"""
    return get_db_engine()

def get_cache_connection():
    """Get Valkey/Redis cache connection"""
    return get_cache_client()

# --- DATA LOGIC: FLIGHT DETAILS ---
def fetch_flight_db(flight_id):
    """Fetch flight details from database"""
    start = time.time()
    
    engine = get_db_connection()
    from_column = quote_identifier(engine, "from")
    to_column = quote_identifier(engine, "to")
    
    query = text(f"""
        SELECT 
            f.flight_id,
            a.airlinename as airline,
            af.iata as from_airport,
            at.iata as to_airport,
            f.departure,
            f.arrival,
            'On Time' as status
        FROM flight f
        JOIN airline a ON f.airline_id = a.airline_id
        JOIN airport af ON f.{from_column} = af.airport_id
        JOIN airport at ON f.{to_column} = at.airport_id
        WHERE f.flight_id = :flight_id
    """)
    
    with engine.connect() as conn:
        result = conn.execute(query, {"flight_id": flight_id})
        row = result.fetchone()
        if row:
            data = dict(row._mapping)
            # Rename for backward compatibility
            data['from'] = data.pop('from_airport')
            data['to'] = data.pop('to_airport')
        else:
            data = None
    
    return data, (time.time() - start) * 1000

# --- DATA LOGIC: MANIFEST (HEAVY QUERY) ---
def fetch_manifest_db(flight_id):
    """Fetch flight manifest with passenger details (heavy JOIN operation)"""
    start = time.time()
    
    engine = get_db_connection()
    
    # Heavy 3-table JOIN: Booking -> Passenger -> PassengerDetails
    query = text("""
        SELECT 
            b.seat,
            p.firstname,
            p.lastname,
            p.passportno,
            pd.country,
            b.price
        FROM booking b
        JOIN passenger p ON b.passenger_id = p.passenger_id
        LEFT JOIN passengerdetails pd ON p.passenger_id = pd.passenger_id
        WHERE b.flight_id = :flight_id
        ORDER BY b.seat ASC
    """)
    
    with engine.connect() as conn:
        result = conn.execute(query, {"flight_id": flight_id})
        data = [dict(row._mapping) for row in result]
    
    return data, (time.time() - start) * 1000

# --- DATA LOGIC: PASSENGER FLIGHTS (COMPLEX QUERY) ---
def fetch_passenger_flights_db(passport_no):
    """Fetch all flights for a passenger (complex multi-table JOIN)"""
    start = time.time()
    
    engine = get_db_connection()
    from_column = quote_identifier(engine, "from")
    to_column = quote_identifier(engine, "to")
    
    # Complex 8-table JOIN query
    query = text(f"""
        SELECT 
            b.booking_id,
            b.seat,
            b.price,
            f.flightno,
            f.departure,
            f.arrival,
            dep_airport.name AS departure_airport,
            dep_airport.iata AS departure_iata,
            arr_airport.name AS arrival_airport,
            arr_airport.iata AS arrival_iata,
            al.airlinename,
            al.iata AS airline_iata,
            at.identifier AS aircraft_type,
            ap.capacity AS aircraft_capacity,
            p.firstname,
            p.lastname,
            p.passportno
        FROM booking b
        JOIN flight f ON b.flight_id = f.flight_id
        JOIN airport dep_airport ON f.{from_column} = dep_airport.airport_id
        JOIN airport arr_airport ON f.{to_column} = arr_airport.airport_id
        JOIN airline al ON f.airline_id = al.airline_id
        JOIN airplane ap ON f.airplane_id = ap.airplane_id
        JOIN airplane_type at ON ap.type_id = at.type_id
        JOIN passenger p ON b.passenger_id = p.passenger_id
        WHERE p.passportno = :passport_no
        ORDER BY f.departure DESC
        LIMIT 10
    """)
    
    with engine.connect() as conn:
        result = conn.execute(query, {"passport_no": passport_no})
        data = [dict(row._mapping) for row in result]
    
    return data, (time.time() - start) * 1000

# --- DATA LOGIC: GET RANDOM PASSENGERS ---
@st.cache_data(ttl=3600)
def get_random_passengers():
    """Get 10 random passengers (simplified approach)"""
    import random
    
    engine = get_db_connection()
    
    # Get min and max passenger IDs
    with engine.connect() as conn:
        result = conn.execute(text("SELECT MIN(passenger_id) as min_id, MAX(passenger_id) as max_id FROM passenger"))
        row = result.fetchone()
        min_id = row.min_id
        max_id = row.max_id
    
    # Generate 10 random passenger IDs in the range
    random_ids = random.sample(range(min_id, max_id + 1), min(10, max_id - min_id + 1))
    
    # Get passenger details for those IDs
    query = text("""
        SELECT 
            p.passenger_id,
            p.passportno,
            p.firstname,
            p.lastname,
            COUNT(b.booking_id) as booking_count
        FROM passenger p
        LEFT JOIN booking b ON p.passenger_id = b.passenger_id
        WHERE p.passenger_id IN :passenger_ids
          AND p.passportno IS NOT NULL
        GROUP BY p.passenger_id, p.passportno, p.firstname, p.lastname
        HAVING COUNT(b.booking_id) > 0
        LIMIT 10
    """)
    
    with engine.connect() as conn:
        result = conn.execute(query, {"passenger_ids": tuple(random_ids)})
        data = [dict(row._mapping) for row in result]
    
    return data

# --- CACHE ASIDE WRAPPERS ---
def get_data_cache_aside(key_prefix, id, fetch_func, cache):
    key = f"{key_prefix}:{id}"
    
    # 1. Try Cache
    start = time.time()
    cached = cache.get(key)
    if cached:
        return json.loads(cached), (time.time() - start) * 1000, "HIT"
    
    # 2. DB Fallback
    data, db_time = fetch_func(id)
    
    # 3. Populate Cache (if data exists)
    if data:
        cache.set(key, json.dumps(data, default=str), ttl=3600)
        
    return data, db_time, "MISS"

# --- STREAMLIT UI ---
st.set_page_config(
    page_title="Valkey Cache Demo",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Add Valkey logo and title
col_logo, col_title = st.columns([1, 4])
with col_logo:
    st.image("https://valkey.io/img/valkey-horizontal.svg", width=200)
with col_title:
    st.title("FlughafenDB: Database Queries vs. Valkey Cache")
    st.caption("Demonstrating cache-aside pattern with complex SQL queries")

# Initialize session state
if 'history' not in st.session_state:
    st.session_state.history = []

# Initialize cache connection
if 'cache' not in st.session_state:
    st.session_state.cache = get_cache_connection()

# Main layout
col_input, col_stats = st.columns([1, 2])

with col_input:
    st.subheader("Query Controls")
    
    # Flight ID input
    flight_id = st.number_input("Flight ID", value=115, step=1, min_value=1)
    
    st.markdown("---")
    
    # Passenger selection
    st.subheader("Passenger Selection")
    passengers = get_random_passengers()
    
    if passengers:
        # Create display options with name and passport
        passenger_options = {
            f"{p['firstname']} {p['lastname']} ({p['passportno']}) - {p['booking_count']} bookings": p['passportno']
            for p in passengers
        }
        
        selected_display = st.selectbox(
            "Select Passenger",
            options=list(passenger_options.keys()),
            help="Choose a passenger to view their flight history"
        )
        
        selected_passport = passenger_options[selected_display]
    else:
        st.warning("No passengers found in database")
        selected_passport = None
    
    st.markdown("---")
    
    # ACTION BUTTONS
    if st.button("🔍 Get Flight Details (Simple Query)", width='stretch'):
        try:
            res, lat, stat = get_data_cache_aside(
                "flight", 
                flight_id, 
                fetch_flight_db, 
                st.session_state.cache
            )
            
            source = "Valkey Cache" if stat == "HIT" else "Database"
            st.session_state.history.append({
                "Type": "Flight Details",
                "Latency": lat,
                "Source": source
            })
            
            if res:
                st.success(f"✅ Flight {res['from']} → {res['to']}")
                st.json({
                    "Flight ID": res['flight_id'],
                    "Airline": res['airline'],
                    "Route": f"{res['from']} → {res['to']}",
                    "Departure": str(res.get('departure', 'N/A')),
                    "Arrival": str(res.get('arrival', 'N/A')),
                    "Status": res['status']
                })
            else:
                st.error("❌ Flight not found")
        except Exception as e:
            st.error(f"Error: {e}")

    if st.button("📋 Get Manifest (3-Table JOIN)", width='stretch'):
        try:
            res, lat, stat = get_data_cache_aside(
                "manifest", 
                flight_id, 
                fetch_manifest_db, 
                st.session_state.cache
            )
            
            source = "Valkey Cache" if stat == "HIT" else "Database (3 JOINs)"
            st.session_state.history.append({
                "Type": "Flight Manifest",
                "Latency": lat,
                "Source": source
            })
            
            if res:
                st.success(f"✅ Manifest loaded: {len(res)} passengers")
                
                # Format passenger data for display
                df = pd.DataFrame(res)
                if 'firstname' in df.columns and 'lastname' in df.columns:
                    df['name'] = df['firstname'] + ' ' + df['lastname']
                    df = df.drop(['firstname', 'lastname'], axis=1)
                
                st.dataframe(df, width='stretch', hide_index=True)
            else:
                st.warning("⚠️ No passengers found for this flight")
        except Exception as e:
            st.error(f"Error: {e}")

    if st.button("✈️ Get Passenger Flights (8-Table JOIN)", width='stretch'):
        if not selected_passport:
            st.error("❌ No passenger selected")
        else:
            try:
                res, lat, stat = get_data_cache_aside(
                    "passenger_flights",
                    selected_passport,
                    fetch_passenger_flights_db,
                    st.session_state.cache
                )
                
                source = "Valkey Cache" if stat == "HIT" else "Database (8 JOINs)"
                st.session_state.history.append({
                    "Type": "Passenger Flights",
                    "Latency": lat,
                    "Source": source
                })
                
                if res:
                    passenger_name = f"{res[0]['firstname']} {res[0]['lastname']}"
                    st.success(f"✅ Found {len(res)} flights for {passenger_name}")
                    
                    # Format flight data for display
                    df = pd.DataFrame(res)
                    
                    # Ensure proper data types (important for cache hits where data is JSON)
                    df['booking_id'] = df['booking_id'].astype(str)
                    df['flightno'] = df['flightno'].astype(str)
                    df['departure_iata'] = df['departure_iata'].astype(str)
                    df['arrival_iata'] = df['arrival_iata'].astype(str)
                    df['departure'] = df['departure'].astype(str)
                    df['arrival'] = df['arrival'].astype(str)
                    df['airlinename'] = df['airlinename'].astype(str)
                    df['airline_iata'] = df['airline_iata'].astype(str)
                    df['aircraft_type'] = df['aircraft_type'].astype(str)
                    df['aircraft_capacity'] = pd.to_numeric(df['aircraft_capacity'], errors='coerce')
                    df['seat'] = df['seat'].astype(str)
                    df['price'] = pd.to_numeric(df['price'], errors='coerce')
                    
                    # Create readable columns
                    display_df = pd.DataFrame({
                        'Booking ID': df['booking_id'],
                        'Flight': df['flightno'],
                        'Route': df['departure_iata'] + ' → ' + df['arrival_iata'],
                        'Departure': df['departure'],
                        'Arrival': df['arrival'],
                        'Airline': df['airlinename'] + ' (' + df['airline_iata'] + ')',
                        'Aircraft': df['aircraft_type'] + ' (' + df['aircraft_capacity'].astype(str) + ' seats)',
                        'Seat': df['seat'],
                        'Price': '$' + df['price'].round(2).astype(str)
                    })
                    
                    st.dataframe(display_df, width='stretch', hide_index=True)
                    
                    # Show detailed info in expander
                    with st.expander("📊 View Detailed Flight Information"):
                        st.json({
                            "Passenger": passenger_name,
                            "Passport": selected_passport,
                            "Total Flights": len(res),
                            "Total Spent": f"${sum(df['price']):.2f}",
                            "Airlines Used": df['airlinename'].nunique(),
                            "Airports Visited": len(set(df['departure_iata'].tolist() + df['arrival_iata'].tolist()))
                        })
                else:
                    st.warning(f"⚠️ No flights found for passport {selected_passport}")
            except Exception as e:
                st.error(f"Error: {e}")

    st.markdown("---")
    
    if st.button("🗑️ Flush Cache", width='stretch'):
        try:
            st.session_state.cache.flush_all()
            st.session_state.history = []
            st.warning("🧹 Cache flushed successfully")
        except Exception as e:
            st.error(f"Error flushing cache: {e}")

# Visualization and Statistics
with col_stats:
    st.subheader("Performance Metrics")
    
    if st.session_state.history:
        df = pd.DataFrame(st.session_state.history)
        
        # Latest query metrics
        last = st.session_state.history[-1]
        c1, c2, c3 = st.columns(3)
        c1.metric("Last Query", last['Type'])
        c2.metric("Latency", f"{last['Latency']:.3f} ms")
        c3.metric("Source", last['Source'])
        
        st.markdown("---")
        
        # Latency comparison chart
        fig = px.bar(
            df, 
            x=df.index, 
            y="Latency", 
            color="Source",
            title="Query Latency Comparison (Lower is Better)",
            labels={"index": "Query Number", "Latency": "Latency (ms)"},
            color_discrete_map={
                "Database": "#FF4B4B",
                "Database (3 JOINs)": "#CC3333",
                "Database (8 JOINs)": "#8B0000",
                "Valkey Cache": "#00C805"
            },
            text_auto='.0f'
        )
        fig.update_layout(
            xaxis_title="Query Number",
            yaxis_title="Latency (ms)",
            showlegend=True,
            height=400
        )
        st.plotly_chart(fig, width='stretch')
        
        # Summary statistics
        st.markdown("### Summary Statistics")
        
        cache_hits = df[df['Source'].str.contains('Cache', case=False)]
        db_queries = df[~df['Source'].str.contains('Cache', case=False)]
        
        col_a, col_b = st.columns(2)
        
        with col_a:
            st.metric(
                "Total Queries",
                len(df),
                help="Total number of queries executed"
            )
            if len(cache_hits) > 0:
                st.metric(
                    "Cache Hits",
                    len(cache_hits),
                    f"{len(cache_hits)/len(df)*100:.2f}%"
                )
                st.metric(
                    "Avg Cache Latency",
                    f"{cache_hits['Latency'].mean():.3f} ms"
                )
        
        with col_b:
            if len(db_queries) > 0:
                st.metric(
                    "Database Queries",
                    len(db_queries),
                    f"{len(db_queries)/len(df)*100:.2f}%"
                )
                st.metric(
                    "Avg DB Latency",
                    f"{db_queries['Latency'].mean():.3f} ms"
                )
                
                if len(cache_hits) > 0:
                    speedup = db_queries['Latency'].mean() / cache_hits['Latency'].mean()
                    st.metric(
                        "Cache Speedup",
                        f"{speedup:.2f}x faster",
                        help="How much faster cache is compared to database"
                    )
    else:
        st.info("👆 Execute queries above to see performance metrics")
        
        st.markdown("""
        ### How it works:
        
        1. **Flush Cache** - Clears all cached data
        2. **First Query** - Data fetched from database (slower)
        3. **Cached** - Data stored in Valkey with TTL
        4. **Subsequent Queries** - Data served from cache (faster)
        
        ### Query Complexity:
        - **Flight Details**: 3 JOINs (simple)
        - **Flight Manifest**: 3 JOINs (medium)
        - **Passenger Flights**: 8 JOINs (complex)
        
        ### Try it:
        - Click "Get Flight Details" twice to see cache speedup
        - Click "Get Manifest" to see 3-table JOIN performance
        - Click "Get Passenger Flights" to see 8-table JOIN performance
        - Compare database vs cache latency in the chart
        - Notice how complex queries benefit most from caching!
        """)
