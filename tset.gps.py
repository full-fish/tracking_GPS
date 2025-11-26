import subprocess
import time
import json
from datetime import datetime

# 설정 값
GPS_TIMEOUT = 15  # GPS 시도 시간 (짧게 치고 빠짐)
LONG_NET_TIMEOUT = 120  # GPS 실패 후 '콜드 타임' 고려한 넉넉한 네트워크 탐색 (2분)
SHORT_NET_TIMEOUT = 20  # 평상시 네트워크 탐색 (20초)
GPS_RETRY_INTERVAL = 3600  # 네트워크 모드일 때 GPS 재시도 간격 (1시간 = 3600초)
LOOP_INTERVAL = 60  # 기본 반복 간격 (1분)


def log(msg):
    """현재 시간과 함께 로그 출력"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def try_gps():
    """GPS 위치 획득 시도 (15초 제한 + 강제 종료 포함)"""
    log("🛰️ GPS 위치 탐색 시작 (최대 15초)...")

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
            # (여기서 필요한 위치 처리 로직 추가 가능)
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
        # 네트워크는 굳이 kill 할 필요 없이 timeout 옵션 사용
        result = subprocess.run(
            ["termux-location", "-p", "network"],
            capture_output=True,
            text=True,
            timeout=duration,
        )

        if result.returncode == 0:
            log("✅ 네트워크 위치 확보 성공!")
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

    log("🚀 위치 추적 시스템 시작")

    while True:
        if current_mode == "GPS_MODE":
            # [상황 1] GPS 모드: 1분마다 GPS 잡기
            if try_gps():
                # 성공하면 계속 GPS 모드 유지
                log(f"   -> GPS 모드 유지. {LOOP_INTERVAL}초 뒤 다시 실행.")
            else:
                # 실패하면 네트워크 모드로 전환 + 롱 네트워크 탐색
                log("🔄 GPS 실패. 2분간 넉넉하게 네트워크 탐색 시도 (Recovering)...")
                try_network(LONG_NET_TIMEOUT)  # 2분 대기

                current_mode = "NETWORK_MODE"
                last_gps_try_time = time.time()  # 1시간 타이머 시작
                log(f"   -> 네트워크 모드로 전환됨. (다음 GPS 시도: 1시간 뒤)")

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
                    # 여전히 안 잡히면 다시 롱 네트워크 탐색 (GPS 찌꺼기 정리)
                    log("😓 여전히 GPS 안 잡힘. 다시 2분간 네트워크 탐색.")
                    try_network(LONG_NET_TIMEOUT)
                    last_gps_try_time = time.time()  # 타이머 리셋
            else:
                # 1시간 안 됐으면 그냥 1분마다 짧게 네트워크 탐색
                try_network(SHORT_NET_TIMEOUT)
                log(
                    f"   -> 네트워크 모드 유지. (GPS 재시도까지 {int((GPS_RETRY_INTERVAL - time_since_last_gps)/60)}분 남음)"
                )

        # 공통: 1분 대기
        time.sleep(LOOP_INTERVAL)


if __name__ == "__main__":
    try:
        main_logic()
    except KeyboardInterrupt:
        log("종료합니다.")
