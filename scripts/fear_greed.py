#!/usr/bin/env python3
"""US / Korea fear & greed data collector (Hermes cron pre-run script). Stdlib only.

Prints a compact, labeled data block for the agent:
  1. US  — CNN Fear & Greed: headline, CNN's own comparison points, daily trend, 7 components
  2. KR  — kospifgi.com (primary): score, trend, 8 components with raw values
  3. KR  — cross-checks: siglens.io (5 percentile factors) and feargreed.co.kr (realtime, 1-day based)
  4. Change since the last briefing (from a local state file, not from chat continuity)

Wake gate: if neither the US nor the primary KR reading changed since the last run (both markets
closed), prints {"wakeAgent": false} as the last line so cron skips the agent and delivery.
`--force` ignores the gate. `FG_STATE_DIR` overrides the state dir (use a scratch dir for tests).
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

KST = timezone(timedelta(hours=9))
ET = ZoneInfo("America/New_York")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
STATE_DIR = os.environ.get("FG_STATE_DIR", os.path.expanduser("~/.hermes/data/fear_greed"))
STATE_FILE = os.path.join(STATE_DIR, "state.json")

errors = []
RATING_KO = {"extreme fear": "극단적 공포", "fear": "공포", "neutral": "중립", "greed": "탐욕", "extreme greed": "극단적 탐욕",
             "extreme_fear": "극단적 공포", "extreme_greed": "극단적 탐욕"}


def ko(r):
    return RATING_KO.get(str(r).lower(), r)


def get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def safe(label, fn, default=None):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        errors.append(f"{label}: {type(e).__name__}: {e}")
        return default


def rsc_text(html):
    """Decode a Next.js app-router page's flight data (self.__next_f.push chunks) into one string."""
    out = []
    for c in re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S):
        try:
            out.append(json.loads('"' + c + '"'))
        except ValueError:
            continue
    return "".join(out)


def visible_text(html):
    import html as h
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", h.unescape(re.sub(r"<[^>]+>", " ", t))).strip()


def us_session(ts_utc: datetime) -> str:
    """US session a CNN reading belongs to: the ET date if computed after the 16:00 ET close, else the
    previous weekday (readings before the open still describe the last close)."""
    t = ts_utc.astimezone(ET)
    d = t.date()
    if t.hour < 16:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


# ---------------------------------------------------------------- US: CNN
CNN_COMPONENTS = [  # key, label, raw description
    ("market_momentum_sp500", "시장 모멘텀", "S&P500 vs 125일 이평"),
    ("stock_price_strength", "주가 강도", "NYSE 52주 신고가-신저가(%)"),
    ("stock_price_breadth", "주가 폭", "맥클렐런 거래량 합산"),
    ("put_call_options", "풋/콜", "5일 평균 풋/콜 비율"),
    ("market_volatility_vix", "변동성", "VIX vs 50일 이평"),
    ("junk_bond_demand", "정크본드 수요", "하이일드-투자등급 스프레드(%p)"),
    ("safe_haven_demand", "안전자산 수요", "주식-국채 20일 수익률 차(%p)"),
]


def cnn():
    d = json.loads(get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                       {"Accept": "application/json, text/plain, */*",
                        "Referer": "https://edition.cnn.com/", "Origin": "https://edition.cnn.com"}))
    fg = d["fear_and_greed"]
    ts = datetime.fromisoformat(fg["timestamp"])
    sess = us_session(ts)
    # one value per calendar day = the LAST point of that day (the series holds a carried-forward 00:00
    # point plus intraday/after-close recomputes); drop days after the session (today's placeholder)
    daily = {}
    for p in sorted(d["fear_and_greed_historical"]["data"], key=lambda p: p["x"]):
        day = datetime.fromtimestamp(p["x"] / 1000, timezone.utc).date().isoformat()
        if day <= sess:
            daily[day] = p["y"]

    def last_raw(key):
        v = d.get(key) or {}
        return v["data"][-1]["y"] if v.get("data") else None
    comps = []
    for key, label, desc in CNN_COMPONENTS:
        v = d.get(key)
        if not v:
            continue
        raw = last_raw(key)
        if key == "market_momentum_sp500":
            ma = last_raw("market_momentum_sp125")
            raw_s = f"S&P500 {raw:,.2f} / 125일선 {ma:,.2f}" if raw is not None and ma is not None else "n/a"
        elif key == "market_volatility_vix":
            ma = last_raw("market_volatility_vix_50")
            raw_s = f"VIX {raw:.2f} / 50일선 {ma:.2f}" if raw is not None and ma is not None else "n/a"
        else:
            raw_s = f"{raw:.3f}" if isinstance(raw, (int, float)) else "n/a"
        comps.append({"label": label, "desc": desc, "score": v["score"], "rating": v["rating"], "raw": raw_s})
    return {"score": fg["score"], "rating": fg["rating"], "ts": ts, "session": sess,
            "prev_close": fg["previous_close"], "w1": fg["previous_1_week"], "m1": fg["previous_1_month"],
            "y1": fg["previous_1_year"], "daily": daily, "comps": comps}


