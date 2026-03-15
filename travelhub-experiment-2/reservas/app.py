# 1st Party Libraries
import os
import time
import logging
import datetime

# 3rd Party Libraries
import pytz
import psycopg2
import requests
from flask import Flask, request, jsonify

# Instanciar la aplicación Flask
app = Flask(__name__)

# Configurar timezone para Bogotá
bogota_tz = pytz.timezone('America/Bogota')

# Configurar el logger
logging.basicConfig(format = '\n%(asctime)s [%(name)s] %(message)s', level = logging.INFO)
logger = logging.getLogger('reservas')

AUTORIZADOR_URL = os.environ.get("AUTORIZADOR_URL", "http://autorizador:5001")

# Reservas simuladas en memoria
RESERVAS = {1: {"reserva_id": 1, "user_id": 1, "hotel": "Hotel Bogotá Plaza", "fecha": "2026-04-10", "huespedes": 2},
            2: {"reserva_id": 2, "user_id": 1, "hotel": "Hotel Cartagena Beach", "fecha": "2026-05-15", "huespedes": 3},
            3: {"reserva_id": 3, "user_id": 2, "hotel": "Hotel Lima Central", "fecha": "2026-06-20", "huespedes": 1},
            4: {"reserva_id": 4, "user_id": 3, "hotel": "Hotel CDMX Centro", "fecha": "2026-07-01", "huespedes": 4},}

def get_db_connection():
    """Obtener una conexión a la base de datos"""
    
    # Configurar la conexión a la base de datos
    return psycopg2.connect(host = os.environ.get("DB_HOST", "db"), port = os.environ.get("DB_PORT", "5432"),
                            database = os.environ.get("DB_NAME", "travelhub"), user = os.environ.get("DB_USER", "travelhub"),
                            password = os.environ.get("DB_PASSWORD", "travelhub123"),)

def wait_for_db(max_retries = 10, delay = 3):
    """Espera a que PostgreSQL esté listo"""
    
    # Configurar el número máximo de intentos y el retardo entre cada intento
    for i in range(max_retries):
        
        # Intentar conectar a PostgreSQL
        try:
            
            # Intentar conectar a PostgreSQL
            conn = get_db_connection()
            
            # Cerrar la conexión a PostgreSQL
            conn.close()

            # Registrar que la conexión fue exitosa y retornar True
            logger.info("Conexión a PostgreSQL exitosa")
            return True
        
        # Si se produce un error, registrar el error y volver a intentar
        except Exception as e:

            # Registrar el error y esperar antes de volver a intentar
            logger.info(f"Esperando a PostgreSQL... intento {i + 1}/{max_retries}")
            
            # Esperar antes de volver a intentar
            time.sleep(delay)
    
    # Registrar que no se pudo conectar a PostgreSQL y retornar False
    logger.error("No se pudo conectar a PostgreSQL")
    return False

def init_db():
    """Crear la tabla de experimentos en la base de datos"""

    # Esperar a que PostgreSQL esté listo
    if not wait_for_db():
        raise Exception("PostgreSQL no disponible")
    
    # Configurar la conexión a la base de datos
    conn = get_db_connection()
    
    # Instanciar un cursor para la conexión
    cur = conn.cursor()
    
    # Ejecutar la consulta para crear la tabla de experimentos si no existe
    cur.execute("""CREATE TABLE IF NOT EXISTS experiment_log (id SERIAL PRIMARY KEY, timestamp TIMESTAMPTZ DEFAULT NOW(),
                    test_type VARCHAR(100), token_description VARCHAR(255),expected_result VARCHAR(50), actual_result VARCHAR(50),
                    http_status INTEGER, passed BOOLEAN)""")
    
    # Guardar los cambios en la base de datos
    conn.commit()
    
    # Cerrar el cursor y la conexión a la base de datos
    cur.close()
    
    # Cerrar la conexión a la base de datos
    conn.close()

    # Registrar que la base de datos se ha inicializado
    logger.info("Base de datos inicializada")


def log_experiment(test_type, token_desc, expected, actual, status, passed):
    """Registrar un experimento en la base de datos"""
    
    try:
        # Configurar la conexión a la base de datos
        conn = get_db_connection()

        # Instanciar un cursor para la conexión
        cur = conn.cursor()

        # Ejecutar la consulta para insertar el registro del experimento
        cur.execute("""INSERT INTO experiment_log (test_type, token_description, expected_result, actual_result, http_status, passed) VALUES (%s, %s, %s, %s, %s, %s)""", (test_type, token_desc, expected, actual, status, passed))
        
        # Guardar los cambios en la base de datos
        conn.commit()
        
        # Cerrar el cursor y la conexión a la base de datos
        cur.close()

        # Cerrar la conexión a la base de datos
        conn.close()
    
    # Registrar que el experimento se ha registradoo o si hubo un error al hacerlo
    except Exception as e:
        logger.error(f"Error registrando experimento: {e}")


