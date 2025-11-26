import subprocess
import time
import json
import os
import csv
from datetime import datetime

# =========================
# ⚙️ 설정 (알고리즘 파라미터)
# =========================
LOG_FILE = "gps_log.csv"

# 시간 설정 (초 단위)
GPS_TIMEOUT = 20  # GPS 탐색 제한 시간
LONG_NET_TIMEOUT = 120  # GPS 실패 직후 넉넉한 네트워크 탐색 시간 (2분)
SHORT_NET_TIMEOUT = 20  # 평상시 네트워크 탐색 시간
GPS_RETRY_INTERVAL = 3600  # 네트워크 모드일 때 GPS 재시도 간격 (1시간)
LOOP_INTERVAL = 60  # 데이터 수집 및 루프 간격 (1분)


def log(msg):
    """터미널에 시간과 함께 로그 출력"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def save_to_csv(json_str):
    """JSON 형태의 위치 데이터를 파싱하여 CSV에 저장"""
    try:
        data = json.loads(json_str)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lat = data.get("latitude")
        lon = data.get("longitude")
        acc = data.get("accuracy")
        prov = data.get("provider")

        # CSV 파일이 없으면 헤더 생성
        if not os.path.exists(LOG_FILE):
            with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["timestamp", "latitude", "longitude", "accuracy", "provider"]
                )

        # 데이터 추가 (Append)
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([timestamp, lat, lon, acc, prov])

        log(f"💾 기록됨: 위도 {lat}, 경도 {lon} ({prov})")
        return True
    except Exception as e:
        log(f"❌ 데이터 저장 실패: {e}")
        return False


def try_gps():
    """GPS 위치 획득 시도 (20초 제한 + 강제 종료)"""
    log("🛰️ GPS 위치 탐색 시작 (최대 20초)...")

    proc = subprocess.Popen(
        ["termux-location", "-p", "gps"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = proc.communicate(timeout=GPS_TIMEOUT)
        if proc.returncode == 0:
            log("✅ GPS 위치 확보 성공!")
            save_to_csv(stdout)  # 저장
            return True
        else:
            log(f"❌ GPS 탐색 실패 (에러 코드: {proc.returncode})")
            return False

    except subprocess.TimeoutExpired:
        log("⚠️ GPS 시간 초과! 프로세스를 강제 종료(Kill)합니다.")
        proc.kill()
        proc.wait()
        return False
    except Exception as e:
        log(f"❌ GPS 오류 발생: {e}")
        try:
            proc.kill()
        except:
            pass
        return False


def try_network(duration):
    """네트워크 위치 획득 시도 (시간 지정 가능)"""
    log(f"📡 네트워크 위치 탐색 시작 (최대 {duration}초 대기)...")

    try:
        result = subprocess.run(
            ["termux-location", "-p", "network"],
            capture_output=True,
            text=True,
            timeout=duration,
        )

        if result.returncode == 0:
            log("✅ 네트워크 위치 확보 성공!")
            save_to_csv(result.stdout)  # 저장
            return True
        else:
            log("❌ 네트워크 탐색 실패.")
            return False

    except subprocess.TimeoutExpired:
        log(f"⚠️ 네트워크 탐색 시간 초과 ({duration}초 경과).")
        return False


def main_logic():
    # 초기 상태: 무조건 GPS 먼저 시도
    current_mode = "GPS_MODE"
    last_gps_try_time = time.time()

    log(f"🚀 스마트 위치 추적 시작 (저장 파일: {LOG_FILE})")

    # 백그라운드에서 죽지 않도록 Wake Lock 설정
    subprocess.run(["termux-wake-lock"])

    try:
        while True:
            if current_mode == "GPS_MODE":
                # [상황 1] GPS 모드: 1분마다 GPS 시도
                if try_gps():
                    log(f"   -> GPS 모드 유지. {LOOP_INTERVAL}초 대기.")
                else:
                    # 실패하면 네트워크 모드로 전환 + 롱 네트워크 탐색 (2분)
                    log("🔄 GPS 실패. 시스템 안정화를 위해 2분간 네트워크 탐색 시도...")
                    try_network(LONG_NET_TIMEOUT)

                    current_mode = "NETWORK_MODE"
                    last_gps_try_time = time.time()  # 1시간 타이머 시작
                    log(f"   -> 네트워크 모드로 전환됨. (다음 GPS 재시도: 1시간 뒤)")

            elif current_mode == "NETWORK_MODE":
                # [상황 2] 네트워크 모드

                # 1시간이 지났는지 확인
                time_since_last_gps = time.time() - last_gps_try_time

                if time_since_last_gps >= GPS_RETRY_INTERVAL:
                    log("⏰ 1시간 경과. GPS 재확인 시도...")
                    if try_gps():
                        # GPS가 잡히면 모드 복귀
                        current_mode = "GPS_MODE"
                        log("🎉 GPS가 다시 잡혔습니다! GPS 모드로 복귀.")
                    else:
                        # 여전히 안 잡히면 다시 롱 네트워크 탐색
                        log("😓 여전히 GPS 안 잡힘. 다시 2분간 네트워크 탐색.")
                        try_network(LONG_NET_TIMEOUT)
                        last_gps_try_time = time.time()  # 타이머 리셋
                else:
                    # 1시간 안 됐으면 짧게 네트워크 탐색
                    try_network(SHORT_NET_TIMEOUT)
                    log(
                        f"   -> 네트워크 모드 유지. (GPS 재시도까지 {int((GPS_RETRY_INTERVAL - time_since_last_gps)/60)}분 남음)"
                    )

            # 공통: 1분 대기
            time.sleep(LOOP_INTERVAL)

    except KeyboardInterrupt:
        log("사용자에 의해 중지됨.")
    finally:
        # 종료 시 Wake Lock 해제
        subprocess.run(["termux-wake-unlock"])
        log("🛑 위치 추적 종료 (Wake Lock 해제됨)")


if __name__ == "__main__":
    main_logic()