# ---------------------------------------------------------------- KR: kospifgi.com (primary)
KFGI_LABEL = {"momentum": ("시장 모멘텀", "KOSPI 종가 / 125일 평균"), "strength": ("주가 강도", "52주 신고가-신저가 비율 %"),
              "breadth": ("시장 폭", "맥클렐런 볼륨 합계지수"), "put_call": ("풋/콜", "풋/콜 5일 평균"),
              "volatility": ("변동성", "V-KOSPI / 50일 평균"), "safe_haven": ("안전자산 수요", "주식-국채 20일 수익률 차 %"),
              "junk_bond": ("정크본드 수요", "BBB- 3년 - 국고 3년 스프레드(음수)"), "fx": ("환율", "원/달러")}


def kospifgi():
    flight = rsc_text(get("https://www.kospifgi.com/"))
    line = next(ln for ln in flight.split("\n") if '"initialLatest"' in ln)
    props = json.loads(line.partition(":")[2])[3]
    latest = props["initialLatest"]
    hist = [(h["date"], h["fgi_score"]) for h in props.get("initialHistory", [])]
    comps = []
    for c in props.get("initialComponentCharts", []):
        pt = c["points"][-1] if c.get("points") else {}
        label, desc = KFGI_LABEL.get(c["key"], (c["key"], ""))
        raw = pt.get("value")
        base = pt.get("baseline")
        raw_s = f"{raw:,}" + (f" / {base:,}" if base is not None else "") if raw is not None else "n/a"
        comps.append({"label": label, "desc": desc, "score": c.get("latest_score"), "rating": c.get("latest_regime"),
                      "raw": raw_s, "date": pt.get("date")})
    ana = props.get("initialAnalysis") or {}
    return {"date": latest["date"], "score": latest["fgi_score"], "rating": latest["regime"], "hist": hist,
            "comps": comps, "view": ana.get("final_view"), "summary": (ana.get("summary") or "").split("\n")[0]}


# ---------------------------------------------------------------- KR cross-checks
def siglens():
    t = visible_text(get("https://siglens.io/fear-greed/kr"))
    m = re.search(r"(\d+) / 100 (\S+(?: \S+)?) 신뢰도 (\S+) ⓘ (\d{4})년 (\d{1,2})월 (\d{1,2})일 종가 기준", t)
    if not m:
        raise ValueError("score block not found (page layout changed?)")
    out = {"score": int(m.group(1)), "rating": m.group(2), "confidence": m.group(3),
           "date": date(int(m.group(4)), int(m.group(5)), int(m.group(6))).isoformat()}
    cmp_ = re.search(r"기간별 비교 (\d+) 현재 (\d+) 1주 전 (\d+) 1개월 전 (\d+) 1년 전", t)
    if cmp_:
        out.update(w1=int(cmp_.group(2)), m1=int(cmp_.group(3)), y1=int(cmp_.group(4)))
    out["factors"] = [(n, int(p)) for n, p in re.findall(
        r"(시장 모멘텀|시장 변동성|안전자산 선호|신용 스프레드 수요|시장 폭) [+-−]?[\d.]+% .*? 백분위 (\d+)", t.split("요인별 기여도", 1)[-1])[:5]]
    return out


def feargreed_kr():
    d = json.loads(get("https://feargree-api.vercel.app/api",
                       {"Referer": "https://feargreed.co.kr/", "Origin": "https://feargreed.co.kr"}))
    k = d["kr"]
    return {"score": k["score"], "label": k["label"], "ts": d.get("timestamp"), "kospi": k.get("kospi_price"),
            "kospi_chg": k.get("kospi_change"), "vkospi": k.get("vkospi"), "vkospi_src": k.get("vkospi_source"),
            "ind": [(i["name"], i["value"], i.get("raw"), i.get("unit", "")) for i in k.get("indicators", [])]}


# ---------------------------------------------------------------- state
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def fmt_delta(a, b):
    return "n/a" if a is None or b is None else f"{a - b:+.1f}"


