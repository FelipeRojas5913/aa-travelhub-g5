import os
import time
import logging
from collections import deque
from datetime import datetime

import pytz
import requests
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine, text

logging.basicConfig(
    format='\n%(asctime)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S %p: ',
    level=logging.INFO
)
logger = logging.getLogger('monitor')

app = Flask(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://travelhub:travelhub@localhost:5432/travelhub')

SERVICES = {
    'busqueda':   os.environ.get('BUSQUEDA_URL',   'http://busqueda:5000/health'),
    'inventario': os.environ.get('INVENTARIO_URL', 'http://inventario:5001/health'),
    'ordenes':    os.environ.get('ORDENES_URL',    'http://ordenes:5002/health'),
    'reservas':   os.environ.get('RESERVAS_URL',   'http://reservas:5003/health'),
    'usuarios':   os.environ.get('USUARIOS_URL',   'http://usuarios:5004/health'),
}

# Rolling window of response times per service (last 20 checks)
RESPONSE_HISTORY = {name: deque(maxlen=20) for name in SERVICES}

# Latency threshold for DEGRADED: response_time > max(baseline * 2, 1000ms)
DEGRADED_THRESHOLD_MS = 1000

engine = None


def get_engine():
    global engine
    if engine is None:
        engine = create_engine(DATABASE_URL)
    return engine


def init_db():
    for attempt in range(20):
        try:
            eng = get_engine()
            with eng.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS monitor_checks (
                        id SERIAL PRIMARY KEY,
                        service VARCHAR(50) NOT NULL,
                        status VARCHAR(20) NOT NULL,
                        response_time_ms FLOAT,
                        http_status INTEGER,
                        checked_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS service_state_events (
                        id SERIAL PRIMARY KEY,
                        service VARCHAR(50) NOT NULL,
                        state VARCHAR(20) NOT NULL,
                        delay_ms FLOAT,
                        changed_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """))
                conn.commit()
            logger.info("monitor -> DB initialized")
            return
        except Exception as e:
            logger.warning(f"monitor -> DB not ready (attempt {attempt + 1}/20): {e}")
            time.sleep(3)


def persist_check(service, status, response_time_ms, http_status):
    try:
        eng = get_engine()
        with eng.connect() as conn:
            conn.execute(
                text("""
                    INSERT INTO monitor_checks (service, status, response_time_ms, http_status)
                    VALUES (:svc, :st, :rt, :hs)
                """),
                {"svc": service, "st": status, "rt": response_time_ms, "hs": http_status}
            )
            conn.commit()
    except Exception as e:
        logger.error(f"monitor -> Failed to persist check for {service}: {e}")


def classify(service, response_time_ms, http_status):
    if http_status is None or http_status >= 500:
        return 'DOWN'

    history = RESPONSE_HISTORY[service]
    if len(history) >= 3:
        rolling_mean = sum(history) / len(history)
        threshold = max(rolling_mean * 2, DEGRADED_THRESHOLD_MS)
    else:
        threshold = DEGRADED_THRESHOLD_MS

    if response_time_ms > threshold:
        return 'DEGRADED'
    return 'HEALTHY'


def check_service(service, url):
    start = time.time()
    http_status = None
    response_time_ms = None

    try:
        resp = requests.get(url, timeout=8)
        http_status = resp.status_code
        response_time_ms = round((time.time() - start) * 1000, 2)
    except requests.exceptions.ConnectionError:
        response_time_ms = round((time.time() - start) * 1000, 2)
    except requests.exceptions.Timeout:
        response_time_ms = round((time.time() - start) * 1000, 2)
    except Exception as e:
        response_time_ms = round((time.time() - start) * 1000, 2)
        logger.error(f"monitor -> Unexpected error checking {service}: {e}")

    status = classify(service, response_time_ms, http_status)

    # Only add to rolling history when service responds (not DOWN)
    if status != 'DOWN':
        RESPONSE_HISTORY[service].append(response_time_ms)

    persist_check(service, status, response_time_ms, http_status)
    logger.info(f"monitor -> {service}: {status} ({response_time_ms}ms, HTTP {http_status})")
    return status, response_time_ms, http_status


def poll_all_services():
    logger.info("monitor -> Polling all services...")
    for service, url in SERVICES.items():
        check_service(service, url)


init_db()

scheduler = BackgroundScheduler()
scheduler.add_job(poll_all_services, 'interval', seconds=10)
scheduler.start()

# Run first check immediately on startup
poll_all_services()


@app.route('/status', methods=['GET'])
def status():
    try:
        eng = get_engine()
        with eng.connect() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT ON (service)
                    service, status, response_time_ms, http_status, checked_at
                FROM monitor_checks
                ORDER BY service, checked_at DESC
            """)).fetchall()

        services_status = []
        for row in rows:
            services_status.append({
                "service": row[0],
                "status": row[1],
                "response_time_ms": row[2],
                "http_status": row[3],
                "checked_at": row[4].isoformat() if row[4] else None
            })

        return jsonify({
            "timestamp": datetime.now(pytz.timezone('America/Bogota')).strftime('%Y-%m-%d %H:%M:%S %Z'),
            "services": services_status
        }), 200

    except Exception as e:
        logger.error(f"monitor -> /status error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "OK", "service": "monitor"}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