def validate_token():
    """Extrae el token del header y lo valida contra el autorizador (doble canal)."""

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None, "Missing or invalid Authorization header"

    token = auth_header.split(" ")[1]

    # Forward original client context so autorizador can verify fingerprint
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    client_ua = request.headers.get("User-Agent", "")

    try:
        resp = requests.post(
            f"{AUTORIZADOR_URL}/validate",
            json={"token": token, "client_ip": client_ip, "client_ua": client_ua},
            timeout=5,
        )
    except requests.exceptions.RequestException as e:
        return None, f"Autorizador unavailable: {str(e)}"

    if resp.status_code == 200:
        body = resp.json()
        return body.get("claims"), None

    body = resp.json()
    return None, body.get("error", body.get("reason", "Unauthorized"))

@app.route('/reservas/health', methods = ['GET'])
def health():
    """Responde con un mensaje de health"""

    # Respondemos con un mensaje de health
    return jsonify({"service": "reservas", "status": "healthy", "timestamp": datetime.datetime.now(bogota_tz).strftime('%Y-%m-%d %H:%M:%S %Z')}), 200


@app.route('/reservas', methods = ['GET'])
def get_reservas():
    """Lista las reservas del usuario autenticado"""
    
    # Obtenemos el token
    claims, error = validate_token()

    # Si el token no es válido, respondemos con error 401
    if error:
        return jsonify({"error": error}), 401

    # Obtenemos el id del usuario
    user_id = claims["sub"]

    # Obtenemos el rol del usuario
    role = claims.get("role", "")

    # Obtenemos las reservas siempre y cuando el rol sea admin
    if role == "admin":
        result = list(RESERVAS.values())
    
    # Obtenemos las reservas solo de los usuarios que tienen la misma id que el token
    else:
        result = [r for r in RESERVAS.values() if r["user_id"] == user_id]

    # Registramos el acceso a la lista de reservas
    logger.info(f"GET /reservas - user_id: {user_id}, role: {role}, resultados: {len(result)}")
    
    # Respondemos con la lista de reservas
    return jsonify(result), 200

@app.route('/reservas/<int:reserva_id>', methods = ['GET'])
def get_reserva(reserva_id):
    """Obtiene una reserva específica"""
    
    # Obtenemos el token
    claims, error = validate_token()
    
    # Si el token no es válido, respondemos con error 401
    if error:
        return jsonify({"error": error}), 401

    # Obtenemos la reserva
    reserva = RESERVAS.get(reserva_id)

    # Si la reserva no existe, respondemos con error 404
    if not reserva:
        return jsonify({"error": "Reserva no encontrada"}), 404

    # Obtenemos el id del usuario
    user_id = claims["sub"]

    # Obtenemos el rol del usuario
    role = claims.get("role", "")

    # Si el usuario no es el dueño de la reserva o el rol no es admin, respondemos con error 403
    if role != "admin" and reserva["user_id"] != user_id:
        
        # Registramos el intento de acceso no autorizado
        logger.info(f"ACCESO DENEGADO - user_id: {user_id} intentó acceder a reserva de user_id: {reserva['user_id']}")
        
        # Respondemos con error 403
        return jsonify({"error": "No autorizado para ver esta reserva"}), 403

    # Respondemos con la reserva
    return jsonify(reserva), 200

@app.route('/reservas/<int:reserva_id>', methods = ['PUT'])
def update_reserva(reserva_id):
    """Modifica una reserva - solo el dueño puede hacerlo"""
    
    # Obtenemos el token
    claims, error = validate_token()
    
    # Si el token no es válido, respondemos con error 401
    if error:
        return jsonify({"error": error}), 401

    # Obtenemos la reserva
    reserva = RESERVAS.get(reserva_id)
    
    # Si la reserva no existe, respondemos con error 404
    if not reserva:
        return jsonify({"error": "Reserva no encontrada"}), 404

    # Obtenemos el id del usuario
    user_id = claims["sub"]

    # Solo el dueño puede modificar (HU023)
    if reserva["user_id"] != user_id:

        # Registramos el intento de acceso
        logger.info(f"MODIFICACIÓN DENEGADA - user_id: {user_id} intentó modificar reserva de user_id: {reserva['user_id']}")

        # Respondemos con error 403
        return jsonify({"error": "Solo el creador de la reserva puede modificarla"}), 403

    # Obtenemos los datos de la reserva
    data = request.get_json()
    
    # Modificamos solo los campos permitidos
    if data.get("fecha"):
        reserva["fecha"] = data["fecha"]
    
    # Solo se permite modificar el número de huéspedes, no el hotel (HU024)
    if data.get("huespedes"):
        reserva["huespedes"] = data["huespedes"]

    # Registramos la modificación
    logger.info(f"RESERVA MODIFICADA - reserva_id: {reserva_id} por user_id: {user_id}")
    
    # Respondemos con la reserva modificada
    return jsonify(reserva), 200

# Ejecutamos la aplicación Flask
if __name__ == '__main__':
    
    # Inicializamos la base de datos
    init_db()

    # Ejecutamos la aplicación Flask
    app.run(host = '0.0.0.0', port = 5003, debug = True, use_reloader = False)