import os
import pytz
import time
import random
import logging
from datetime import datetime, timedelta
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine, text

logging.basicConfig(
    format='\n%(asctime)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S %p: ',
    level=logging.INFO
)
logger = logging.getLogger('ordenes')

app = Flask(__name__)

SERVICE_NAME = 'ordenes'
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://travelhub:travelhub@localhost:5432/travelhub')

engine = None


def get_engine():
    global engine
    if engine is None:
        engine = create_engine(DATABASE_URL)
    return engine


def init_db():
    for attempt in range(15):
        try:
            eng = get_engine()
            with eng.connect() as conn:
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
            logger.info(f"{SERVICE_NAME} -> DB initialized")
            return
        except Exception as e:
            logger.warning(f"{SERVICE_NAME} -> DB not ready (attempt {attempt + 1}/15): {e}")
            time.sleep(3)


def log_state_change(state, delay_ms):
    try:
        eng = get_engine()
        with eng.connect() as conn:
            conn.execute(
                text("INSERT INTO service_state_events (service, state, delay_ms) VALUES (:s, :st, :d)"),
                {"s": SERVICE_NAME, "st": state, "d": delay_ms}
            )
            conn.commit()
    except Exception as e:
        logger.error(f"{SERVICE_NAME} -> Failed to log state change: {e}")


service_state = {"status": "healthy", "delay": 0}


def random_failure():
    roll = random.random()

    if roll < 0.3:
        service_state["status"] = "degraded"
        service_state["delay"] = random.uniform(2, 5)
        logger.info(f"{SERVICE_NAME} -> DEGRADED (delay: {service_state['delay']:.1f}s)")
        log_state_change("degraded", service_state["delay"] * 1000)

    elif roll < 0.5:
        service_state["status"] = "unhealthy"
        service_state["delay"] = 0
        logger.info(f"{SERVICE_NAME} -> UNHEALTHY")
        log_state_change("unhealthy", 0)

    else:
        service_state["status"] = "healthy"
        service_state["delay"] = 0
        logger.info(f"{SERVICE_NAME} -> HEALTHY")
        log_state_change("healthy", 0)


init_db()

scheduler = BackgroundScheduler()
end_time = datetime.now() + timedelta(minutes=10)
scheduler.add_job(random_failure, 'interval', seconds=random.randint(15, 30), end_date=end_time)
scheduler.start()


@app.route('/health', methods=['GET'])
def health():
    start = time.time()

    if service_state["status"] == "unhealthy":
        elapsed_ms = round((time.time() - start) * 1000, 2)
        return jsonify({
            "service": SERVICE_NAME,
            "status": "unhealthy",
            "response_time_ms": elapsed_ms,
            "timestamp": datetime.now(pytz.timezone('America/Bogota')).strftime('%Y-%m-%d %H:%M:%S %Z')
        }), 500

    if service_state["status"] == "degraded":
        time.sleep(service_state["delay"])

    elapsed_ms = round((time.time() - start) * 1000, 2)
    return jsonify({
        "service": SERVICE_NAME,
        "status": service_state["status"],
        "response_time_ms": elapsed_ms,
        "timestamp": datetime.now(pytz.timezone('America/Bogota')).strftime('%Y-%m-%d %H:%M:%S %Z')
    }), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002, debug=False)
