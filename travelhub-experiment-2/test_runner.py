"""
Test Runner — HU023/HU024 Token Tampering Detection Experiment
Runs 8 scenarios × 3 iterations each and prints structured results.

Usage:
    pip install requests PyJWT cryptography
    python test_runner.py [--autorizador http://localhost:5001] [--reservas http://localhost:5003]
"""

import argparse
import datetime as dt
import json
import sys
import time

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_public_key

ITERATIONS = 3

BASE_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "TestRunner/1.0",
}

def login(autorizador_url, username, password, ip=None, ua=None):
    headers = dict(BASE_HEADERS)
    if ip:
        headers["X-Forwarded-For"] = ip
    if ua:
        headers["User-Agent"] = ua
    resp = requests.post(
        f"{autorizador_url}/login",
        json={"username": username, "password": password},
        headers=headers,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()

def get_reservas(reservas_url, token, ip=None, ua=None):
    headers = {**BASE_HEADERS, "Authorization": f"Bearer {token}"}
    if ip:
        headers["X-Forwarded-For"] = ip
    if ua:
        headers["User-Agent"] = ua
    start = time.monotonic()
    resp = requests.get(f"{reservas_url}/reservas", headers=headers, timeout=10)
    latency_ms = (time.monotonic() - start) * 1000
    return resp, latency_ms

def revoke(autorizador_url, jti):
    resp = requests.post(
        f"{autorizador_url}/revoke",
        json={"jti": jti},
        headers=BASE_HEADERS,
        timeout=10,
    )
    return resp

def get_public_key_der(autorizador_url):
    resp = requests.get(f"{autorizador_url}/public-key", timeout=10)
    resp.raise_for_status()
    pem = resp.json()["public_key_pem"].encode()
    pub = load_pem_public_key(pem)
    return pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

def forge_token(public_key_der, payload_overrides=None):
    """Forge an HS256 token using the public key DER bytes as HMAC secret."""
    payload = {
        "sub": 999,
        "role": "admin",
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
        "iat": dt.datetime.now(dt.timezone.utc),
    }
    if payload_overrides:
        payload.update(payload_overrides)
    return jwt.encode(payload, public_key_der, algorithm="HS256")

def forge_expired_token(public_key_der, jti=None):
    """Forge a token that is already expired."""
    payload = {
        "sub": 999,
        "role": "admin",
        "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1),
        "iat": dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2),
    }
    if jti:
        payload["jti"] = jti
    return jwt.encode(payload, public_key_der, algorithm="HS256")

def run_scenario(name, description, expected_status, fn):
    results = []
    for i in range(1, ITERATIONS + 1):
        try:
            resp, latency_ms = fn()
            status = resp.status_code
            body = {}
            try:
                body = resp.json()
            except Exception:
                pass

            correct = (status == expected_status)
            blocked = status != 200

            jwt_validation = body.get("jwt_validation", "N/A")
            fp_validation = body.get("fingerprint_validation", "N/A")
            reason = body.get("reason") or body.get("error") or ""

            result = {
                "scenario": name,
                "description": description,
                "iteration": i,
                "expected_http": expected_status,
                "actual_http": status,
                "jwt_validation": jwt_validation,
                "fingerprint_validation": fp_validation,
                "reason": reason,
                "final_result": "BLOCKED" if blocked else "ALLOWED",
                "correct": correct,
                "latency_ms": round(latency_ms, 2),
            }
        except Exception as e:
            result = {
                "scenario": name,
                "description": description,
                "iteration": i,
                "expected_http": expected_status,
                "actual_http": None,
                "error": str(e),
                "correct": False,
            }
        results.append(result)
        _print_result(result)
    return results

def _print_result(r):
    mark = "✓" if r.get("correct") else "✗"
    jwt_v = r.get("jwt_validation", "")
    fp_v = r.get("fingerprint_validation", "")
    reason = r.get("reason", "")
    latency = r.get("latency_ms", "")
    print(
        f"  [{mark}] iter={r['iteration']} "
        f"http={r.get('actual_http')} "
        f"jwt={jwt_v} fp={fp_v} "
        f"result={r.get('final_result', 'ERROR')} "
        f"latency={latency}ms"
        + (f" reason={reason}" if reason else "")
    )

