import os
import argparse
from datetime import datetime
from dotenv import load_dotenv  #api 키 불러오기
import requests
import json
import openai
from openai import OpenAI
from urllib.parse import quote
import sys
import traceback


load_dotenv(override=True)
API_KEY = os.getenv("API_KEY")
BASE_URL = "https://copa.codyssey.kr/v1"
MAP_KEY = os.getenv("KAKAO_API_KEY")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# 키가 없으면 즉시 종료 (요구사항!)
if not API_KEY or not MAP_KEY:
    print("❌ API 키가 없습니다. .env 파일에 OPENAI_API_KEY, KAKAO_API_KEY를 설정하세요.")
    sys.exit(1)

parser = argparse.ArgumentParser(description="국내 여행 추천 프로그램")
parser.add_argument("-date", required=True, help="여행 날짜 (YYYY-MM-DD)")
args = parser.parse_args()

# 날짜 형식 검증
try:
    datetime.strptime(args.date, "%Y-%m-%d") #형식이 다르면 실패->excep 처리
except ValueError:
    print("❌ 날짜 형식이 잘못되었습니다. 예: -date 2025-03-15")
    sys.exit(1)

date = args.date #date변수에 저장

def get_recommendation(date):
    prompt = f"""당신은 국내 여행 추천 전문가입니다.
입력 날짜: {date}
아래 JSON 형식으로만 답하세요. 다른 설명은 절대 하지 마세요.
{{
  "recommended_cities": ["도시1", "도시2", "도시3"],
  "weather": "해당 시기 일반적 날씨 요약",
  "events": ["행사1", "행사2"],
  "reason": "추천 이유 2~4문장"
}}"""

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    text = response.choices[0].message.content
    data = json.loads(text)  # 문자열 → 딕셔너리
    return data

def search_restaurants(city):
    base_url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {MAP_KEY}"}
    query = quote(f"{city} 맛집", encoding="utf-8")
    url = f"{base_url}?query={query}&size=5"

    with open("debug_kakao.txt", "w", encoding="utf-8") as f:
        f.write(f"MAP_KEY repr: {repr(MAP_KEY)}\n")
        f.write(f"Authorization: {repr(headers['Authorization'])}\n")
        f.write(f"URL: {repr(url)}\n")

    res = requests.get(url, headers=headers)
    res.raise_for_status()  # 401/403 등이면 예외 발생

    items = res.json()["documents"]

    restaurants = []
    for item in items:
        restaurants.append({
            "name": item["place_name"],
            "address": item["road_address_name"],
            "category": item["category_name"],
            "url": item["place_url"],
            "x": item["x"],
            "y": item["y"],
        })
    return restaurants

def generate_report(date, recommend_data, all_restaurants):
    # 도시별 맛집 텍스트 구성
    restaurant_text = ""
    for city, restaurants in all_restaurants.items():
        if restaurants:
            restaurant_text += f"\n[{city}]\n{json.dumps(restaurants, ensure_ascii=False)}\n"
        else:
            restaurant_text += f"\n[{city}]\n데이터 없음 (장소 검색 결과 0건)\n"

    prompt = f"""아래 정보로 여행 리포트를 Markdown으로 작성하세요.

날짜: {date}
추천 정보: {json.dumps(recommend_data, ensure_ascii=False)}
도시별 맛집 목록: {restaurant_text}

다음 항목을 반드시 포함하세요:
# {date} 국내 여행 추천 리포트
## 추천 지역
## 추천 이유
## 날씨 요약
## 행사/축제
## 도시별 맛집 추천 (도시마다 소제목, 0건이면 '데이터 없음'으로 표기)
## 1일 일정 제안 (오전/오후/저녁)
"""

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

errors = []
raw_path = f"results/{date}_raw.json"

# 이미 저장된 JSON이 있으면 API 호출 건너뜀
if os.path.exists(raw_path):
    print(f"  [캐시] {raw_path} 발견 → API 호출 건너뜀")
    with open(raw_path, "r", encoding="utf-8") as f:
        cached = json.load(f)
    recommend_data = cached["recommendation"]
    all_restaurants = cached["restaurants"]
    errors = cached.get("errors", [])

else:
    # 1) 여행지 추천 (파싱 실패 시 1회 재시도)
    try:
        recommend_data = get_recommendation(date)
    except openai.AuthenticationError:
        print("❌ API 키가 유효하지 않습니다. .env 파일의 API_KEY를 확인하세요.")
        sys.exit(1)
    except json.JSONDecodeError:
        print("⚠️ JSON 파싱 실패, 1회 재시도합니다.")
        try:
            recommend_data = get_recommendation(date)
        except Exception as e:
            errors.append({"step": "recommendation", "type": "PARSE_ERROR", "message": str(e)})
            sys.exit(1)

    print(f"  [1] recommended_cities: {recommend_data['recommended_cities']}")

    # 2) 맛집 검색 - 각 도시마다 반복 (실패해도 리포트는 계속!)
    all_restaurants = {}
    for city in recommend_data["recommended_cities"]:
        try:
            result = search_restaurants(city)
            all_restaurants[city] = result
            if len(result) == 0:
                errors.append({"step": "place_search", "type": "EMPTY_RESULT", "message": f"{city}: 0 results"})
        except requests.exceptions.HTTPError as e:
            errors.append({"step": "place_search", "type": "AUTH_ERROR", "message": f"{city}: {e}"})
            all_restaurants[city] = []
        except Exception as e:
            errors.append({"step": "place_search", "type": "NETWORK_ERROR", "message": f"{city}: {e}"})
            all_restaurants[city] = []

    print(f"  [2] 맛집을 검색하고 있습니다.")

# 리포트 생성
report_text = generate_report(date, recommend_data, all_restaurants)

print(f"  [3] 리포트를 생성하고 있습니다. ")

# 폴더 생성
os.makedirs("results", exist_ok=True)

# 1) 원본 JSON 저장
raw_data = {
    "recommendation": recommend_data,
    "restaurants": all_restaurants,
    "errors": errors
}
with open(f"results/{date}_raw.json", "w", encoding="utf-8") as f:
    json.dump(raw_data, f, ensure_ascii=False, indent=2)

# 2) 리포트 MD 저장
report_path = f"results/{date}_travel_plan.md"
with open(report_path, "w", encoding="utf-8") as f:
    f.write(report_text)

print(f"\n완료! {report_path} 를 확인하세요.")