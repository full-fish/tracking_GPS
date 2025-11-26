import sys
import subprocess
import os
import csv
import smtplib
import configparser
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# =========================
# ⚙️ 파일 및 설정
# =========================
LOGGER_SCRIPT = "gps_logger.py"
LOG_FILE = "gps_log.csv"
# 기본적으로 같은 폴더를 찾지만, 없으면 아래 절대 경로를 확인합니다.
CONFIG_FILE = "config.ini"
# 만선님이 알려주신 정확한 절대 경로
ABSOLUTE_CONFIG_PATH = "/data/data/com.termux/files/home/dev/tracking_GPS/config.ini"

# =========================
# 🛠️ 기능 함수들
# =========================


def start_logging():
    # 이미 실행 중인지 확인
    try:
        pid = subprocess.check_output(["pgrep", "-f", LOGGER_SCRIPT]).strip()
        print(f"⚠️ 이미 실행 중입니다! (PID: {pid.decode()})")
    except subprocess.CalledProcessError:
        # 백그라운드 실행 (nohup 사용)
        # 로그 파일 경로도 절대 경로로 잡히도록 현재 위치 기준 실행
        cmd = f"nohup python {LOGGER_SCRIPT} > /dev/null 2>&1 &"
        os.system(cmd)
        print(f"✅ GPS 수집을 시작했습니다. (백그라운드)")


def stop_logging():
    try:
        # 실행 중인 프로세스 찾아서 종료
        pid = subprocess.check_output(["pgrep", "-f", LOGGER_SCRIPT]).strip()
        os.system(f"kill {pid.decode()}")
        subprocess.run(["termux-wake-unlock"])  # 혹시 몰라 락 해제 한번 더
        print("🛑 GPS 수집을 종료했습니다.")
    except subprocess.CalledProcessError:
        print("⚠️ 실행 중인 GPS 수집기가 없습니다.")


def create_kml(data_rows, output_file):
    # 구글 어스용 KML 파일 생성 함수
    kml_header = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>내 이동 경로</name>
    <Style id="lineStyle">
      <LineStyle>
        <color>ff0000ff</color>
        <width>4</width>
      </LineStyle>
    </Style>
    <Placemark>
      <name>Path</name>
      <styleUrl>#lineStyle</styleUrl>
      <LineString>
        <tessellate>1</tessellate>
        <coordinates>
"""
    kml_footer = """        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(kml_header)
        for row in data_rows:
            # CSV 순서: time, lat, lon, acc, provider
            # KML 좌표 순서: lon, lat, alt
            if len(row) >= 3:
                f.write(f"{row[2]},{row[1]},0 \n")
        f.write(kml_footer)