def run_all(autorizador_url, reservas_url):
    all_results = []
    public_key_der = get_public_key_der(autorizador_url)

    print("\n[Scenario 1] Línea base: token válido")

    def s1():
        data = login(autorizador_url, "viajero1", "pass1")
        return get_reservas(reservas_url, data["token"])

    all_results += run_scenario(
        "baseline_valid_token",
        "Login normal, request con token legítimo",
        200,
        s1,
    )

    print("\n[Scenario 2] Token forjado DER (sin JTI)")

    def s2():
        token = forge_token(public_key_der)  # no jti
        return get_reservas(reservas_url, token)

    all_results += run_scenario(
        "forged_token_der_no_jti",
        "Token forjado con algorithm confusion DER, sin campo jti",
        401,
        s2,
    )

    print("\n[Scenario 3] Token forjado DER (JTI inventado)")

    def s3():
        token = forge_token(public_key_der, {"jti": "fake-uuid-00000000-0000"})
        return get_reservas(reservas_url, token)

    all_results += run_scenario(
        "forged_token_der_fake_jti",
        "Token forjado con jti='fake-uuid-0000' (no existe en BD)",
        401,
        s3,
    )

    print("\n[Scenario 4] Token forjado DER (JTI robado, diferente IP/UA)")

    def s4():
        data = login(autorizador_url, "viajero1", "pass1",
                     ip="10.0.0.1", ua="LegitBrowser/1.0")
        stolen_jti = data["jti"]
        # Forged token with the stolen JTI but different UA
        token = forge_token(public_key_der, {"jti": stolen_jti})
        return get_reservas(reservas_url, token,
                            ip="192.168.99.99", ua="AttackerBot/2.0")

    all_results += run_scenario(
        "forged_token_der_stolen_jti_diff_context",
        "Forged token with stolen JTI but different IP/User-Agent",
        401,
        s4,
    )

    print("\n[Scenario 5] Token forjado DER (JTI robado + contexto replicado)")

    def s5():
        data = login(autorizador_url, "viajero1", "pass1",
                     ip="10.0.0.1", ua="LegitBrowser/1.0")
        stolen_jti = data["jti"]
        # Attacker replicates exact IP and UA used at login
        token = forge_token(public_key_der, {"jti": stolen_jti})
        return get_reservas(reservas_url, token,
                            ip="10.0.0.1", ua="LegitBrowser/1.0")

    all_results += run_scenario(
        "forged_token_der_stolen_jti_same_context",
        "Forged token with stolen JTI AND replicated IP/User-Agent (worst case)",
        200,  # System is expected to FAIL to detect this (second-layer evasion)
        s5,
    )

    print("\n[Scenario 6] Token válido desde otra IP (posible falso positivo)")

    def s6():
        data = login(autorizador_url, "viajero2", "pass2",
                     ip="172.16.0.1", ua="Browser/3.0")
        # Same UA, different IP
        return get_reservas(reservas_url, data["token"],
                            ip="172.16.99.99", ua="Browser/3.0")

    all_results += run_scenario(
        "valid_token_different_ip",
        "Login legítimo, luego request con IP diferente vía X-Forwarded-For",
        401,  # Expected: blocked (fingerprint mismatch)
        s6,
    )

    print("\n[Scenario 7] Token revocado")

    def s7():
        data = login(autorizador_url, "hotel1", "pass3")
        revoke(autorizador_url, data["jti"])
        return get_reservas(reservas_url, data["token"])

    all_results += run_scenario(
        "revoked_token",
        "Login, revocar sesión, intentar usar token",
        401,
        s7,
    )

    print("\n[Scenario 8] Token expirado con JTI válido")

    def s8():
        data = login(autorizador_url, "viajero1", "pass1")
        expired_token = forge_expired_token(public_key_der, jti=data["jti"])
        return get_reservas(reservas_url, expired_token)

    all_results += run_scenario(
        "expired_token_valid_jti",
        "Token con exp en el pasado, jti existe en BD (bloqueado en capa 1)",
        401,
        s8,
    )

    return all_results

def print_summary(results):
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    scenarios = {}
    for r in results:
        s = r["scenario"]
        if s not in scenarios:
            scenarios[s] = {"total": 0, "correct": 0}
        scenarios[s]["total"] += 1
        if r.get("correct"):
            scenarios[s]["correct"] += 1

    all_correct = True
    for name, stats in scenarios.items():
        pct = 100 * stats["correct"] // stats["total"]
        mark = "✓" if stats["correct"] == stats["total"] else "✗"
        print(f"  [{mark}] {name}: {stats['correct']}/{stats['total']} correct ({pct}%)")
        if stats["correct"] != stats["total"]:
            all_correct = False

    total = len(results)
    correct = sum(1 for r in results if r.get("correct"))
    print(f"\n  Overall: {correct}/{total} ({100 * correct // total}%)")

    latencies = [r["latency_ms"] for r in results if "latency_ms" in r]
    if latencies:
        avg_lat = sum(latencies) / len(latencies)
        max_lat = max(latencies)
        print(f"  Avg latency: {avg_lat:.1f}ms  Max: {max_lat:.1f}ms")

    print("=" * 70)
    return all_correct


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--autorizador", default="http://localhost:5001")
    parser.add_argument("--reservas", default="http://localhost:5003")
    parser.add_argument("--output", default=None, help="JSON output file")
    args = parser.parse_args()

    print(f"Autorizador: {args.autorizador}")
    print(f"Reservas:    {args.reservas}")

    for url, name in [(args.autorizador, "autorizador"), (args.reservas, "reservas")]:
        for _ in range(15):
            try:
                requests.get(f"{url}/", timeout=3)
                print(f"{name} ready")
                break
            except Exception:
                print(f"Waiting for {name}...")
                time.sleep(2)

    results = run_all(args.autorizador, args.reservas)
    success = print_summary(results)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults written to {args.output}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
