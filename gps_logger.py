import subprocess
import time
import csv
import os
from datetime import datetime

# =========================
# ⚙️ 설정
# =========================
LOG_FILE = "gps_log.csv"
INTERVAL = 60  # 수집 간격 (초) - 배터리를 위해 60초 이상 권장


def get_location():
    # 1단계: 배터리 절약을 위해 'network' (와이파이/기지국) 먼저 시도
    try:
        # -p network: 배터리를 적게 씀, 실내에서도 잘 잡힘
        cmd = ["termux-location", "-p", "network"]
        # 5초 안에 잡히면 성공 (네트워크는 보통 빠름)
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=5
        )
        return result.stdout
    except:
        # 실패하면 조용히 다음 단계로 넘어감
        pass

    # 2단계: 네트워크 실패 시 'gps' (위성) 시도
    try:
        # -p gps: 배터리 많이 씀, 야외에서 정확함
        cmd = ["termux-location", "-p", "gps"]
        # GPS는 신호 잡는 데 오래 걸리므로 15초 대기
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=15
        )
        return result.stdout
    except:
        # 둘 다 실패하면 None 반환
        return None


def log_process():
    # CSV 파일이 없으면 헤더 생성
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["timestamp", "latitude", "longitude", "accuracy", "provider"]
            )

    print(f"📍 GPS 수집 시작 (간격: {INTERVAL}초)...")
    print(f"💾 저장 파일: {os.path.abspath(LOG_FILE)}")

    # Wake Lock 설정 (백그라운드에서 안 죽게)
    subprocess.run(["termux-wake-lock"])

    try:
        while True:
            loc_json_str = get_location()
            if loc_json_str:
                import json

                data = json.loads(loc_json_str)

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                lat = data.get("latitude")
                lon = data.get("longitude")
                acc = data.get("accuracy")
                prov = data.get("provider")

                with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow([timestamp, lat, lon, acc, prov])

                print(f"[{timestamp}] 기록됨: {lat}, {lon} ({prov})")
            else:
                print(f"[{datetime.now()}] 위치 수신 실패")

            time.sleep(INTERVAL)

    except KeyboardInterrupt:
        print("중지됨.")
    finally:
        # 종료 시 Wake Lock 해제
        subprocess.run(["termux-wake-unlock"])


if __name__ == "__main__":
    log_process()
