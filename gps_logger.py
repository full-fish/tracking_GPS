import subprocess
import time
import json
import os
import csv
from datetime import datetime

# =========================
# ⚙️ 설정 (알고리즘 파라미터)
# =========================
# Tasker 오류 방지를 위한 절대 경로
BASE_DIR = "/data/data/com.termux/files/home/dev/tracking_GPS"
LOG_FILE = os.path.join(BASE_DIR, "gps_log.csv")

# 시간 설정 (초 단위)
GPS_TIMEOUT = 20  # GPS 탐색 제한 시간
LONG_NET_TIMEOUT = 120  # GPS 실패 직후 넉넉한 네트워크 탐색 시간 (2분)
SHORT_NET_TIMEOUT = 20  # 평상시 네트워크 탐색 시간
GPS_RETRY_INTERVAL = 1800  # 네트워크 모드일 때 GPS 재시도 간격 (30분)
LOOP_INTERVAL = 60  # 기본 반복 간격 (1분)


def log(msg):
    """터미널에 시간과 함께 로그 출력"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def save_to_csv(json_str):
    """JSON 데이터를 CSV에 저장"""
    try:
        data = json.loads(json_str)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lat = data.get("latitude")
        lon = data.get("longitude")
        acc = data.get("accuracy")
        prov = data.get("provider")

        if not os.path.exists(LOG_FILE):
            with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["timestamp", "latitude", "longitude", "accuracy", "provider"]
                )

        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, lat, lon, acc, prov])

        log(f"💾 기록됨: {lat}, {lon} ({prov})")
        return True
    except Exception as e:
        log(f"❌ 저장 실패: {e}")
        return False


def try_gps():
    log("🛰️ GPS 탐색 (최대 20초)...")
    proc = subprocess.Popen(
        ["termux-location", "-p", "gps"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=GPS_TIMEOUT)
        if proc.returncode == 0:
            log("✅ GPS 성공!")
            save_to_csv(stdout)
            return True
        return False
    except subprocess.TimeoutExpired:
        log("⚠️ GPS 시간 초과. Kill.")
        proc.kill()
        proc.wait()
        return False
    except:
        try:
            proc.kill()
        except:
            pass
        return False


def try_network(duration):
    log(f"📡 네트워크 탐색 ({duration}초)...")
    try:
        result = subprocess.run(
            ["termux-location", "-p", "network"],
            capture_output=True,
            text=True,
            timeout=duration,
        )
        if result.returncode == 0:
            log("✅ 네트워크 성공!")
            save_to_csv(result.stdout)
            return True
        return False
    except subprocess.TimeoutExpired:
        log(f"⚠️ 네트워크 시간 초과.")
        return False


def main_logic():
    current_mode = "GPS_MODE"
    last_gps_try_time = time.time()

    log(f"🚀 스마트 위치 추적 시작")
    subprocess.run(["termux-wake-lock"])  # 백그라운드 유지

    try:
        while True:
            if current_mode == "GPS_MODE":
                if try_gps():
                    log(f"   -> GPS 모드 유지. {LOOP_INTERVAL}초 대기.")
                else:
                    log("🔄 GPS 실패. 2분간 네트워크 탐색 (Cooling down)...")
                    try_network(LONG_NET_TIMEOUT)
                    current_mode = "NETWORK_MODE"
                    last_gps_try_time = time.time()
                    log(f"   -> 네트워크 모드 전환. (GPS 재시도: 30분 뒤)")

            elif current_mode == "NETWORK_MODE":
                time_since_last_gps = time.time() - last_gps_try_time
                if time_since_last_gps >= GPS_RETRY_INTERVAL:
                    log("⏰ 30분 경과. GPS 재확인...")
                    if try_gps():
                        current_mode = "GPS_MODE"
                        log("🎉 GPS 복구됨! GPS 모드로 복귀.")
                    else:
                        log("😓 GPS 실패. 다시 2분간 네트워크 탐색.")
                        try_network(LONG_NET_TIMEOUT)
                        last_gps_try_time = time.time()
                else:
                    try_network(SHORT_NET_TIMEOUT)
                    log(f"   -> 네트워크 모드 유지.")

            time.sleep(LOOP_INTERVAL)

    except KeyboardInterrupt:
        log("중지됨.")
    finally:
        subprocess.run(["termux-wake-unlock"])
        log("🛑 종료 (Wake Lock 해제)")


if __name__ == "__main__":
    main_logic()
