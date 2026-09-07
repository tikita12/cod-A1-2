# 🧳 API 활용 국내 여행지 추천 프로그램

## STEP 0. 사전 준비

- 사용할 LLM API : OpenAI
- 사용할 지도 API : Kakao Local
- Python 버전 확인: Python 3.14.7
- 설치한 라이브러리 목록:  
      openai 3.7.0  
      requests 2.31.0  
      python-dotenv 1.0.0  
      urllib3 2.7.0  

## STEP 1. 프로젝트 구조 만들기

### 
```
travel_planner/
├── travel_planner.py   # 메인 실행 파일
├── .env                # gpt key, base url, kakao api key
├── .gitignore          #  .env :환경변수 파일 = 비밀 정보 보관소
├── README.md
├── results/            # 결과 저장 폴더
└── requirements.txt
```

## STEP 2. 환경변수(API 키) 관리

### 
1. `.env` 파일 내용 작성:
```
API_KEY=sk********
KAKAO_API_KEY=24****
```

2. 코드에서 키 불러오기:
```
from dotenv import load_dotenv
import os

load_dotenv()
API_KEY = os.getenv("API_KEY")  
MAP_KEY = os.getenv("KAKAO_API_KEY")  

# ✍️ 키가 없으면?
if not llm_key:
    print("❌ API 키가 없습니다. .env 파일에 OPENAI_API_KEY, KAKAO_API_KEY를 설정하세요.")  # 안내 메시지
    sys.exit(1)` # 즉시 종료

```

## STEP 3. CLI 인터페이스 (argparse)

### 
```
import argparse # 터미널에서 프로그램 실행 시 입력한 인자를 받아서 처리해주는 파이썬 내장 라이브러리
from datetime import datetime

parser = argparse.ArgumentParser()
parser.add_argument("-date" #-date 값으로 입력, required=True #필수값, help="여행 날짜 (YYYY-MM-DD)" #help — python travel_planner.py --help 실행 시 보여줄 설명) 
args = parser.parse_args()

# ✍️ 날짜 형식 검증 (YYYY-MM-DD)
try:
    datetime.strptime(args.date, "%Y-%m-%d")  # ✍️ 형식 문자열
except ValueError:
    print(""❌ 날짜 형식이 잘못되었습니다. 예: -date 2025-03-15"")  # 사용법 안내
    sys.exit(1)   # 종료 처리
```

## STEP 4. LLM API 연동 ① - 여행지 추천 (1차 JSON)

### ✍️ 내가 채울 부분
1. 프롬프트 설계 (반드시 JSON만 출력하도록!):
```
당신은 여행 추천 전문가입니다.
입력 날짜: {date}
아래 JSON 형식으로만 답하세요.
{
  "recommended_city": "____",
  "weather": "____",
  "events": ["____"],
  "reason": "____"
}
```

2. LLM 호출 함수:
```
def get_recommendation(date):
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": prompt}]
    )  # ✍️ LLM API 호출 코드, 사용모델 : gpt-5-mini, 역할: 사용자, 내용:prompt
    data = json.loads(text)  # ✍️ 응답 텍스트를 JSON으로 파싱
    return data
```

### 
- 파싱 : 문자열을 프로그램이 다룰 수 있는 데이터 구조로 변환
- 파싱 실패 대비는 STEP 7에서 처리

---

## STEP 5. 지도 API 연동 - 맛집 검색

### 
```
def search_restaurants(city):
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {MAP_KEY}"}  # ✍️ 키
    params = {"query": f"{city} 맛집"}  # ✍️ 검색 키워드

    res = requests.get(url, headers=headers, params=params)
    items = res.json()["documents"]  #res.json() :응답을 json문자열에서 파이썬 딕셔너리로 변환
                                     #["documents"]: 딕셔너리에서  "documents"의 키 값만 꺼냄

    
    restaurants = [] # ✍️ 필요한 필드만 추출 (name, address, category, url, x, y)
    for item in items[:5]:
        restaurants.append({
            "name": item["place_name"],
            "address": item["road_address_name"],
            # ...
        })
    return restaurants
```

## STEP 6. LLM API 연동 ② - 최종 리포트 생성

### 
```
def generate_report(recommend_data, restaurants): # ✍️ LLM 호출 후 마크다운 텍스트 반환
    prompt = f"""
    아래 정보로 여행 리포트를 Markdown으로 작성하세요.
    날짜: {date}
    추천 정보: {recommend_data}
    맛집 목록: {restaurants}

    다음 항목을 반드시 포함하세요:
    # {date} 국내 여행 추천 리포트
    ## 추천 지역
    ## 추천 이유
    ## 날씨 요약
    ## 행사/축제
    ## 맛집 추천 (0건이면 '데이터 없음'으로 표기)
    ## 1일 일정 제안 (오전/오후/저녁)
    """
```
---

## STEP 7. 에러 처리

### ✍️ 내가 채울 부분 (오류 목록 관리)
```
errors = []  # 오류를 여기에 모음

# 맛집 검색 실패 예시
try:
    restaurants = search_restaurants(recommend_data["recommended_city"])
    if len(restaurants) == 0:
        errors.append({"step": "place_search", "type": "EMPTY_RESULT", "message": "0 results"})
