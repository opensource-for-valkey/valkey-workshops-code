import time
import random
from typing import Dict, Any


class WeatherService:
    """Mock weather service that simulates OpenWeatherMap API responses."""
    
    # Mock data for 5 cities from each G20 country
    CITIES = {
        # United States
        "US_10001": {"coord": {"lon": -74.0060, "lat": 40.7128}, "name": "New York", "country": "US", "zip": "10001", "timezone": -18000},
        "US_90001": {"coord": {"lon": -118.2437, "lat": 34.0522}, "name": "Los Angeles", "country": "US", "zip": "90001", "timezone": -28800},
        "US_60601": {"coord": {"lon": -87.6298, "lat": 41.8781}, "name": "Chicago", "country": "US", "zip": "60601", "timezone": -21600},
        "US_77001": {"coord": {"lon": -95.3698, "lat": 29.7604}, "name": "Houston", "country": "US", "zip": "77001", "timezone": -21600},
        "US_33101": {"coord": {"lon": -80.1918, "lat": 25.7617}, "name": "Miami", "country": "US", "zip": "33101", "timezone": -18000},
        
        # United Kingdom
        "GB_SW1A": {"coord": {"lon": -0.1276, "lat": 51.5074}, "name": "London", "country": "GB", "zip": "SW1A", "timezone": 0},
        "GB_M1": {"coord": {"lon": -2.2426, "lat": 53.4808}, "name": "Manchester", "country": "GB", "zip": "M1", "timezone": 0},
        "GB_B1": {"coord": {"lon": -1.8904, "lat": 52.4862}, "name": "Birmingham", "country": "GB", "zip": "B1", "timezone": 0},
        "GB_EH1": {"coord": {"lon": -3.1883, "lat": 55.9533}, "name": "Edinburgh", "country": "GB", "zip": "EH1", "timezone": 0},
        "GB_G1": {"coord": {"lon": -4.2518, "lat": 55.8642}, "name": "Glasgow", "country": "GB", "zip": "G1", "timezone": 0},
        
        # Japan
        "JP_1000001": {"coord": {"lon": 139.6917, "lat": 35.6895}, "name": "Tokyo", "country": "JP", "zip": "1000001", "timezone": 32400},
        "JP_5300001": {"coord": {"lon": 135.5023, "lat": 34.6937}, "name": "Osaka", "country": "JP", "zip": "5300001", "timezone": 32400},
        "JP_2310001": {"coord": {"lon": 139.6380, "lat": 35.4437}, "name": "Yokohama", "country": "JP", "zip": "2310001", "timezone": 32400},
        "JP_4600001": {"coord": {"lon": 136.9066, "lat": 35.1815}, "name": "Nagoya", "country": "JP", "zip": "4600001", "timezone": 32400},
        "JP_0600001": {"coord": {"lon": 141.3545, "lat": 43.0642}, "name": "Sapporo", "country": "JP", "zip": "0600001", "timezone": 32400},
        
        # Germany
        "DE_10115": {"coord": {"lon": 13.4050, "lat": 52.5200}, "name": "Berlin", "country": "DE", "zip": "10115", "timezone": 3600},
        "DE_80331": {"coord": {"lon": 11.5820, "lat": 48.1351}, "name": "Munich", "country": "DE", "zip": "80331", "timezone": 3600},
        "DE_60311": {"coord": {"lon": 8.6821, "lat": 50.1109}, "name": "Frankfurt", "country": "DE", "zip": "60311", "timezone": 3600},
        "DE_20095": {"coord": {"lon": 9.9937, "lat": 53.5511}, "name": "Hamburg", "country": "DE", "zip": "20095", "timezone": 3600},
        "DE_50667": {"coord": {"lon": 6.9603, "lat": 50.9375}, "name": "Cologne", "country": "DE", "zip": "50667", "timezone": 3600},
        
        # France
        "FR_75001": {"coord": {"lon": 2.3522, "lat": 48.8566}, "name": "Paris", "country": "FR", "zip": "75001", "timezone": 3600},
        "FR_13001": {"coord": {"lon": 5.3698, "lat": 43.2965}, "name": "Marseille", "country": "FR", "zip": "13001", "timezone": 3600},
        "FR_69001": {"coord": {"lon": 4.8357, "lat": 45.7640}, "name": "Lyon", "country": "FR", "zip": "69001", "timezone": 3600},
        "FR_31000": {"coord": {"lon": 1.4442, "lat": 43.6047}, "name": "Toulouse", "country": "FR", "zip": "31000", "timezone": 3600},
        "FR_06000": {"coord": {"lon": 7.2619, "lat": 43.7102}, "name": "Nice", "country": "FR", "zip": "06000", "timezone": 3600},
        
        # China
        "CN_100000": {"coord": {"lon": 116.4074, "lat": 39.9042}, "name": "Beijing", "country": "CN", "zip": "100000", "timezone": 28800},
        "CN_200000": {"coord": {"lon": 121.4737, "lat": 31.2304}, "name": "Shanghai", "country": "CN", "zip": "200000", "timezone": 28800},
        "CN_510000": {"coord": {"lon": 113.2644, "lat": 23.1291}, "name": "Guangzhou", "country": "CN", "zip": "510000", "timezone": 28800},
        "CN_518000": {"coord": {"lon": 114.0579, "lat": 22.5431}, "name": "Shenzhen", "country": "CN", "zip": "518000", "timezone": 28800},
        "CN_610000": {"coord": {"lon": 104.0668, "lat": 30.5728}, "name": "Chengdu", "country": "CN", "zip": "610000", "timezone": 28800},
        
        # India
        "IN_110001": {"coord": {"lon": 77.2090, "lat": 28.6139}, "name": "New Delhi", "country": "IN", "zip": "110001", "timezone": 19800},
        "IN_400001": {"coord": {"lon": 72.8777, "lat": 19.0760}, "name": "Mumbai", "country": "IN", "zip": "400001", "timezone": 19800},
        "IN_560001": {"coord": {"lon": 77.5946, "lat": 12.9716}, "name": "Bangalore", "country": "IN", "zip": "560001", "timezone": 19800},
        "IN_700001": {"coord": {"lon": 88.3639, "lat": 22.5726}, "name": "Kolkata", "country": "IN", "zip": "700001", "timezone": 19800},
        "IN_600001": {"coord": {"lon": 80.2707, "lat": 13.0827}, "name": "Chennai", "country": "IN", "zip": "600001", "timezone": 19800},
        
        # Brazil
        "BR_01310": {"coord": {"lon": -46.6333, "lat": -23.5505}, "name": "São Paulo", "country": "BR", "zip": "01310", "timezone": -10800},
        "BR_20000": {"coord": {"lon": -43.1729, "lat": -22.9068}, "name": "Rio de Janeiro", "country": "BR", "zip": "20000", "timezone": -10800},
        "BR_70000": {"coord": {"lon": -47.8825, "lat": -15.7942}, "name": "Brasília", "country": "BR", "zip": "70000", "timezone": -10800},
        "BR_40000": {"coord": {"lon": -38.5108, "lat": -12.9714}, "name": "Salvador", "country": "BR", "zip": "40000", "timezone": -10800},
        "BR_30000": {"coord": {"lon": -43.9378, "lat": -19.9167}, "name": "Belo Horizonte", "country": "BR", "zip": "30000", "timezone": -10800},
        
        # Australia
        "AU_2000": {"coord": {"lon": 151.2093, "lat": -33.8688}, "name": "Sydney", "country": "AU", "zip": "2000", "timezone": 36000},
        "AU_3000": {"coord": {"lon": 144.9631, "lat": -37.8136}, "name": "Melbourne", "country": "AU", "zip": "3000", "timezone": 36000},
        "AU_4000": {"coord": {"lon": 153.0251, "lat": -27.4698}, "name": "Brisbane", "country": "AU", "zip": "4000", "timezone": 36000},
        "AU_6000": {"coord": {"lon": 115.8605, "lat": -31.9505}, "name": "Perth", "country": "AU", "zip": "6000", "timezone": 28800},
        "AU_5000": {"coord": {"lon": 138.6007, "lat": -34.9285}, "name": "Adelaide", "country": "AU", "zip": "5000", "timezone": 34200},
        
        # South Africa
        "ZA_0001": {"coord": {"lon": 28.0473, "lat": -26.2041}, "name": "Johannesburg", "country": "ZA", "zip": "0001", "timezone": 7200},
        "ZA_8001": {"coord": {"lon": 18.4241, "lat": -33.9249}, "name": "Cape Town", "country": "ZA", "zip": "8001", "timezone": 7200},
        "ZA_4001": {"coord": {"lon": 31.0218, "lat": -29.8587}, "name": "Durban", "country": "ZA", "zip": "4001", "timezone": 7200},
        "ZA_0002": {"coord": {"lon": 28.1878, "lat": -25.7479}, "name": "Pretoria", "country": "ZA", "zip": "0002", "timezone": 7200},
        "ZA_6001": {"coord": {"lon": 25.6022, "lat": -33.9608}, "name": "Port Elizabeth", "country": "ZA", "zip": "6001", "timezone": 7200},
        
        # Canada
        "CA_M5H": {"coord": {"lon": -79.3832, "lat": 43.6532}, "name": "Toronto", "country": "CA", "zip": "M5H", "timezone": -18000},
        "CA_H2Y": {"coord": {"lon": -73.5673, "lat": 45.5017}, "name": "Montreal", "country": "CA", "zip": "H2Y", "timezone": -18000},
        "CA_V6B": {"coord": {"lon": -123.1207, "lat": 49.2827}, "name": "Vancouver", "country": "CA", "zip": "V6B", "timezone": -28800},
        "CA_T2P": {"coord": {"lon": -114.0719, "lat": 51.0447}, "name": "Calgary", "country": "CA", "zip": "T2P", "timezone": -25200},
        "CA_K1A": {"coord": {"lon": -75.6972, "lat": 45.4215}, "name": "Ottawa", "country": "CA", "zip": "K1A", "timezone": -18000},
        
        # Italy
        "IT_00100": {"coord": {"lon": 12.4964, "lat": 41.9028}, "name": "Rome", "country": "IT", "zip": "00100", "timezone": 3600},
        "IT_20100": {"coord": {"lon": 9.1900, "lat": 45.4642}, "name": "Milan", "country": "IT", "zip": "20100", "timezone": 3600},
        "IT_80100": {"coord": {"lon": 14.2681, "lat": 40.8518}, "name": "Naples", "country": "IT", "zip": "80100", "timezone": 3600},
        "IT_10100": {"coord": {"lon": 7.6869, "lat": 45.0703}, "name": "Turin", "country": "IT", "zip": "10100", "timezone": 3600},
        "IT_50100": {"coord": {"lon": 11.2558, "lat": 43.7696}, "name": "Florence", "country": "IT", "zip": "50100", "timezone": 3600},
        
        # South Korea
        "KR_03000": {"coord": {"lon": 126.9780, "lat": 37.5665}, "name": "Seoul", "country": "KR", "zip": "03000", "timezone": 32400},
        "KR_48000": {"coord": {"lon": 129.0756, "lat": 35.1796}, "name": "Busan", "country": "KR", "zip": "48000", "timezone": 32400},
        "KR_21000": {"coord": {"lon": 126.7052, "lat": 37.4563}, "name": "Incheon", "country": "KR", "zip": "21000", "timezone": 32400},
        "KR_41000": {"coord": {"lon": 128.6014, "lat": 35.8714}, "name": "Daegu", "country": "KR", "zip": "41000", "timezone": 32400},
        "KR_34000": {"coord": {"lon": 126.9910, "lat": 35.1595}, "name": "Gwangju", "country": "KR", "zip": "34000", "timezone": 32400},
        
        # Mexico
        "MX_06000": {"coord": {"lon": -99.1332, "lat": 19.4326}, "name": "Mexico City", "country": "MX", "zip": "06000", "timezone": -21600},
        "MX_44100": {"coord": {"lon": -103.3496, "lat": 20.6597}, "name": "Guadalajara", "country": "MX", "zip": "44100", "timezone": -21600},
        "MX_64000": {"coord": {"lon": -100.3161, "lat": 25.6866}, "name": "Monterrey", "country": "MX", "zip": "64000", "timezone": -21600},
        "MX_72000": {"coord": {"lon": -98.2063, "lat": 19.0414}, "name": "Puebla", "country": "MX", "zip": "72000", "timezone": -21600},
        "MX_22000": {"coord": {"lon": -116.9719, "lat": 32.5149}, "name": "Tijuana", "country": "MX", "zip": "22000", "timezone": -28800},
        
        # Indonesia
        "ID_10110": {"coord": {"lon": 106.8456, "lat": -6.2088}, "name": "Jakarta", "country": "ID", "zip": "10110", "timezone": 25200},
        "ID_60111": {"coord": {"lon": 112.7521, "lat": -7.2575}, "name": "Surabaya", "country": "ID", "zip": "60111", "timezone": 25200},
        "ID_40111": {"coord": {"lon": 107.6191, "lat": -6.9175}, "name": "Bandung", "country": "ID", "zip": "40111", "timezone": 25200},
        "ID_50241": {"coord": {"lon": 110.4203, "lat": -6.9932}, "name": "Semarang", "country": "ID", "zip": "50241", "timezone": 25200},
        "ID_20111": {"coord": {"lon": 98.6722, "lat": 3.5952}, "name": "Medan", "country": "ID", "zip": "20111", "timezone": 25200},
        
        # Turkey
        "TR_34000": {"coord": {"lon": 28.9784, "lat": 41.0082}, "name": "Istanbul", "country": "TR", "zip": "34000", "timezone": 10800},
        "TR_06000": {"coord": {"lon": 32.8597, "lat": 39.9334}, "name": "Ankara", "country": "TR", "zip": "06000", "timezone": 10800},
        "TR_35000": {"coord": {"lon": 27.1428, "lat": 38.4237}, "name": "Izmir", "country": "TR", "zip": "35000", "timezone": 10800},
        "TR_16000": {"coord": {"lon": 29.0875, "lat": 40.1826}, "name": "Bursa", "country": "TR", "zip": "16000", "timezone": 10800},
        "TR_01000": {"coord": {"lon": 35.3213, "lat": 37.0000}, "name": "Adana", "country": "TR", "zip": "01000", "timezone": 10800},
        
        # Saudi Arabia
        "SA_11564": {"coord": {"lon": 46.6753, "lat": 24.7136}, "name": "Riyadh", "country": "SA", "zip": "11564", "timezone": 10800},
        "SA_21442": {"coord": {"lon": 39.8261, "lat": 21.4858}, "name": "Jeddah", "country": "SA", "zip": "21442", "timezone": 10800},
        "SA_31952": {"coord": {"lon": 39.8579, "lat": 21.3891}, "name": "Mecca", "country": "SA", "zip": "31952", "timezone": 10800},
        "SA_24231": {"coord": {"lon": 39.6111, "lat": 24.5247}, "name": "Medina", "country": "SA", "zip": "24231", "timezone": 10800},
        "SA_31311": {"coord": {"lon": 50.0888, "lat": 26.4207}, "name": "Dammam", "country": "SA", "zip": "31311", "timezone": 10800},
        
        # Argentina
        "AR_C1000": {"coord": {"lon": -58.3816, "lat": -34.6037}, "name": "Buenos Aires", "country": "AR", "zip": "C1000", "timezone": -10800},
        "AR_X5000": {"coord": {"lon": -64.1888, "lat": -31.4201}, "name": "Córdoba", "country": "AR", "zip": "X5000", "timezone": -10800},
        "AR_S2000": {"coord": {"lon": -60.6393, "lat": -32.9468}, "name": "Rosario", "country": "AR", "zip": "S2000", "timezone": -10800},
        "AR_A4400": {"coord": {"lon": -65.4165, "lat": -24.7859}, "name": "Salta", "country": "AR", "zip": "A4400", "timezone": -10800},
        "AR_U9000": {"coord": {"lon": -68.0591, "lat": -38.9516}, "name": "Neuquén", "country": "AR", "zip": "U9000", "timezone": -10800},
        
        # Russia
        "RU_101000": {"coord": {"lon": 37.6173, "lat": 55.7558}, "name": "Moscow", "country": "RU", "zip": "101000", "timezone": 10800},
        "RU_190000": {"coord": {"lon": 30.3609, "lat": 59.9311}, "name": "Saint Petersburg", "country": "RU", "zip": "190000", "timezone": 10800},
        "RU_630000": {"coord": {"lon": 82.9346, "lat": 55.0084}, "name": "Novosibirsk", "country": "RU", "zip": "630000", "timezone": 25200},
        "RU_620000": {"coord": {"lon": 60.5974, "lat": 56.8389}, "name": "Yekaterinburg", "country": "RU", "zip": "620000", "timezone": 18000},
        "RU_420000": {"coord": {"lon": 49.1221, "lat": 55.7887}, "name": "Kazan", "country": "RU", "zip": "420000", "timezone": 10800},
        
        # European Union (represented by major EU cities)
        "NL_1012": {"coord": {"lon": 4.9041, "lat": 52.3676}, "name": "Amsterdam", "country": "NL", "zip": "1012", "timezone": 3600},
        "ES_28001": {"coord": {"lon": -3.7038, "lat": 40.4168}, "name": "Madrid", "country": "ES", "zip": "28001", "timezone": 3600},
        "ES_08001": {"coord": {"lon": 2.1734, "lat": 41.3851}, "name": "Barcelona", "country": "ES", "zip": "08001", "timezone": 3600},
        "BE_1000": {"coord": {"lon": 4.3517, "lat": 50.8503}, "name": "Brussels", "country": "BE", "zip": "1000", "timezone": 3600},
        "AT_1010": {"coord": {"lon": 16.3738, "lat": 48.2082}, "name": "Vienna", "country": "AT", "zip": "1010", "timezone": 3600},
    }
    
    @staticmethod
    def _generate_weather_data(city_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate random weather data for a city."""
        current_time = int(time.time())
        
        # Random weather conditions
        weather_conditions = [
            {"id": 800, "main": "Clear", "description": "clear sky", "icon": "01d"},
            {"id": 801, "main": "Clouds", "description": "few clouds", "icon": "02d"},
            {"id": 500, "main": "Rain", "description": "light rain", "icon": "10d"},
            {"id": 600, "main": "Snow", "description": "light snow", "icon": "13d"},
        ]
        
        return {
            "coord": city_data["coord"],
            "weather": [random.choice(weather_conditions)],
            "base": "stations",
            "main": {
                "temp": round(random.uniform(50, 85), 1),
                "feels_like": round(random.uniform(48, 83), 1),
                "temp_min": round(random.uniform(45, 75), 1),
                "temp_max": round(random.uniform(55, 90), 1),
                "pressure": random.randint(1000, 1025),
                "humidity": random.randint(40, 90),
                "sea_level": random.randint(1010, 1020),
                "grnd_level": random.randint(1005, 1015)
            },
            "visibility": random.randint(8000, 10000),
            "wind": {
                "speed": round(random.uniform(3, 15), 1),
                "deg": random.randint(0, 360),
                "gust": round(random.uniform(5, 20), 1)
            },
            "clouds": {
                "all": random.randint(0, 100)
            },
            "dt": current_time,
            "sys": {
                "type": 2,
                "id": random.randint(2000000, 2999999),
                "country": city_data["country"],
                "sunrise": current_time - 21600,
                "sunset": current_time + 21600
            },
            "timezone": city_data["timezone"],
            "id": random.randint(4000000, 5000000),
            "name": city_data["name"],
            "cod": 200
        }
    
    @classmethod
    def get_weather(cls, country: str, zip_code: str) -> Dict[str, Any]:
        """
        Get weather data for a specific country and zip code.
        Simulates network latency between 250-750ms.
        
        Args:
            country: Two-letter country code (e.g., 'US', 'GB')
            zip_code: Zip/postal code
            
        Returns:
            Dictionary with OpenWeatherMap API format
        """
        # Simulate network latency
        delay = random.uniform(0.25, 0.75)
        time.sleep(delay)
        
        # Find matching city
        city_key = f"{country}_{zip_code}"
        city_data = cls.CITIES.get(city_key)
        
        if not city_data:
            return {
                "cod": "404",
                "message": "city not found"
            }
        
        return cls._generate_weather_data(city_data)
    
    @classmethod
    def get_all_cities(cls) -> list:
        """Get list of all available cities."""
        return [
            {"country": data["country"], "zip": data["zip"], "name": data["name"]}
            for data in cls.CITIES.values()
        ]
