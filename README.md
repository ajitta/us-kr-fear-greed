# 미국·한국 공포탐욕지수 일일 브리핑 (Hermes Agent 스킬)

평일 08:30(KST)에 미국 CNN Fear & Greed와 한국 KOSPI 공포탐욕지수 3종을 모아 텔레그램 등으로 브리핑하는 스킬입니다.

리포트에 들어가는 내용:
- 미국 CNN 지수: 현재 점수, CNN이 제공하는 전일·1주·1개월·1년 비교값, 최근 10거래일 추이, 7개 구성지표(점수와 원자료)
- 한국 [kospifgi.com](https://www.kospifgi.com/) (주 소스): 점수, 추이, 8개 구성지표(점수와 원자료)
- 한국 교차 확인: [siglens.io](https://siglens.io/fear-greed/kr), [feargreed.co.kr](https://feargreed.co.kr/). 소스마다 기준일을 붙이고, 같은 날짜끼리만 비교
- 한미 구조 비교, 역발상 해석, 변곡 신호
- 직전 브리핑 대비 변화 (로컬 상태 파일 기준)

## 요구사항
- Hermes Agent. 메신저로 받으려면 gateway가 실행 중이어야 함
- python3 3.9 이상 (표준 라이브러리만 사용)

## 설치
```bash
git clone https://github.com/ajitta/us-kr-fear-greed.git && cd us-kr-fear-greed
bash scripts/install.sh                  # 스킬과 스크립트 설치 + 4개 소스 동작 확인
bash scripts/install.sh --cron telegram  # 평일 08:30 예약 작업까지 생성
```
- 업데이트: `git pull && bash scripts/install.sh`
- 데이터만 확인: `FG_STATE_DIR=$(mktemp -d) python3 ~/.hermes/scripts/fear_greed.py --force`
- 예약 시각은 Hermes 시간대를 따릅니다. `timezone: Asia/Seoul`을 권장하며, UTC 서버면 설치 스크립트가 23:30(일~목)으로 등록합니다.

## 구성
- `SKILL.md`: 작성 규칙, 소스, 주의사항
- `references/cron-prompt.md`: 예약 작업 프롬프트
- `scripts/fear_greed.py`: 데이터 수집
  - 미국·한국 둘 다 새 데이터가 없으면(양국 휴장) `{"wakeAgent": false}`를 출력해 그날 실행을 건너뜀
  - 직전 브리핑 값은 `~/.hermes/data/fear_greed/state.json`에 저장 (`FG_STATE_DIR`로 변경 가능)

## 유의사항
- 한국에는 공식 공포탐욕지수가 없습니다. 사이트마다 산식이 달라 같은 날에도 수십 점 차이가 날 수 있습니다.
  - feargreed.co.kr은 가중치의 65%가 하루 등락률 기반이라 급등락일에 크게 움직입니다. VKOSPI가 추정치로 표시될 수 있습니다.
- 데이터는 각 사이트의 공개 페이지·API에서 가져옵니다. 공식 API가 아니어서 사이트가 바뀌면 깨질 수 있습니다. 상업적으로 쓰기 전에 각 사 약관을 확인하세요.
- 투자 판단 참고용이며 투자 권유가 아닙니다.

## 라이선스
MIT
