"""Create a Korean study-strategy infographic from analysis CSV outputs."""

from __future__ import annotations

import csv
import html
import textwrap
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs"
FONT_REGULAR = Path(r"C:\Windows\Fonts\malgun.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\malgunbd.ttf")


PALETTE = {
    "paper": "#F7F5EF",
    "ink": "#1F2933",
    "muted": "#5B6570",
    "line": "#D8D2C3",
    "navy": "#203A5F",
    "teal": "#187C79",
    "orange": "#D66A2C",
    "red": "#B84444",
    "green": "#4F7D3B",
    "gold": "#B78B20",
    "white": "#FFFFFF",
    "soft_blue": "#EAF1F5",
    "soft_teal": "#E8F3F1",
    "soft_orange": "#F9EDE3",
    "soft_red": "#F7E6E3",
}


def read_csv(name: str) -> list[dict]:
    with (OUTPUT_DIR / name).open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size=size)


def text_width(draw: ImageDraw.ImageDraw, value: str, text_font: ImageFont.FreeTypeFont) -> int:
    if not value:
        return 0
    return int(draw.textbbox((0, 0), value, font=text_font)[2])


def wrap_by_width(draw: ImageDraw.ImageDraw, value: str, text_font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in str(value).split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if text_width(draw, candidate, text_font) <= max_width:
                current = candidate
            else:
                if text_width(draw, current, text_font) > max_width:
                    lines.extend(split_long_word(draw, current, text_font, max_width))
                else:
                    lines.append(current)
                current = word
        if text_width(draw, current, text_font) > max_width:
            lines.extend(split_long_word(draw, current, text_font, max_width))
        else:
            lines.append(current)
    return lines


def split_long_word(draw: ImageDraw.ImageDraw, value: str, text_font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines = []
    current = ""
    for char in value:
        candidate = current + char
        if current and text_width(draw, candidate, text_font) > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    text_font: ImageFont.FreeTypeFont,
    fill: str,
    max_width: int | None = None,
    line_gap: int = 6,
) -> int:
    x, y = xy
    lines = [value] if max_width is None else wrap_by_width(draw, value, text_font, max_width)
    for line in lines:
        draw.text((x, y), line, font=text_font, fill=fill)
        y += text_font.size + line_gap
    return y


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str | None = None, width: int = 2, radius: int = 22) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def pill(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, label: str, label_font: ImageFont.FreeTypeFont, text_fill: str) -> None:
    rounded(draw, box, fill=fill, radius=(box[3] - box[1]) // 2)
    w = text_width(draw, label, label_font)
    y = box[1] + ((box[3] - box[1]) - label_font.size) // 2 - 3
    draw.text((box[0] + ((box[2] - box[0]) - w) // 2, y), label, font=label_font, fill=text_fill)


def build_data() -> dict:
    questions = read_csv("02_questions_master.csv")
    priority = read_csv("05_recent_weighted_priority.csv")
    distribution = read_csv("03_topic_distribution.csv")

    by_topic_l1 = Counter()
    for row in questions:
        if row["topic_l1"] != "unknown":
            by_topic_l1[row["topic_l1"]] += 1

    return {
        "question_count": len(questions),
        "group_count": len({row["question_id"].split("-")[0] for row in questions}),
        "classified_count": sum(1 for row in questions if row["topic_l1"] != "unknown"),
        "review_count": sum(1 for row in questions if row["needs_human_review"] == "true"),
        "top_priority": priority[:10],
        "topic_counts": by_topic_l1.most_common(8),
        "distribution": distribution,
    }


def create_png(data: dict, out_path: Path) -> None:
    width, height = 1600, 2200
    image = Image.new("RGB", (width, height), PALETTE["paper"])
    draw = ImageDraw.Draw(image)

    f_title = font(74, True)
    f_sub = font(30)
    f_h = font(34, True)
    f_body = font(24)
    f_body_b = font(24, True)
    f_small = font(20)
    f_metric = font(54, True)
    f_rank = font(25, True)

    margin = 78
    draw.text((margin, 74), "해사영어 고득점 합격 전략", font=f_title, fill=PALETTE["ink"])
    draw.text((margin, 158), "기출 600문항 · 30개 시험 세트 · 최근 3개년 가중분석 기반", font=f_sub, fill=PALETTE["muted"])
    pill(draw, (1180, 84, 1508, 142), PALETTE["navy"], "빈도 50 · 최근 30 · 위험 20", font(22, True), PALETTE["white"])

    metrics = [
        ("600", "문항 분석", PALETTE["navy"], PALETTE["soft_blue"]),
        ("30", "시험 세트", PALETTE["teal"], PALETTE["soft_teal"]),
        ("522", "자동 분류", PALETTE["green"], "#EBF4E7"),
        ("149", "검토 필요", PALETTE["red"], PALETTE["soft_red"]),
    ]
    x = margin
    for number, label, color, fill in metrics:
        rounded(draw, (x, 240, x + 330, 385), fill=fill, outline=PALETTE["line"], radius=18)
        draw.text((x + 26, 268), number, font=f_metric, fill=color)
        draw.text((x + 32, 333), label, font=f_body_b, fill=PALETTE["ink"])
        x += 355

    # Priority panel
    left = margin
    top = 445
    panel_w = 700
    rounded(draw, (left, top, left + panel_w, 1305), fill=PALETTE["white"], outline=PALETTE["line"], radius=20)
    draw.text((left + 34, top + 28), "최우선 학습 축 TOP 10", font=f_h, fill=PALETTE["ink"])
    draw.text((left + 34, top + 72), "점수는 빈도·최근성·오답위험을 합산", font=f_small, fill=PALETTE["muted"])

    y = top + 122
    max_score = max(float(row["priority_score"]) for row in data["top_priority"][:10])
    accents = [PALETTE["teal"], PALETTE["navy"], PALETTE["orange"], PALETTE["gold"]]
    for idx, row in enumerate(data["top_priority"][:10], start=1):
        label = f"{row['topic_l2']} · {row['topic_l3']}"
        score = float(row["priority_score"])
        bar_w = int(430 * score / max_score)
        color = accents[(idx - 1) % len(accents)]
        draw.text((left + 34, y + 2), f"{idx:02d}", font=f_rank, fill=color)
        draw_text(draw, (left + 86, y), label, f_body_b if idx <= 6 else f_body, PALETTE["ink"], max_width=430, line_gap=2)
        draw.rounded_rectangle((left + 86, y + 46, left + 526, y + 64), radius=9, fill="#ECE8DC")
        draw.rounded_rectangle((left + 86, y + 46, left + 86 + bar_w, y + 64), radius=9, fill=color)
        draw.text((left + 540, y + 34), f"{score:.2f}", font=f_body_b, fill=PALETTE["ink"])
        draw.text((left + 610, y + 34), f"{row['recent_3yr_count']}문항", font=f_small, fill=PALETTE["muted"])
        y += 72

    # Topic count panel
    right = 820
    rounded(draw, (right, top, right + 702, 1028), fill=PALETTE["white"], outline=PALETTE["line"], radius=20)
    draw.text((right + 34, top + 28), "단원별 출제 볼륨", font=f_h, fill=PALETTE["ink"])
    draw.text((right + 34, top + 72), "unknown 제외, 자동 분류 기준", font=f_small, fill=PALETTE["muted"])
    max_count = max(count for _, count in data["topic_counts"])
    y = top + 126
    for topic, count in data["topic_counts"]:
        bar_w = int(430 * count / max_count)
        color = PALETTE["navy"] if "충돌" in topic else PALETTE["teal"] if "통신" in topic else PALETTE["orange"] if "영어" in topic else PALETTE["green"]
        draw_text(draw, (right + 34, y - 4), topic, f_body_b, PALETTE["ink"], max_width=250, line_gap=2)
        draw.rounded_rectangle((right + 292, y, right + 722 - 34, y + 26), radius=13, fill="#ECE8DC")
        draw.rounded_rectangle((right + 292, y, right + 292 + bar_w, y + 26), radius=13, fill=color)
        draw.text((right + 622, y - 4), f"{count}", font=f_body_b, fill=PALETTE["ink"])
        y += 56

    # Strategy formula panel
    rounded(draw, (right, 1064, right + 702, 1305), fill=PALETTE["soft_orange"], outline="#E4C6AA", radius=20)
    draw.text((right + 34, 1092), "고득점 공식", font=f_h, fill=PALETTE["ink"])
    formula_items = [
        ("1", "협약명 먼저 표시", "UNCLOS·COLREG·SOLAS·IAMSAR"),
        ("2", "부정문 표시", "옳지 않은 것, 모두 몇 개인가"),
        ("3", "숫자 규정 암기", "거리·기간·톤수·각도"),
    ]
    fy = 1142
    for number, title, detail in formula_items:
        pill(draw, (right + 34, fy, right + 72, fy + 38), PALETTE["orange"], number, font(19, True), PALETTE["white"])
        draw.text((right + 88, fy - 4), title, font=f_body_b, fill=PALETTE["ink"])
        draw.text((right + 88, fy + 25), detail, font=font(18), fill=PALETTE["muted"])
        fy += 51

    # Four-week plan
    plan_top = 1360
    rounded(draw, (margin, plan_top, 1522, 1772), fill=PALETTE["white"], outline=PALETTE["line"], radius=20)
    draw.text((margin + 34, plan_top + 30), "4주 합격 플랜", font=f_h, fill=PALETTE["ink"])
    plans = [
        ("1주", "고빈도 규칙", "COLREG 등화·음향·제한시계 + SMCP 조타명령"),
        ("2주", "협약 원문 빈칸", "UNCLOS·SOLAS·MARPOL\nSTCW 숫자/정의 정리"),
        ("3주", "SAR·보안·오염", "IAMSAR 단계/패턴, ISPS 등급, MARPOL 배출"),
        ("4주", "실전 회독", "20문항 세트 풀이 → topic_l2별 오답 재분류"),
    ]
    px = margin + 34
    for i, (week, title, detail) in enumerate(plans):
        box = (px + i * 356, plan_top + 94, px + i * 356 + 320, plan_top + 360)
        fill = [PALETTE["soft_teal"], PALETTE["soft_blue"], PALETTE["soft_orange"], "#EEF1E6"][i]
        rounded(draw, box, fill=fill, outline=PALETTE["line"], radius=18)
        pill(draw, (box[0] + 22, box[1] + 22, box[0] + 110, box[1] + 66), [PALETTE["teal"], PALETTE["navy"], PALETTE["orange"], PALETTE["green"]][i], week, font(22, True), PALETTE["white"])
        draw.text((box[0] + 22, box[1] + 92), title, font=f_body_b, fill=PALETTE["ink"])
        draw_text(draw, (box[0] + 22, box[1] + 132), detail, font(22), PALETTE["muted"], max_width=276, line_gap=8)

    # Final 7 days and caveat
    bottom_top = 1828
    rounded(draw, (margin, bottom_top, 915, 2076), fill=PALETTE["soft_blue"], outline="#C7D7E2", radius=20)
    draw.text((margin + 34, bottom_top + 28), "마지막 7일 압축", font=f_h, fill=PALETTE["ink"])
    bullets = [
        "D-7~D-5: TOP 10 주제만 반복 회독",
        "D-4~D-3: COLREG·SMCP·IAMSAR 표 백지 복원",
        "D-2: 최근 3개년 재풀이 후 오답만 표시",
        "D-1: 숫자 규정·약어만 가볍게 확인",
    ]
    y = bottom_top + 92
    for item in bullets:
        draw.ellipse((margin + 38, y + 8, margin + 52, y + 22), fill=PALETTE["navy"])
        draw_text(draw, (margin + 70, y), item, f_body, PALETTE["ink"], max_width=760)
        y += 42

    rounded(draw, (955, bottom_top, 1522, 2076), fill=PALETTE["soft_red"], outline="#E1B9B4", radius=20)
    draw.text((989, bottom_top + 28), "검토 필요", font=f_h, fill=PALETTE["ink"])
    caveat = (
        "OCR 기반 분석이라 오래된 스캔 일부는 번호·영문 철자가 깨집니다. "
        "149개 row는 human_review_queue.csv에서 원문 확인 대상으로 분리했습니다."
    )
    draw_text(draw, (989, bottom_top + 92), caveat, f_body, PALETTE["ink"], max_width=482, line_gap=10)

    draw.text((margin, 2130), "Source: outputs/02_questions_master.csv, 05_recent_weighted_priority.csv · Generated by scripts/create_strategy_infographic.py", font=f_small, fill=PALETTE["muted"])
    image.save(out_path, "PNG", optimize=True)


def create_html(data: dict, out_path: Path) -> None:
    top_cards = "\n".join(
        f"""
        <li>
          <strong>{html.escape(row['topic_l2'])}</strong>
          <span>{html.escape(row['topic_l3'])}</span>
          <em>{float(row['priority_score']):.2f}</em>
        </li>
        """
        for row in data["top_priority"][:10]
    )
    topics = "\n".join(
        f"<li><span>{html.escape(topic)}</span><b>{count}</b></li>"
        for topic, count in data["topic_counts"]
    )
    doc = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>해사영어 고득점 합격 전략 인포그래픽</title>
  <style>
    :root {{
      --paper: {PALETTE['paper']};
      --ink: {PALETTE['ink']};
      --muted: {PALETTE['muted']};
      --line: {PALETTE['line']};
      --navy: {PALETTE['navy']};
      --teal: {PALETTE['teal']};
      --orange: {PALETTE['orange']};
      --red: {PALETTE['red']};
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: "Malgun Gothic", "Apple SD Gothic Neo", system-ui, sans-serif;
      letter-spacing: 0;
    }}
    main {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 48px 28px;
    }}
    header {{
      display: grid;
      gap: 14px;
      border-bottom: 2px solid var(--line);
      padding-bottom: 28px;
    }}
    h1 {{
      margin: 0;
      font-size: 52px;
      line-height: 1.12;
    }}
    .lead {{ margin: 0; color: var(--muted); font-size: 22px; }}
    .formula {{
      display: inline-flex;
      width: fit-content;
      padding: 10px 18px;
      border-radius: 999px;
      background: var(--navy);
      color: white;
      font-weight: 700;
    }}
    .metrics, .grid, .plan {{
      display: grid;
      gap: 18px;
    }}
    .metrics {{
      grid-template-columns: repeat(4, 1fr);
      margin: 30px 0;
    }}
    .metric, section {{
      background: white;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 24px;
    }}
    .metric b {{ display: block; font-size: 44px; color: var(--teal); }}
    .metric span {{ font-size: 18px; font-weight: 700; }}
    .grid {{ grid-template-columns: 1fr 1fr; }}
    h2 {{ margin: 0 0 12px; font-size: 28px; }}
    ol, ul {{ margin: 0; padding: 0; list-style: none; }}
    .top-list li {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 4px 12px;
      padding: 12px 0;
      border-bottom: 1px solid #ebe6d8;
    }}
    .top-list span {{ color: var(--muted); }}
    .top-list em {{ grid-row: 1 / span 2; align-self: center; color: var(--orange); font-style: normal; font-weight: 800; }}
    .topic-list li {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      padding: 9px 0;
      border-bottom: 1px solid #ebe6d8;
    }}
    .plan {{
      grid-template-columns: repeat(4, 1fr);
      margin-top: 18px;
    }}
    .week {{
      background: #E8F3F1;
      border-radius: 16px;
      padding: 18px;
      min-height: 150px;
    }}
    .week b {{ display: inline-block; background: var(--teal); color: white; border-radius: 999px; padding: 6px 12px; margin-bottom: 12px; }}
    .week strong {{ display: block; margin-bottom: 8px; }}
    .note {{ margin-top: 18px; background: #F7E6E3; }}
    footer {{ margin-top: 24px; color: var(--muted); font-size: 14px; }}
    @media (max-width: 820px) {{
      h1 {{ font-size: 36px; }}
      .metrics, .grid, .plan {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>해사영어 고득점 합격 전략</h1>
      <p class="lead">기출 {data['question_count']}문항 · {data['group_count']}개 시험 세트 · 최근 3개년 가중분석 기반</p>
      <span class="formula">빈도 50 · 최근 30 · 오답위험 20</span>
    </header>
    <ul class="metrics">
      <li class="metric"><b>{data['question_count']}</b><span>문항 분석</span></li>
      <li class="metric"><b>{data['group_count']}</b><span>시험 세트</span></li>
      <li class="metric"><b>{data['classified_count']}</b><span>자동 분류</span></li>
      <li class="metric"><b>{data['review_count']}</b><span>검토 필요</span></li>
    </ul>
    <div class="grid">
      <section>
        <h2>최우선 학습 축 TOP 10</h2>
        <ol class="top-list">{top_cards}</ol>
      </section>
      <section>
        <h2>단원별 출제 볼륨</h2>
        <ul class="topic-list">{topics}</ul>
      </section>
    </div>
    <section style="margin-top:18px">
      <h2>4주 합격 플랜</h2>
      <div class="plan">
        <div class="week"><b>1주</b><strong>고빈도 규칙</strong><span>COLREG 등화·음향·제한시계 + SMCP 조타명령</span></div>
        <div class="week"><b>2주</b><strong>협약 원문 빈칸</strong><span>UNCLOS·SOLAS·MARPOL·STCW 숫자/정의 정리</span></div>
        <div class="week"><b>3주</b><strong>SAR·보안·오염</strong><span>IAMSAR 단계/패턴, ISPS 등급, MARPOL 배출</span></div>
        <div class="week"><b>4주</b><strong>실전 회독</strong><span>20문항 세트 풀이 후 topic_l2별 오답 재분류</span></div>
      </div>
    </section>
    <section class="note">
      <h2>마지막 7일 압축</h2>
      <p>D-7~D-5 TOP10 회독 → D-4~D-3 COLREG·SMCP·IAMSAR 표 백지 복원 → D-2 최근 3개년 재풀이 → D-1 숫자 규정·약어만 확인.</p>
      <p>OCR 기반 분석이라 오래된 스캔 일부는 번호·영문 철자가 깨집니다. {data['review_count']}개 row는 human_review_queue.csv에서 원문 확인 대상으로 분리했습니다.</p>
    </section>
    <footer>Source: outputs/02_questions_master.csv, 05_recent_weighted_priority.csv</footer>
  </main>
</body>
</html>
"""
    out_path.write_text(doc, encoding="utf-8")


def main() -> int:
    data = build_data()
    create_png(data, OUTPUT_DIR / "08_exam_strategy_infographic.png")
    create_html(data, OUTPUT_DIR / "08_exam_strategy_infographic.html")
    print("Wrote outputs/08_exam_strategy_infographic.png")
    print("Wrote outputs/08_exam_strategy_infographic.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
