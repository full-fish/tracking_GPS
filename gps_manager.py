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
# ⚙️ 절대 경로 설정 (Tasker 오류 방지)
# =========================
BASE_DIR = "/data/data/com.termux/files/home/dev/tracking_GPS"
LOGGER_SCRIPT = os.path.join(BASE_DIR, "gps_logger.py")
LOG_FILE = os.path.join(BASE_DIR, "gps_log.csv")
CONFIG_FILE = os.path.join(BASE_DIR, "config.ini")

# =========================
# 🛠️ 기능 함수들
# =========================


def start_logging():
    # 이미 실행 중인지 확인
    try:
        # pgrep에서 스크립트 이름만으로 검색
        pid = subprocess.check_output(["pgrep", "-f", "gps_logger.py"]).strip()
        print(f"⚠️ 이미 실행 중입니다! (PID: {pid.decode()})")
    except subprocess.CalledProcessError:
        # 백그라운드 실행 (절대 경로 사용)
        # 로그가 꼬이지 않도록 /dev/null로 보내거나 별도 로그 파일 지정 가능
        cmd = f"nohup python {LOGGER_SCRIPT} > /dev/null 2>&1 &"
        os.system(cmd)
        print(f"✅ GPS 수집을 시작했습니다. (백그라운드)")
        print(f"📂 저장 위치: {LOG_FILE}")


def stop_logging():
    try:
        pid = subprocess.check_output(["pgrep", "-f", "gps_logger.py"]).strip()
        os.system(f"kill {pid.decode()}")
        subprocess.run(["termux-wake-unlock"])
        print("🛑 GPS 수집을 종료했습니다.")
    except subprocess.CalledProcessError:
        print("⚠️ 실행 중인 GPS 수집기가 없습니다.")


def create_kml(data_rows, output_file):
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
            # CSV: time, lat, lon, acc, prov
            # KML: lon, lat, alt
            if len(row) >= 3:
                f.write(f"{row[2]},{row[1]},0 \n")
        f.write(kml_footer)


def send_email_with_files(files, start_t, end_t):
    config = configparser.ConfigParser()

    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
    else:
        print(f"❌ config.ini 파일을 찾을 수 없습니다.\n({CONFIG_FILE})")
        return

    if not config.sections():
        print("❌ 설정 파일에 계정 정보가 없습니다.")
        return

    email_sent_flag = False

    for section in config.sections():
        print(f"\n📨 [{section}] 계정으로 전송 시도 중...")
        try:
            settings = config[section]
            SMTP_SERVER = settings.get("smtp_server")
            SMTP_PORT = settings.get("smtp_port")
            SENDER_EMAIL = settings.get("sender_email")
            APP_PASSWORD = settings.get("app_password")
            RECIPIENT_EMAIL = settings.get("recipient_email")

            if not all(
                [SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, APP_PASSWORD, RECIPIENT_EMAIL]
            ):
                print(f"  ⚠️ [{section}] 정보 부족. 패스.")
                continue

            msg = MIMEMultipart()
            msg["From"] = SENDER_EMAIL
            msg["To"] = RECIPIENT_EMAIL
            msg["Subject"] = f"🗺️ 이동 동선 데이터 ({start_t} ~ {end_t})"

            body = (
                f"요청하신 기간의 이동 경로 데이터입니다.\n"
                f"- 기간: {start_t} ~ {end_t}\n\n"
                f"첨부파일:\n1. .csv (엑셀)\n2. .kml (지도)"
            )
            msg.attach(MIMEText(body, "plain"))

            for filename in files:
                if os.path.exists(filename):
                    with open(filename, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={os.path.basename(filename)}",
                    )
                    msg.attach(part)

            server = smtplib.SMTP(SMTP_SERVER, int(SMTP_PORT))
            server.starttls()
            server.login(SENDER_EMAIL, APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
            server.quit()

            print(f"  ✅ [{section}] 메일 전송 성공!")
            email_sent_flag = True
            break

        except Exception as e:
            print(f"  ❌ [{section}] 전송 실패: {e}")
            continue

    # 전송 후 임시 파일 삭제
    for f in files:
        if os.path.exists(f):
            os.remove(f)

    if not email_sent_flag:
        print("\n❌ 모든 계정 전송 실패.")


def send_data(start_str, end_str):
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

    if not os.path.exists(LOG_FILE):
        print(f"❌ 로그 파일({LOG_FILE})이 없습니다.")
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

    print(f"🔍 {len(filtered_rows)}개의 데이터 발견.")

    if not filtered_rows:
        print("❌ 전송할 데이터가 없습니다.")
        return

    # 임시 파일 생성 (절대 경로 사용)
    export_csv = os.path.join(BASE_DIR, f"path_{start_dt.strftime('%Y%m%d')}.csv")
    export_kml = os.path.join(BASE_DIR, f"map_{start_dt.strftime('%Y%m%d')}.kml")

    with open(export_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if header:
            writer.writerow(header)
        writer.writerows(filtered_rows)

    create_kml(filtered_rows, export_kml)
    send_email_with_files([export_csv, export_kml], start_str, end_str)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python gps_manager.py [start|stop|send '시작' '종료']")
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "start":
        start_logging()
    elif mode == "stop":
        stop_logging()
    elif mode == "send":
        if len(sys.argv) < 4:
            print("❌ 시간을 입력해주세요.")
        else:
            send_data(sys.argv[2], sys.argv[3])
    else:
        print(f"❌ 알 수 없는 명령어: {mode}")
