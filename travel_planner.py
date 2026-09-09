# ===== 1. Imports =====
import os, sys, json, argparse, requests, openai
from datetime import datetime
from dotenv import load_dotenv
from abc import ABC, abstractmethod
from urllib.parse import quote
from openai import OpenAI

# ===== 2. 환경변수 & 상수 =====
load_dotenv(override=True)
API_KEY = os.getenv("API_KEY")
BASE_URL = "https://copa.codyssey.kr/v1"
MAP_KEY = os.getenv("KAKAO_API_KEY")

CITY_ALIASES = {          # ⭐ 정의 추가!
    "서울시": "서울",
    "부산광역시": "부산",
    # 필요한 만큼 추가
}

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# ===== 3. 클래스 =====
class MapProvider(ABC):
    @abstractmethod
    def search_restaurants(self, city: str) -> list:
        pass

class KakaoMapProvider(MapProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    
    def search_restaurants(self, city: str) -> list:
        headers = {"Authorization": f"KakaoAK {self.api_key}"}
        query = quote(f"{city} 맛집", encoding="utf-8")
        url = f"{self.base_url}?query={query}&size=5"
        
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        items = res.json()["documents"]
        
        return [{
            "name": item["place_name"],
            "address": item["road_address_name"],
            "category": item["category_name"],
            "url": item["place_url"],
            "x": item["x"],
            "y": item["y"],
        } for item in items]

# ===== 4. 함수들 =====
def normalize_city(city):
    city = city.strip()
    return CITY_ALIASES.get(city, city)

def validate_recommendation(data):
    required_keys = ["recommended_cities", "weather", "events", "reason"]
    for key in required_keys:
        if key not in data:
            raise ValueError(f"필수 키 누락: '{key}'")
    if not isinstance(data["recommended_cities"], list):
        raise TypeError("'recommended_cities'는 리스트여야 합니다")
    if len(data["recommended_cities"]) == 0:
        raise ValueError("추천 도시가 비어있습니다")
    return True

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
    data = json.loads(text)
    validate_recommendation(data)
    return data

def generate_report(date, recommend_data, all_restaurants, errors):
    restaurant_text = ""
    for city, restaurants in all_restaurants.items():
        if restaurants:
            restaurant_text += f"\n[{city}]\n{json.dumps(restaurants, ensure_ascii=False)}\n"
        else:
            restaurant_text += f"\n[{city}]\n데이터 없음\n"
    
    prompt = f"""아래 정보로 여행 리포트를 Markdown으로 작성하세요.
날짜: {date}
추천 정보: {json.dumps(recommend_data, ensure_ascii=False)}
도시별 맛집: {restaurant_text}
발생한 오류: {errors}

# {date} 국내 여행 추천 리포트
## 추천 지역
## 추천 이유
## 날씨 요약
## 행사/축제
## 도시별 맛집 추천
## 1일 일정 제안
## ⚠️ 처리 중 알림사항 (errors 없으면 '정상 처리됨')
"""
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

# ===== 5. main =====
def main():
    # 5-1. 키 검증
    if not API_KEY or not MAP_KEY:
        print("❌ API 키가 없습니다.")
        sys.exit(1)
    
    # 5-2. argparse
    parser = argparse.ArgumentParser(description="국내 여행 추천 프로그램")
    parser.add_argument("-date", required=True, help="여행 날짜 (YYYY-MM-DD)")
    args = parser.parse_args()
    
    # 5-3. 날짜 검증
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print("❌ 날짜 형식이 잘못되었습니다. 예: -date 2025-03-15")
        sys.exit(1)
    
    date = args.date
    errors = []
    raw_path = f"results/{date}_raw.json"
    
    # 5-4. 캐싱 확인
    if os.path.exists(raw_path):
        print(f"  [캐시 사용] {raw_path}")
        with open(raw_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        recommend_data = cached["recommendation"]
        all_restaurants = cached["restaurants"]
        errors = cached.get("errors", [])
    else:
        # 5-5. 여행지 추천 (재시도 1회)
        recommend_data = None
        for attempt in range(2):   # 최대 2번 시도
            try:
                recommend_data = get_recommendation(date)
                break   # 성공하면 탈출
            except openai.AuthenticationError:
                print("❌ API 키가 유효하지 않습니다.")
                sys.exit(1)
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                if attempt == 0:
                    print(f"⚠️ {e} → 1회 재시도")
                else:
                    print(f"❌ 재시도 실패: {e}")
                    errors.append({"step": "recommendation", "type": "PARSE_ERROR", "message": str(e)})
                    sys.exit(1)

        print(f"  [1] 추천 도시: {recommend_data['recommended_cities']}")
        
        # 5-6. 맛집 검색 (도시별 반복)
        map_provider = KakaoMapProvider(MAP_KEY)
        all_restaurants = {}
        
        for city in recommend_data["recommended_cities"]:
            normalized = normalize_city(city)        # ⭐ 정규화 사용!
            try:
                result = map_provider.search_restaurants(normalized)
                all_restaurants[city] = result
                if len(result) == 0:
                    errors.append({"step": "place_search", "type": "EMPTY_RESULT", "message": f"{city}: 0건"})
            except requests.exceptions.HTTPError as e:
                errors.append({"step": "place_search", "type": "AUTH_ERROR", "message": f"{city}: {e}"})
                all_restaurants[city] = []
            except Exception as e:
                errors.append({"step": "place_search", "type": "NETWORK_ERROR", "message": f"{city}: {e}"})
                all_restaurants[city] = []
        
        print(f"  [2] 맛집 검색 완료")
    
    # 5-7. 리포트 생성
    report_text = generate_report(date, recommend_data, all_restaurants, errors)
    print(f"  [3] 리포트 생성 완료")
    
    # 5-8. 저장
    os.makedirs("results", exist_ok=True)
    
    raw_data = {
        "recommendation": recommend_data,
        "restaurants": all_restaurants,
        "errors": errors
    }
    with open(f"results/{date}_raw.json", "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)
    
    report_path = f"results/{date}_travel_plan.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    
    print(f"\n✅ 완료! {report_path}")

# ===== 6. 실행 =====
if __name__ == "__main__":
    main()