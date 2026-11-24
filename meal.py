"""율량중학교 급식 알림 - 나이스(NEIS) API에서 오늘 급식을 가져와 텔레그램으로 보냅니다.

사용법
  python meal.py                      # 지금 시각(한국)에 맞춰 아침/점심 문구로 발송
  python meal.py --mode morning       # 아침 문구로 발송
  python meal.py --mode lunch         # 점심 문구로 발송
  python meal.py --date 20261124      # 특정 날짜 메뉴 확인 (테스트용)

텔레그램 설정(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)이 없으면 화면에만 출력합니다.
표준 라이브러리만 사용하므로 따로 설치할 것이 없습니다.
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
NEIS = "https://open.neis.go.kr/hub/"

SCHOOL_NAME = os.environ.get("SCHOOL_NAME", "율량중학교")
EDU_CODE = os.environ.get("EDU_CODE", "M10")  # M10 = 충청북도교육청
SCHOOL_CODE = os.environ.get("SCHOOL_CODE", "")  # 비워 두면 학교 이름으로 자동 조회
SHOW_ALLERGY = os.environ.get("SHOW_ALLERGY", "0") == "1"  # 1이면 알레르기 번호 표시
NOTIFY_NO_MEAL = os.environ.get("NOTIFY_NO_MEAL", "0") == "1"  # 1이면 급식 없는 날도 알림


def neis(endpoint, **params):
    """나이스 API 호출. 데이터가 없으면 빈 목록을 돌려줍니다."""
    params.update(Type="json", pIndex=1, pSize=100, KEY=os.environ["NEIS_KEY"])
    url = NEIS + endpoint + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=20) as res:
        data = json.load(res)
    result = data.get("RESULT")
    if result and result.get("CODE") == "INFO-200":  # 해당 데이터 없음
        return []
    if result and result.get("CODE") != "INFO-000":
        raise RuntimeError(f"나이스 API 오류: {result.get('CODE')} {result.get('MESSAGE')}")
    for part in data.get(endpoint, []):
        if "row" in part:
            return part["row"]
    return []


def find_school_code():
    if SCHOOL_CODE:
        return SCHOOL_CODE
    rows = neis("schoolInfo", ATPT_OFCDC_SC_CODE=EDU_CODE, SCHUL_NM=SCHOOL_NAME)
    for row in rows:
        if row["SCHUL_NM"] == SCHOOL_NAME:
            return row["SD_SCHUL_CODE"]
    raise RuntimeError(f"학교를 찾지 못했어요: {SCHOOL_NAME} (교육청 코드 {EDU_CODE})")


def clean_dish(text):
    text = text.strip()
    if not SHOW_ALLERGY:
        text = re.sub(r"\s*\([\d.\s]+\)", "", text)  # (5.6.9) 같은 알레르기 번호 제거
    return text.strip()


def get_meals(date):
    """{'중식': {'dishes': [...], 'kcal': '672.5 Kcal'}} 형태로 돌려줍니다."""
    rows = neis(
        "mealServiceDietInfo",
        ATPT_OFCDC_SC_CODE=EDU_CODE,
        SD_SCHUL_CODE=find_school_code(),
        MLSV_YMD=date.strftime("%Y%m%d"),
    )
    meals = {}
    for row in rows:
        dishes = [clean_dish(d) for d in row["DDISH_NM"].split("<br/>") if d.strip()]
        meals[row["MMEAL_SC_NM"]] = {"dishes": dishes, "kcal": row.get("CAL_INFO", "")}
    return meals


def build_message(date, meals, mode):
    weekday = "월화수목금토일"[date.weekday()]
    if mode == "lunch":
        head = f"⏰ 곧 점심시간이에요! 오늘({date.month}/{date.day} {weekday}) 급식"
    else:
        head = f"🍚 오늘({date.month}/{date.day} {weekday}) 급식"
    lines = [head]
    for name, info in meals.items():
        lines.append(f"\n[{name}]" + (f"  {info['kcal']}" if info["kcal"] else ""))
        lines += [f"• {d}" for d in info["dishes"]]
    return "\n".join(lines)


def send(text):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(text)
        print("\n(텔레그램 설정이 없어 화면에만 출력했어요)")
        return
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=20) as res:
        res.read()
    print("텔레그램으로 보냈어요.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["morning", "lunch"], default=os.environ.get("MODE") or None)
    parser.add_argument("--date", help="YYYYMMDD (테스트용)")
    args = parser.parse_args()

    now = datetime.now(KST)
    date = datetime.strptime(args.date, "%Y%m%d").replace(tzinfo=KST) if args.date else now
    mode = args.mode or ("morning" if now.hour < 10 else "lunch")

    meals = get_meals(date)
    if not meals:
        print(f"{date:%Y-%m-%d} 급식 정보가 없어요 (주말, 방학, 휴업일일 수 있어요).")
        if NOTIFY_NO_MEAL:
            send(f"오늘({date.month}/{date.day})은 급식 정보가 없어요.")
        return
    send(build_message(date, meals, mode))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)