except requests.exceptions.HTTPError as e:
    errors.append({"step": "place_search", "type": "AUTH_ERROR", "message": str(e)})
    restaurants = []  # 빈 리스트로 계속 진행!

# LLM JSON 파싱 실패 → 재시도 1회
except json.JSONDecodeError:
    print("⚠️ JSON 파싱 실패, 1회 재시도합니다.")
    try:
        recommend_data = get_recommendation(date)  # 재시도 1회만!
    ________
```
---

## STEP 8. 결과 저장

### 
```
import os, json

os.makedirs("results", exist_ok=True)  # 폴더 없으면 생성

# 1) 원본 JSON 저장
raw_data = {
    "recommendation": recommend_data,
    "restaurants": restaurants,
    "errors": errors
}
with open(f"results/{date}_raw.json", "w", encoding="utf-8") as f:
    json.dump(raw_data, f, ensure_ascii=False, indent=2)

# 2) 리포트 md 저장
with open(f"results/{date}_travel_pla.md", "w", encoding="utf-8") as f:
    f.write(report_text)
```

---

## STEP 9. README.md 작성

- 프로그램 개요
      특정날짜 입력 시, llm으로 검색하고 kakao map의 맛집을 검색하여 여행 report작성
- 실행 방법
      `python travel_planner.py --date "yyyy-mm-dd"`
- API 키 설정 방법
      .env에 API_KEY 저장,
      .gittgnore에 .env 추가(API 키 유출 방지)
- 결과물 확인 방법
       results/ 폴더 안에 자동 저장

---

## STEP 10. 최종 점검 체크리스트

- `-date` 없이 실행하면 에러 안내가 나오는가?
- API 키 없을 때 안내 후 종료되는가?
- 맛집 0건이어도 리포트가 생성되는가?
- `results/`에 JSON + MD 파일이 생성되는가?
- 키가 제출물 어디에도 노출되지 않는가?

---

## 🎯 (보너스) 도전 과제
-복수 지역 추천 (recommended_cities: 2~3개)  
for 구문이 없으면  
search_restaurants("부산")  
search_restaurants("경주")  
search_restaurants("전주") 각각 이렇게 작성해야하지만  

for 루프를 쓰면:  
for city in ["부산", "경주", "전주"]:  
    search_restaurants(city)  
city 자리에 "부산" → "경주" → "전주" 순서로 자동으로 바뀌면서 3번 실행됨  

  
-캐싱: 같은 날짜 재실행 시 API 호출 건너뛰기  

---

## 📝 학습 정리 (과제 목표 자가 점검)

1. REST API의 GET/POST 차이는?
> GET — 데이터를 가져올 때. URL에 정보를 담아서 요청
``` 
    res = requests.get(url, headers=headers)
```
    #url : 주소, headers : 보내는 사람, 우편 종류, body : 편지 내용
    #base url("https://dapi.kakao.com/v2/local/search/keyword.json")뒤에 ?로 파라미터를 붙임  

>POST — 데이터를 보낼 때. 본문(body)에 정보를 담아서 요청  
``` 
   response = client.chat.completions.create(  
        model="gpt-5-mini",  
        messages=[{"role": "user", "content": prompt}]  
    )
```
    
| 항목 | GET | POST |
|------|-----|------|
| 목적 | 조회 | 전송 |
| 데이터 위치 | URL | 본문 |
| 예시 | 검색, 조회 | 로그인, AI 프롬프트 |

2. LLM 출력을 JSON으로 구조화하는 이유는? → 원하는 값만 꺼낼 수 있음(도시, 날씨...)  
    - 다음 단계로 넘기기 쉬움(도시이름을 바로 꺼내서 맛집 검색에 사용)  
    - 형식이 일정  
    - 즉, AI답변을 코드가 쓸 수 있는 데이터로 만들기 위해  

3. 외부 API 호출 시 대표 오류(인증/쿼터/네트워크/파싱)와 대응은?
   
-인증 오류 (Authentication)
        API 키가 없거나 틀렸을 때  
        401 Unauthorized  → 키 자체가 잘못됨  
        403 Forbidden     → 키는 맞는데 권한 없음 (서비스 미활성화 등)  
        대응: sys.exit(1) 또는 안내 메시지 출력 후 종료  

-쿼터 오류 (Quota)
        사용량 한도 초과  
        429 Too Many Requests → 단시간 요청 너무 많음  
                              → 월 사용량 초과  
        대응: 잠시 기다렸다가 재시도, 유료 플랜 업그레이드  

-네트워크 오류 (Network)  
        서버에 연결 자체가 안 될 때  
        ConnectionError   → 인터넷 끊김  
        Timeout           → 응답이 너무 느림  
        500 Server Error  → 외부 서버 문제  
        대응: 재시도, 빈 리스트로 계속 진행  

-파싱 오류 (Parsing)  
        응답은 왔는데 형식이 틀렸을 때  
        // AI가 JSON 대신 이렇게 답하면  
        "부산을 추천합니다! {\"city\": ..."  ← json.loads() 실패  
        대응: 이 코드에서는 1회 재시도 후 sys.exit(1)  

4. API 키를 .env로 관리하는 이유는?  
   → api key 노출 방지, 개발/운영 환경마다 다른 키를 쓸 때 코드는 그대로 두고 .env만 바꿔서 쓸 수 있게
