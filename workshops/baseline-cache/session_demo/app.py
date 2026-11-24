import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash
from session_demo.glide_session import GlideSessionInterface
import mysql.connector
from dotenv import load_dotenv

# Add parent directory to path to import project modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import get_cache_client
from services.weather_service import WeatherService

# Load environment variables from root .env file
root_dir = Path(__file__).parent.parent
env_path = Path(os.environ.get('WORKSHOP_ENV_FILE', root_dir / '.env'))
load_dotenv(dotenv_path=env_path)

# Get URL prefix from environment
URL_PREFIX = os.getenv('URL_PREFIX', '')

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]
app.config["JSON_AS_ASCII"] = False

# Make URL prefix available in all templates
@app.context_processor
def inject_url_prefix():
    return {'url_prefix': URL_PREFIX}

# Configure Valkey/Redis session storage through the shared secure client.
session_cache = get_cache_client(decode_responses=False)
app.config["SESSION_TYPE"] = "redis"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_USE_SIGNER"] = True
app.config["SESSION_KEY_PREFIX"] = "flight_session:"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

app.session_interface = GlideSessionInterface(session_cache)

# Database connection
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('DB_PORT', 3306)),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'flughafendb_large')
    )


@app.route('/')
def index():
    if 'passenger_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', 
                         passenger=session.get('passenger'),
                         weather=session.get('weather'),
                         flights=session.get('flights', []))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        passport = request.form.get('passport')
        
        if not passport:
            flash('Please enter your passport number', 'error')
            return render_template('login.html')
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # The workshop looks up a passenger record; this is not production authentication.
        cursor.execute("""
            SELECT p.passenger_id, p.passportno, p.firstname, p.lastname,
                   pd.city, pd.country, pd.zip
            FROM passenger p
            LEFT JOIN passengerdetails pd ON p.passenger_id = pd.passenger_id
            WHERE p.passportno = %s
        """, (passport,))
        
        passenger = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if passenger:
            app.session_interface.regenerate(session)
            session['passenger_id'] = passenger['passenger_id']
            session['passenger'] = {
                'passportno': passenger['passportno'],
                'firstname': passenger['firstname'],
                'lastname': passenger['lastname'],
                'city': passenger['city'],
                'country': passenger['country'],
                'zip': passenger['zip']
            }
            flash(f'Welcome, {passenger["firstname"]} {passenger["lastname"]}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid passport number', 'error')
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    app.session_interface.regenerate(session)
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))


@app.route('/weather', methods=['GET', 'POST'])
def weather():
    if 'passenger_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        country = request.form.get('country')
        zip_code = request.form.get('zip_code')
        
        if country and zip_code:
            weather_data = WeatherService.get_weather(country, zip_code)
            
            if weather_data.get('cod') == 200:
                session['weather'] = {
                    'city': weather_data['name'],
                    'country': weather_data['sys']['country'],
                    'zip': zip_code,
                    'temp': weather_data['main']['temp'],
                    'description': weather_data['weather'][0]['description'],
                    'humidity': weather_data['main']['humidity'],
                    'wind_speed': weather_data['wind']['speed']
                }
                flash('Weather information updated!', 'success')
            else:
                flash('City not found for the provided zip code', 'error')
        
        return redirect(url_for('index'))
    
    # Get available cities for the form
    cities = WeatherService.get_all_cities()
    return render_template('weather.html', cities=cities)


@app.route('/flights', methods=['GET', 'POST'])
def flights():
    if 'passenger_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        flight_id = request.form.get('flight_id')
        
        if flight_id:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
                SELECT f.flight_id, f.flightno, 
                       af.name as from_airport, af.iata as from_iata,
                       at.name as to_airport, at.iata as to_iata,
                       f.departure, f.arrival,
                       al.airlinename
                FROM flight f
                JOIN airport af ON f.from = af.airport_id
                JOIN airport at ON f.to = at.airport_id
                JOIN airline al ON f.airline_id = al.airline_id
                WHERE f.flight_id = %s
            """, (flight_id,))
            
            flight = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if flight:
                # Initialize flights list in session if not exists
                if 'flights' not in session:
                    session['flights'] = []
                
                # Convert datetime to string for session storage
                flight_data = {
                    'flight_id': flight['flight_id'],
                    'flightno': flight['flightno'],
                    'from_airport': flight['from_airport'],
                    'from_iata': flight['from_iata'],
                    'to_airport': flight['to_airport'],
                    'to_iata': flight['to_iata'],
                    'departure': flight['departure'].strftime('%Y-%m-%d %H:%M'),
                    'arrival': flight['arrival'].strftime('%Y-%m-%d %H:%M'),
                    'airline': flight['airlinename']
                }
                
                # Check if flight already in session
                if not any(f['flight_id'] == flight_data['flight_id'] for f in session['flights']):
                    session['flights'].append(flight_data)
                    session.modified = True
                    flash('Flight added to your session!', 'success')
                else:
                    flash('Flight already in your session', 'info')
            else:
                flash('Flight not found', 'error')
        
        return redirect(url_for('index'))
    
    # Get today's flights
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    
    cursor.execute("""
        SELECT f.flight_id, f.flightno, 
               af.name as from_airport, af.iata as from_iata,
               at.name as to_airport, at.iata as to_iata,
               f.departure, f.arrival,
               al.airlinename
        FROM flight f
        JOIN airport af ON f.from = af.airport_id
        JOIN airport at ON f.to = at.airport_id
        JOIN airline al ON f.airline_id = al.airline_id
        WHERE DATE(f.departure) = %s
        ORDER BY f.departure
        LIMIT 50
    """, (today,))
    
    available_flights = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('flights.html', flights=available_flights)


@app.route('/remove_flight/<int:flight_id>')
def remove_flight(flight_id):
    if 'passenger_id' not in session:
        return redirect(url_for('login'))
    
    if 'flights' in session:
        session['flights'] = [f for f in session['flights'] if f['flight_id'] != flight_id]
        session.modified = True
        flash('Flight removed from your session', 'info')
    
    return redirect(url_for('index'))


def main():
    """Run the session demo development server."""
    debug = os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes", "on"}
    port = int(os.getenv("PORT", "5001"))
    app.run(host='127.0.0.1', debug=debug, port=port)


if __name__ == '__main__':
    main()