def send_email_with_files(files, start_t, end_t):
    # config.ini 읽기
    config = configparser.ConfigParser()

    # 1. 현재 폴더 확인
    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
    # 2. 절대 경로 확인 (알려주신 경로)
    elif os.path.exists(ABSOLUTE_CONFIG_PATH):
        config.read(ABSOLUTE_CONFIG_PATH)
    else:
        print(
            f"❌ config.ini 파일을 찾을 수 없습니다.\n(경로 확인: {ABSOLUTE_CONFIG_PATH})"
        )
        return

    if not config.sections():
        print("❌ 설정 파일에 계정 정보가 없습니다.")
        return

    email_sent_flag = False

    # 🔄 모든 섹션(계정)을 돌면서 전송 시도 (하나라도 성공하면 중단)
    for section in config.sections():
        print(f"\n📨 [{section}] 계정으로 전송 시도 중...")

        try:
            settings = config[section]

            # 필수 정보 확인
            SMTP_SERVER = settings.get("smtp_server")
            SMTP_PORT = settings.get("smtp_port")
            SENDER_EMAIL = settings.get("sender_email")
            APP_PASSWORD = settings.get("app_password")
            RECIPIENT_EMAIL = settings.get("recipient_email")

            if not all(
                [SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, APP_PASSWORD, RECIPIENT_EMAIL]
            ):
                print(f"  ⚠️ [{section}] 정보 부족. 다음 계정으로 넘어갑니다.")
                continue

            # 메일 내용 구성
            msg = MIMEMultipart()
            msg["From"] = SENDER_EMAIL
            msg["To"] = RECIPIENT_EMAIL
            msg["Subject"] = f"🗺️ 이동 동선 데이터 ({start_t} ~ {end_t})"

            body = (
                f"요청하신 기간의 이동 경로 데이터입니다.\n"
                f"- 발송 서버: {section}\n"
                f"- 기간: {start_t} ~ {end_t}\n\n"
                f"첨부파일:\n"
                f"1. .csv: 엑셀 데이터\n"
                f"2. .kml: 구글 어스/지도용 경로 파일"
            )
            msg.attach(MIMEText(body, "plain"))

            # 파일 첨부
            for filename in files:
                if os.path.exists(filename):
                    with open(filename, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition", f"attachment; filename={filename}"
                    )
                    msg.attach(part)

            # SMTP 전송
            server = smtplib.SMTP(SMTP_SERVER, int(SMTP_PORT))
            server.starttls()
            server.login(SENDER_EMAIL, APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
            server.quit()

            print(f"  ✅ [{section}] 메일 전송 성공!")
            email_sent_flag = True
            break  # 성공했으므로 반복문 종료

        except Exception as e:
            print(f"  ❌ [{section}] 전송 실패: {e}")
            print("  🔄 다음 계정을 시도합니다...")
            continue

    # 파일 정리
    for f in files:
        if os.path.exists(f):
            os.remove(f)

    if not email_sent_flag:
        print("\n❌ 모든 계정으로 전송을 시도했으나 실패했습니다.")


def send_data(start_str, end_str):
    # 1. 날짜 파싱
    try:
        if len(start_str) == 10:
            start_str += " 00:00"
        if len(end_str) == 10:
            end_str += " 23:59"

        fmt = "%Y-%m-%d %H:%M"
        start_dt = datetime.strptime(start_str, fmt)
        end_dt = datetime.strptime(end_str, fmt)
    except ValueError:
        print("❌ 날짜 형식 오류. '2025-11-26 09:00' 형태로 입력하세요.")
        return

    # 2. CSV 읽기
    if not os.path.exists(LOG_FILE):
        print(
            f"❌ 로그 파일({LOG_FILE})이 아직 없습니다. 'start' 명령으로 수집을 먼저 해주세요."
        )
        return

    filtered_rows = []

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)

        for row in reader:
            if not row or len(row) < 3:
                continue
            try:
                row_dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                if start_dt <= row_dt <= end_dt:
                    filtered_rows.append(row)
            except ValueError:
                continue

    print(
        f"🔍 {start_str} ~ {end_str} 기간의 데이터 {len(filtered_rows)}개를 찾았습니다."
    )

    if not filtered_rows:
        print("❌ 전송할 데이터가 없습니다.")
        return

    # 3. 파일 생성
    export_csv = f"path_{start_dt.strftime('%Y%m%d')}.csv"
    export_kml = f"map_{start_dt.strftime('%Y%m%d')}.kml"

    # CSV 쓰기
    with open(export_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if header:
            writer.writerow(header)
        writer.writerows(filtered_rows)

    # KML 쓰기
    create_kml(filtered_rows, export_kml)

    # 4. 이메일 전송
    send_email_with_files([export_csv, export_kml], start_str, end_str)


# =========================
# 🚀 메인 실행부
# =========================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법:")
        print("  python gps_manager.py start")
        print("  python gps_manager.py stop")
        print("  python gps_manager.py send '시작시간' '종료시간'")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "start":
        start_logging()
    elif mode == "stop":
        stop_logging()
    elif mode == "send":
        if len(sys.argv) < 4:
            print("❌ 시간을 입력해주세요.")
            print(
                "예: python gps_manager.py send '2025-11-26 09:00' '2025-11-26 18:00'"
            )
        else:
            send_data(sys.argv[2], sys.argv[3])
    else:
        print(f"❌ 알 수 없는 명령어: {mode}")
