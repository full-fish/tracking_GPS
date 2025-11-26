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
CONFIG_FILE = "config.ini"

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
            # CSV 순서: time, lat, lon, ...
            # KML 좌표 순서: lon, lat, alt
            f.write(f"{row[2]},{row[1]},0 \n")
        f.write(kml_footer)


def send_data(start_str, end_str):
    # 1. 날짜 파싱
    try:
        # 입력 형식 예: "2025-11-26 10:00"
        fmt = "%Y-%m-%d %H:%M"
        start_dt = datetime.strptime(start_str, fmt)
        end_dt = datetime.strptime(end_str, fmt)
    except ValueError:
        print("❌ 날짜 형식이 틀렸습니다. 'YYYY-MM-DD HH:MM' 형식으로 입력하세요.")
        return

    # 2. CSV 읽어서 필터링
    if not os.path.exists(LOG_FILE):
        print("❌ 저장된 로그 파일이 없습니다.")
        return

    filtered_rows = []

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)

        for row in reader:
            if not row:
                continue
            row_dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            # 시간 범위 확인
            if start_dt <= row_dt <= end_dt:
                filtered_rows.append(row)

    print(f"🔍 총 {len(filtered_rows)}개의 위치 데이터를 찾았습니다.")

    if not filtered_rows:
        print("❌ 해당 기간의 데이터가 없습니다.")
        return

    # 3. 파일 생성 (CSV 및 KML)
    export_csv = "export_path.csv"
    export_kml = "export_map.kml"

    # CSV 저장
    with open(export_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(filtered_rows)

    # KML 저장 (지도 보기용)
    create_kml(filtered_rows, export_kml)

    # 4. 이메일 전송
    send_email_with_files([export_csv, export_kml], start_str, end_str)


def send_email_with_files(files, start_t, end_t):
    # config.ini 읽기
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    # 네이버 섹션 찾기 (없으면 첫번째 섹션 사용)
    section = "NAVER" if "NAVER" in config else config.sections()[0]
    settings = config[section]

    msg = MIMEMultipart()
    msg["From"] = settings["sender_email"]
    msg["To"] = settings["recipient_email"]
    msg["Subject"] = f"🗺️ 이동 동선 데이터 ({start_t} ~ {end_t})"

    body = "요청하신 기간의 이동 경로 데이터입니다.\n\n- .csv: 엑셀에서 열기\n- .kml: 구글 어스 또는 '구글 내 지도'에 업로드하여 경로 확인 가능"
    msg.attach(MIMEText(body, "plain"))

    for filename in files:
        with open(filename, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={filename}")
        msg.attach(part)

    try:
        server = smtplib.SMTP(settings["smtp_server"], int(settings["smtp_port"]))
        server.starttls()
        server.login(settings["sender_email"], settings["app_password"])
        server.sendmail(
            settings["sender_email"], settings["recipient_email"], msg.as_string()
        )
        server.quit()
        print("📧 메일 전송 성공!")

        # 임시 파일 삭제
        for f in files:
            os.remove(f)

    except Exception as e:
        print(f"❌ 메일 전송 실패: {e}")


# =========================
# 🚀 메인 실행부
# =========================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법:")
        print("  python gps_manager.py start")
        print("  python gps_manager.py stop")
        print("  python gps_manager.py send '2025-11-26 09:00' '2025-11-26 18:00'")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "start":
        start_logging()
    elif mode == "stop":
        stop_logging()
    elif mode == "send":
        if len(sys.argv) < 4:
            print("❌ 시작 시간과 종료 시간을 입력해주세요.")
            print(
                "예: python gps_manager.py send '2025-11-26 09:00' '2025-11-26 18:00'"
            )
        else:
            send_data(sys.argv[2], sys.argv[3])
    else:
        print("❌ 알 수 없는 명령어입니다.")