def main():
    now = datetime.now(KST)
    force = "--force" in sys.argv
    us = safe("CNN", cnn)
    kf = safe("kospifgi", kospifgi)
    sg = safe("siglens", siglens)
    fk = safe("feargreed.co.kr", feargreed_kr)
    st = load_state()
    prev = st.get("last", {})

    us_new = bool(us) and us["session"] != prev.get("us_session")
    kr_new = bool(kf) and kf["date"] != prev.get("kr_date")
    if prev and not us_new and not kr_new and not force and (us or kf):
        print(f"미국({prev.get('us_session')})·한국({prev.get('kr_date')}) 모두 새 데이터 없음 — 브리핑 생략")
        print(json.dumps({"wakeAgent": False}))
        return

    def P(s=""):
        print(s, flush=True)
    P(f"# 공포탐욕 데이터 (수집 {now:%Y-%m-%d %H:%M} KST)")
    P("\n## 갱신 상태")
    P(f"- 미국 CNN: {'세션 ' + us['session'] + (' (신규)' if us_new else ' (직전 브리핑과 같은 세션 — 미국 휴장 등)') if us else '데이터 수집 실패'}")
    P(f"- 한국 kospifgi: {'기준일 ' + kf['date'] + (' (신규)' if kr_new else ' (직전 브리핑과 같은 기준일 — 한국 휴장 등)') if kf else '데이터 수집 실패'}")
    if sg:
        lag = f" — 주 소스보다 늦음(기준일 차이)" if kf and sg["date"] < kf["date"] else ""
        P(f"- 한국 siglens: {sg['date']} 종가 기준{lag}")
    else:
        P("- 한국 siglens: 데이터 수집 실패")
    P(f"- 한국 feargreed.co.kr: {'실시간 산출(' + fk['ts'] + ' UTC), KOSPI ' + str(fk['kospi']) + ' 반영' if fk else '데이터 수집 실패'}")

    # ------------------------------------------------ US
    P("\n## 1. 미국 CNN Fear & Greed")
    if us:
        P(f"- 현재 {us['score']:.1f} ({ko(us['rating'])}) — {us['session']} 미국 장 마감 반영, 산출 {us['ts'].astimezone(KST):%m-%d %H:%M} KST")
        P(f"- CNN 제공 비교값: 전일 종가 {us['prev_close']:.1f} ({fmt_delta(us['score'], us['prev_close'])}), "
          f"1주 전 {us['w1']:.1f} ({fmt_delta(us['score'], us['w1'])}), 1개월 전 {us['m1']:.1f} ({fmt_delta(us['score'], us['m1'])}), "
          f"1년 전 {us['y1']:.1f} ({fmt_delta(us['score'], us['y1'])})")
        days = sorted(us["daily"])[-10:]
        P("- 최근 10거래일(각 날짜 최종 산출값): " + ", ".join(f"{d[5:]} {us['daily'][d]:.1f}" for d in days))
        P("  ※ 일별 추이는 장 마감 후 재산출이 반영된 값이라 CNN '전일 종가' 값과 1~3p 다를 수 있음 — 정상, 불일치로 보고하지 말 것."
          " 전일 대비 변화는 CNN '전일 종가' 기준으로 말할 것")
        P("- 구성지표 (점수 0~100은 장기 분포 대비 백분위 / 원자료):")
        for c in us["comps"]:
            P(f"  - {c['label']}: {c['score']:.1f} ({ko(c['rating'])}) | {c['desc']}: {c['raw']}")
    else:
        P("- 데이터 수집 실패")

    # ------------------------------------------------ KR primary
    P("\n## 2. 한국 kospifgi.com (주 소스: 8개 지표, KRX·ECOS, 전일 종가 기준, 매 영업일 08:10 KST부터 갱신)")
    if kf:
        h = dict(kf["hist"])
        ds = sorted(h)
        prev_d = ds[-2] if len(ds) >= 2 and ds[-1] == kf["date"] else None
        P(f"- {kf['date']} 장 마감 기준 {kf['score']} ({ko(kf['rating'])})"
          + (f", 전 거래일({prev_d}) {h[prev_d]} 대비 {fmt_delta(kf['score'], h[prev_d])}" if prev_d else ""))
        P("- 최근 10거래일: " + ", ".join(f"{d[5:]} {h[d]}" for d in ds[-10:]))
        P("- 구성지표 (점수 / 원자료):")
        for c in kf["comps"]:
            sc = f"{c['score']:.1f}" if isinstance(c["score"], (int, float)) else "n/a"
            P(f"  - {c['label']}: {sc} ({ko(c['rating'])}) | {c['desc']}: {c['raw']}")
        if kf.get("summary"):
            P(f"- (사이트 자체 AI 해석, 참고용) 전망 {kf.get('view')}: {kf['summary'][:200]}")
    else:
        P("- 데이터 수집 실패")

    # ------------------------------------------------ KR cross-checks
    P("\n## 3. 한국 교차 확인 (산식이 달라 절대값 차이는 정상)")
    if sg:
        extra = f", 1주 전 {sg.get('w1')} / 1개월 전 {sg.get('m1')} / 1년 전 {sg.get('y1')}" if "w1" in sg else ""
        P(f"- siglens.io: {sg['score']} ({sg['rating']}), {sg['date']} 종가 기준, 신뢰도 {sg['confidence']}{extra}")
        P("  5요인 백분위(동일가중, ETF·지수 종가, 변동성=실현변동성): " + ", ".join(f"{n} {p}" for n, p in sg["factors"]))
        if kf and sg["date"] in dict(kf["hist"]):
            P(f"  같은 기준일({sg['date']}) 비교: kospifgi {dict(kf['hist'])[sg['date']]} vs siglens {sg['score']}")
    else:
        P("- siglens.io: 데이터 수집 실패")
    if fk:
        same = ""
        mom = next((c for c in (kf or {}).get("comps", []) if c["label"] == "시장 모멘텀"), None)
        try:
            kclose = float(mom["raw"].split(" / ")[0].replace(",", "")) if mom else None
            same = (f" = kospifgi와 같은 {kf['date']} 세션" if kclose is not None and abs(float(fk["kospi"]) - kclose) < 0.01
                    else f" ≠ kospifgi 기준일({kf['date']}) 종가 {kclose:,.2f} → 다른 세션이라 직접 비교 불가" if kclose else "")
        except (TypeError, ValueError):
            pass
        P(f"- feargreed.co.kr: {fk['score']} ({fk['label']}) — 실시간 6지표 가중평균, KOSPI {fk['kospi']} ({fk['kospi_chg']}%) 반영{same}")
        P("  지표: " + ", ".join(f"{n} {v}" + (f"(원자료 {r}{u})" if r is not None and n != '종합 심리' else "") for n, v, r, u in fk["ind"]))
        P(f"  ※ 사이트가 밝힌 가중치 중 65%가 하루 등락률 기반(모멘텀 25·주가강도 15·KOSPI추세 15·KOSDAQ 10)이라 하루 급등락에 크게 출렁임. "
          f"VKOSPI {fk['vkospi']}은 {'추정치(vkospi_source=estimated) — 실제 V-KOSPI 아님' if fk['vkospi_src'] == 'estimated' else '출처 ' + str(fk['vkospi_src'])}")
    else:
        P("- feargreed.co.kr: 데이터 수집 실패")

    # ------------------------------------------------ vs last briefing
    P("\n## 4. 직전 브리핑 대비 (로컬 상태 파일)")
    if prev:
        P(f"- 직전 브리핑 {prev.get('run_at', '')[:16]}: 미국 {prev.get('us_score')} ({prev.get('us_session')}) / "
          f"kospifgi {prev.get('kr_score')} ({prev.get('kr_date')}) / siglens {prev.get('sg_score')} ({prev.get('sg_date')})")
        P(f"- 변화: 미국 {fmt_delta(us and us['score'], prev.get('us_score'))}, kospifgi {fmt_delta(kf and kf['score'], prev.get('kr_score'))}")
    else:
        P("- 직전 기록 없음 (첫 실행)")

    if errors:
        P("\n## 수집 오류 (해당 소스는 '데이터 수집 실패'로 표기)")
        for e in errors:
            P(f"- {e}")

    if us or kf:
        cur = {"run_at": now.isoformat(timespec="minutes"),
               "us_session": us["session"] if us else prev.get("us_session"), "us_score": round(us["score"], 1) if us else prev.get("us_score"),
               "kr_date": kf["date"] if kf else prev.get("kr_date"), "kr_score": kf["score"] if kf else prev.get("kr_score"),
               "sg_date": sg["date"] if sg else prev.get("sg_date"), "sg_score": sg["score"] if sg else prev.get("sg_score")}
        st["last"] = cur
        save_state(st)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 — never let a parse bug kill the briefing silently
        import traceback
        print(f"!! 수집 스크립트 예외: {type(e).__name__}: {e}")
        traceback.print_exc(file=sys.stdout)
