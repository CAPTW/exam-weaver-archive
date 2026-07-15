from src.parser.formatting import (
    has_suspicious_text_artifact,
    normalize_latex_text,
    repair_extracted_text_artifacts,
)


def test_repair_extracted_text_artifacts_normalizes_private_math_glyphs_and_linewraps():
    text = (
        "3상 교류 유효전력을 표시한 것으로 옳은 것은? "
        "(단, \ue004는 선간전압,\n\ue008는 선전류, \ue0a4는 위상각이다)"
    )

    assert repair_extracted_text_artifacts(text) == (
        "3상 교류 유효전력을 표시한 것으로 옳은 것은? "
        "(단, E는 선간전압, I는 선전류, θ는 위상각이다)"
    )


def test_repair_extracted_text_artifacts_preserves_blank_parentheses():
    text = 'Wiper, Kim (   ) duty,\nbeing sick.'

    assert repair_extracted_text_artifacts(text) == 'Wiper, Kim (   ) duty, being sick.'
    assert repair_extracted_text_artifacts(
        '( )에 순서대로 적합한 것은? "다른 선박을 ( ) 쪽에 두고 ( )을/를 횡단"'
    ) == '( )에 순서대로 적합한 것은? "다른 선박을 ( ) 쪽에 두고 ( )을/를 횡단"'


def test_suspicious_text_detector_ignores_subject_names_in_plain_text():
    assert not has_suspicious_text_artifact('대체 가능한 기관2 문제')


def test_repair_extracted_text_artifacts_fixes_common_korean_spacing_joins():
    assert repair_extracted_text_artifacts('영향으로옳은 것은?') == '영향으로 옳은 것은?'
    assert repair_extracted_text_artifacts('관성력과 원심력에의해 작용한다.') == (
        '관성력과 원심력에 의해 작용한다.'
    )
    assert repair_extracted_text_artifacts('충돌의 위험이 있을때 외에는그 선박의 진로') == (
        '충돌의 위험이 있을 때 외에는 그 선박의 진로'
    )


def test_repair_extracted_text_artifacts_joins_safe_korean_linewrap_fragments():
    text = (
        "디젤기관에서 연료분사 시 유립의 크기에 대한 설명으\n"
        "로 옳\n"
        "지 않은 것은? 프로펠\n"
        "러와 적\n"
        "합한 일\n"
        "정한 정해\n"
        "진 값"
    )

    assert repair_extracted_text_artifacts(text) == (
        "디젤기관에서 연료분사 시 유립의 크기에 대한 설명으로 옳지 않은 것은? "
        "프로펠러와 적합한 일정한 정해진 값"
    )


def test_repair_extracted_text_artifacts_keeps_ambiguous_korean_linewrap_as_space():
    text = "태핏 클리어런스가 규정보다\n작은 경우 밸브가 열리기 시작하는 시기는?"

    assert repair_extracted_text_artifacts(text) == (
        "태핏 클리어런스가 규정보다 작은 경우 밸브가 열리기 시작하는 시기는?"
    )


def test_repair_extracted_text_artifacts_normalizes_hwp_math_glyphs():
    text = "함수 \ue0ea\ue044\ue0f8\ue045 \ue047 \ue034\ue046\ue0e9\ue046\ue035\ue0f8, P-\ue0a4, \ue015\ue034"

    assert repair_extracted_text_artifacts(text) == "함수 f(t) = 1-e-2t, P-θ, V1"


def test_repair_extracted_text_artifacts_rebuilds_single_variable_note():
    text = (
        "크랭크암 개폐량의 허용한도 중 안전하게 운전할 수 \n"
        "있는 한도는 단 는 행정 이다? ( , S [mm] .)"
    )

    assert repair_extracted_text_artifacts(text) == (
        "크랭크암 개폐량의 허용한도 중 안전하게 운전할 수 "
        "있는 한도는? (단, S는 행정[mm]이다.)"
    )


def test_repair_extracted_text_artifacts_rebuilds_multiple_variable_note():
    text = (
        "다음과 같이 다이오드와 저항으로 구성된 회로에 해당되는 "
        "논리기호는 단 는 입력이고 는 출력이다? ( , A, B X .)"
    )

    assert repair_extracted_text_artifacts(text) == (
        "다음과 같이 다이오드와 저항으로 구성된 회로에 해당되는 "
        "논리기호는? (단, A, B는 입력이고 X는 출력이다.)"
    )


def test_repair_extracted_text_artifacts_rebuilds_two_variable_note():
    text = "순방향 영역에서 다이오드의 특성을 옳게 나타낸 V-I 것은 단 는 전압 는 전류이다? ( , V , I .)"

    assert repair_extracted_text_artifacts(text) == (
        "순방향 영역에서 다이오드의 특성을 옳게 나타낸 V-I 것은? "
        "(단, V는 전압, I는 전류이다.)"
    )


def test_repair_extracted_text_artifacts_rebuilds_leading_blank_prompt_quote_question():
    text = (
        '에 순서대로 적합한 것은(   )? 상 회사는 안전 및 해양환경오염방지 활동"ISM code '
        '이 안전관리시스템을 준수하는 지를 검증하기 위하여을 넘지 않는 간격으로 회사 및 선박의 내부 안(   ) '
        '전심사를 실시하여야 한다 예외적인 상황인 경우 이. 심사의 간격은 이내까지 연장될 수 있다(   )."'
    )

    assert repair_extracted_text_artifacts(text) == (
        '"ISM code상 회사는 안전 및 해양환경오염방지 활동이 안전관리시스템을 준수하는지를 '
        '검증하기 위하여 (   )을 넘지 않는 간격으로 회사 및 선박의 내부 안전심사를 실시하여야 한다. '
        '예외적인 상황인 경우 이 심사의 간격은 (   ) 이내까지 연장될 수 있다." '
        '에 순서대로 적합한 것은?'
    )


def test_repair_extracted_text_artifacts_moves_inserted_prompt_tail_out_of_english_quote():
    text = (
        '"Fuel oil tanks to be (   ) and cleaned out for에서 에 알맞은 '
        'internal inspection by surveyor." (   ) 것은?'
    )

    assert repair_extracted_text_artifacts(text) == (
        '"Fuel oil tanks to be (   ) and cleaned out for internal inspection by surveyor."'
        '에서 (   )에 알맞은 것은?'
    )


def test_repair_extracted_text_artifacts_reorders_reversed_choice_fragments():
    assert repair_extracted_text_artifacts("개월 개월24, 6") == "24개월, 6개월"
    assert repair_extracted_text_artifacts("제곱 3") == "3제곱"
    assert repair_extracted_text_artifacts("시간6") == "6시간"
    assert repair_extracted_text_artifacts("년 3") == "3년"
    assert repair_extracted_text_artifacts("배 1.75") == "1.75배"
    assert repair_extracted_text_artifacts("점쇄선2") == "2점쇄선"
    assert repair_extracted_text_artifacts("약 해리5") == "약 5해리"
    assert repair_extracted_text_artifacts("업무정지 일15") == "업무정지 15일"
    assert repair_extracted_text_artifacts("업무정지 개월1") == "업무정지 1개월"
    assert repair_extracted_text_artifacts("총톤수 톤 이상100") == "총톤수 100톤 이상"
    assert repair_extracted_text_artifacts("국제항해에 종사하는 총톤수 톤인 어선400") == (
        "국제항해에 종사하는 총톤수 400톤인 어선"
    )
    assert repair_extracted_text_artifacts("둥근꼴 형상물 개1") == "둥근꼴 형상물 1개"
    assert repair_extracted_text_artifacts("장음 회5") == "장음 5회"
    assert repair_extracted_text_artifacts("제어량A:, B: 1") == "A: 제어량, B: 1"
    assert repair_extracted_text_artifacts("의료부문M,") == "M, 의료부문"
    assert repair_extracted_text_artifacts("쇄빙선과의 통신I,") == "I, 쇄빙선과의 통신"
    assert repair_extracted_text_artifacts("배1.25") == "1.25배"
    assert repair_extracted_text_artifacts("약 톤2,050") == "약 2,050톤"
    assert repair_extracted_text_artifacts("해리0.5 2∼") == "0.5∼2해리"
    assert repair_extracted_text_artifacts("이상60[℃]") == "60[℃] 이상"
    assert repair_extracted_text_artifacts("약 이하20[%]") == "약 20[%] 이하"
    assert repair_extracted_text_artifacts("미터 미만7") == "7미터 미만"
    assert repair_extracted_text_artifacts("센티미터 이상 10") == "10센티미터 이상"
    assert repair_extracted_text_artifacts("단정 진수훈련 년- 1") == "단정 진수훈련 - 1년"
    assert repair_extracted_text_artifacts(
        "줄의 법칙3.2[Ω], 2[Ω], 3[Ω]의 저항을 병렬로 접속한 회로에 21[V]의 전압을 공급하면 전류는 몇 [A]인가?"
    ) == "줄의 법칙"


def test_repair_extracted_text_artifacts_restores_displaced_sequence_arrows():
    assert repair_extracted_text_artifacts(
        "정적압축 정적팽창 단열팽창 단열압축→ → →"
    ) == "정적압축→정적팽창→단열팽창→단열압축"
    assert repair_extracted_text_artifacts("1 2 3 4→ → →") == "1→2→3→4"


def test_repair_extracted_text_artifacts_does_not_guess_ambiguous_tail_arrows():
    assert repair_extracted_text_artifacts("밸브를 열고 상태를 확인한다→ →") == (
        "밸브를 열고 상태를 확인한다→ →"
    )
    assert repair_extracted_text_artifacts("A B C→ → →") == "A B C→ → →"


def test_suspicious_text_detector_flags_displaced_sequence_arrows():
    assert has_suspicious_text_artifact(
        "정적압축 정적팽창 단열팽창 단열압축→ → →"
    )
    assert not has_suspicious_text_artifact("정적압축→정적팽창→단열팽창→단열압축")


def test_repair_extracted_text_artifacts_rebuilds_rest_hours_numeric_choice():
    assert repair_extracted_text_artifacts(
        "임의의 시간의 기간 중 시간과 임의의 24 10 7 일의 기간 중 시간을 하회해서는 안 된다77."
    ) == (
        "임의의 24시간의 기간 중 10시간과 임의의 7일의 기간 중 "
        "77시간을 하회해서는 안 된다."
    )


def test_repair_extracted_text_artifacts_rebuilds_embedded_number_unit_fragments():
    assert repair_extracted_text_artifacts(
        "직경이 다른 동일 원관 내에 흐르는 물은 직경이 배2로 되는 곳에서 유속은 몇 배로 되는가?"
    ) == "직경이 다른 동일 원관 내에 흐르는 물은 직경이 2배로 되는 곳에서 유속은 몇 배로 되는가?"
    assert repair_extracted_text_artifacts(
        "협약상 모든 구명줄발사기는 조용한 날씨에 SOLAS 적어도 미터 길이의 줄을 운반할 수 있는 몇 개 230 이상의 발사체를 가져야 하는가?"
    ) == (
        "SOLAS 협약상 모든 구명줄발사기는 조용한 날씨에 적어도 230미터 길이의 줄을 "
        "운반할 수 있는 몇 개 이상의 발사체를 가져야 하는가?"
    )
    assert repair_extracted_text_artifacts("기선으로부터 해리 이상 떨어진 곳에서 배12 출할 것") == (
        "기선으로부터 12해리 이상 떨어진 곳에서 배출할 것"
    )
    assert repair_extracted_text_artifacts("육지로부터 해리 이상 떨어진 해역에서 배12 출하여야 한다.") == (
        "육지로부터 12해리 이상 떨어진 해역에서 배출하여야 한다."
    )
    assert repair_extracted_text_artifacts(
        "어느 저항체에 가해지는 전압을 배로 증가시키면 이2 때 저항체에서 나타나는 전류와 전력은 각각 몇 배로 커지는가?"
    ) == (
        "어느 저항체에 가해지는 전압을 2배로 증가시키면 이때 저항체에서 나타나는 전류와 전력은 "
        "각각 몇 배로 커지는가?"
    )
    assert repair_extracted_text_artifacts("전류는 배 전력은 배 2, 4") == "전류는 2배, 전력은 4배"
    assert repair_extracted_text_artifacts("년 년5, 3") == "5년, 3년"
    assert repair_extracted_text_artifacts(
        "예인선열의 길이가 미터 초과 미터 미100, 200만일 때 예인선은 주간에 마름모꼴 형상물 개1를 표시하여야 한다."
    ) == (
        "예인선열의 길이가 100미터 초과 200미터 미만일 때 예인선은 주간에 "
        "마름모꼴 형상물 1개를 표시하여야 한다."
    )
    assert repair_extracted_text_artifacts("해리 1 3∼") == "1∼3해리"
    assert repair_extracted_text_artifacts("분을 넘지 아니하는 간격으로 장음 회1 2") == (
        "2분을 넘지 아니하는 간격으로 장음 1회"
    )
    assert repair_extracted_text_artifacts("장음 회 단음 회2, 1") == "장음 2회, 단음 1회"
    assert repair_extracted_text_artifacts("단음 회에 이은 장음 회1 2") == "단음 1회에 이은 장음 2회"
    assert repair_extracted_text_artifacts("여객선 길이 에서 미만 개120m 180m: 18") == (
        "여객선 길이 120m 이상 180m 미만: 18개"
    )
    assert repair_extracted_text_artifacts(
        "총톤수 톤 이상의 유조선과 총톤수 톤 150 400 이상의 유조선이 아닌 모든 선박에 적용된다."
    ) == "총톤수 150톤 이상의 유조선과 총톤수 400톤 이상의 유조선이 아닌 모든 선박에 적용된다."
    assert repair_extracted_text_artifacts("현등 쌍 수직선상에 붉은색 전주등 개1, 3") == (
        "현등 1쌍, 수직선상에 붉은색 전주등 3개"
    )
    assert repair_extracted_text_artifacts(
        "국제항해에 종사하는 선박에 대하여 년 1969 선박의 톤수 측정에 관한 국제협약규정에 따라 선박 크기를 나타내는 톤수는 국제총톤수이다."
    ) == (
        "국제항해에 종사하는 선박에 대하여 1969년 선박의 톤수 측정에 관한 "
        "국제협약규정에 따라 선박 크기를 나타내는 톤수는 국제총톤수이다."
    )
    assert repair_extracted_text_artifacts(
        "배수량 톤인 선박이 비중 인 수역에서 비10,000 1.025 중 인 수역으로 진입하였을 때 평균흘수가 1.000 증가했다면 비중 인 수역에서의 매 10cm, 1.000 cm 배수톤은?"
    ) == (
        "배수량 10,000톤인 선박이 비중 1.025인 수역에서 비중 1.000인 수역으로 진입하였을 때 "
        "평균흘수가 10cm 증가했다면 비중 1.000인 수역에서의 매 cm 배수톤은?"
    )
    assert repair_extracted_text_artifacts(
        "배수량 톤인 선박이 해수 비중 에 떠있는 6,560 (: 1.025) 경우 수면 밑에 잠긴 선체의 용적은?"
    ) == "배수량 6,560톤인 선박이 해수(비중: 1.025)에 떠있는 경우 수면 밑에 잠긴 선체의 용적은?"
    assert repair_extracted_text_artifacts(
        "배수량 톤인 선박에서 선창 내에 있는 톤의 10,000 200 화물을 상방으로 미터 옮겨 적재하였다면 5 GM 의 변 화량은?"
    ) == "배수량 10,000톤인 선박에서 선창 내에 있는 200톤의 화물을 상방으로 5미터 옮겨 적재하였다면 GM의 변화량은?"
    assert repair_extracted_text_artifacts(
        "월 일 인천항의 오전 고조시는12 20? 단 당일 달의 (, 자오선 통과시는 시 분 인천항의 평균 고조간격은 03 55, 시간 분임4 28)"
    ) == (
        "12월 20일 인천항의 오전 고조시는? "
        "(단, 당일 달의 자오선 통과시는 03시 55분, 인천항의 평균 고조간격은 4시간 28분임)"
    )
    assert repair_extracted_text_artifacts("시 분00 33") == "00시 33분"
    assert repair_extracted_text_artifacts("시 분 08 23") == "08시 23분"
    assert repair_extracted_text_artifacts("감소 0.100m") == "0.100m 감소"
    assert repair_extracted_text_artifacts("감소 9[%]") == "9[%] 감소"
    assert repair_extracted_text_artifacts(
        "국제해상충돌방지규칙상 예인선열의 길이가 미터200를 넘을 때 예인선과 피예인선에 표시하여야 하는 형 상물은?"
    ) == (
        "국제해상충돌방지규칙상 예인선열의 길이가 200미터를 넘을 때 "
        "예인선과 피예인선에 표시하여야 하는 형상물은?"
    )


def test_repair_extracted_text_artifacts_rebuilds_latin_choice_fragments():
    assert repair_extracted_text_artifacts("종 절연B") == "B종 절연"
    assert repair_extracted_text_artifacts("종 절연 F") == "F종 절연"
    assert repair_extracted_text_artifacts("종 E") == "E종"
    assert repair_extracted_text_artifacts("급A") == "A급"
    assert repair_extracted_text_artifacts("류 Y") == "Y류"
    assert repair_extracted_text_artifacts("자석 C") == "C자석"
    assert repair_extracted_text_artifacts("자T") == "T자"
    assert repair_extracted_text_artifacts("형 반도체N") == "N형 반도체"
    assert repair_extracted_text_artifacts("반도체P-N") == "P-N 반도체"
    assert repair_extracted_text_artifacts("플립플롭T") == "T 플립플롭"
    assert repair_extracted_text_artifacts("회로RS Flip Flop –") == "RS Flip Flop 회로"
    assert repair_extracted_text_artifacts("지수API") == "API지수"
    assert repair_extracted_text_artifacts("회로R-L") == "R-L 회로"
    assert repair_extracted_text_artifacts("평활회로R-C") == "R-C 평활회로"
    assert repair_extracted_text_artifacts("와 C H") == "C와 H"
    assert repair_extracted_text_artifacts("는 부하에 걸리는 전압의 실효값이다E.") == (
        "E는 부하에 걸리는 전압의 실효값이다."
    )
    assert repair_extracted_text_artifacts("의 단위는 이다P [kVA].") == "P의 단위는 [kVA]이다."
    assert repair_extracted_text_artifacts("발전기는 결선을 하고 전동기는 결선을 한다Y.△") == (
        "발전기는 △결선을 하고 전동기는 Y결선을 한다."
    )
    assert repair_extracted_text_artifacts("접합형과 형이 있다MOS.") == "접합형과 MOS형이 있다."
    assert repair_extracted_text_artifacts("채널형과 채널형이 있다P N.") == "P채널형과 N채널형이 있다."
    assert repair_extracted_text_artifacts("은 피복 아크 용접봉이라는 의미이다4316.") == (
        "4316은 피복 아크 용접봉이라는 의미이다."
    )
    assert repair_extracted_text_artifacts("주기관의 펌프L.O.") == "주기관의 L.O. 펌프"
    assert repair_extracted_text_artifacts(
        "류 기관구역이 아닌 곳에 설치된 비상소화펌A 프에는 인화점 이하의 연료유를 사용43[℃] 할 수 있다."
    ) == "A류 기관구역이 아닌 곳에 설치된 비상소화펌프에는 인화점 43[℃] 이하의 연료유를 사용할 수 있다."
    assert repair_extracted_text_artifacts("내 전체 프로그램이 회 실행되는 데 걸PLC 1 리는 시간") == (
        "PLC 내 전체 프로그램이 1회 실행되는 데 걸리는 시간"
    )
    assert repair_extracted_text_artifacts("예비발전기의 기동순서는 발전기 순서 설S/B 정에 따라 운전된다.") == (
        "예비발전기의 기동순서는 S/B 발전기 순서 설정에 따라 운전된다."
    )
    assert repair_extracted_text_artifacts("계 냉매를 사용하는 냉동장치의 팽창밸HCFC 브 교환 작업") == (
        "HCFC계 냉매를 사용하는 냉동장치의 팽창밸브 교환 작업"
    )
    assert repair_extracted_text_artifacts("예비발전기를 시동하여 를 투입시킨다ACB.") == (
        "예비발전기를 시동하여 ACB를 투입시킨다."
    )
    assert repair_extracted_text_artifacts("기관에 의해 비교 시험하는 방법CFR") == "CFR 기관에 의해 비교 시험하는 방법"
    assert repair_extracted_text_artifacts("는 고정식 세정기로 해야 한다COW.") == "COW는 고정식 세정기로 해야 한다."
    assert repair_extracted_text_artifacts("는 를 장비한 탱커에서만 할 수 있다COW IGS.") == (
        "COW는 IGS를 장비한 탱커에서만 할 수 있다."
    )
    assert repair_extracted_text_artifacts("에서 중심까지 높이를 알 수 있다Keel.") == (
        "Keel에서 중심까지 높이를 알 수 있다."
    )
    assert repair_extracted_text_artifacts("를 사용하여 선수를 바람이 불어Bow thruster 오는 쪽으로 유지한다.") == (
        "Bow thruster를 사용하여 선수를 바람이 불어오는 쪽으로 유지한다."
    )
    assert repair_extracted_text_artifacts("폭을 줄인다Pulse.") == "Pulse 폭을 줄인다."
    assert repair_extracted_text_artifacts("의 폭을 크게 한다Antenna.") == "Antenna의 폭을 크게 한다."
    assert repair_extracted_text_artifacts("간의 수은 유통이 불량한 경우NS") == "NS 간의 수은 유통이 불량한 경우"
    assert repair_extracted_text_artifacts("가 동명이고 인 경우L, d, L>d") == "L, d가 동명이고 L>d인 경우"
    assert repair_extracted_text_artifacts("화Sling") == "Sling화"
    assert repair_extracted_text_artifacts("협약 제 장에 명시되어 있다SOLAS 9.") == "SOLAS 협약 제9장에 명시되어 있다."
    assert repair_extracted_text_artifacts("는 공기보다 가볍다LPG.") == "LPG는 공기보다 가볍다."
    assert repair_extracted_text_artifacts("의 주성분은 메탄LNG (CH 4이고 공기보다 가볍다).") == (
        "LNG의 주성분은 메탄(CH4)이고 공기보다 가볍다."
    )
    assert repair_extracted_text_artifacts("의 갱신심사 유효기간은 년이다SMC 5.") == (
        "SMC의 갱신심사 유효기간은 5년이다."
    )
    assert repair_extracted_text_artifacts("선박에는 사본을 비치하여야 한다DOC.") == "선박에는 DOC 사본을 비치하여야 한다."
    assert repair_extracted_text_artifacts("한 개의 에 만재되지 아니하는 소량Container의 화물Container") == (
        "한 개의 Container에 만재되지 아니하는 소량의 화물"
    )
    assert repair_extracted_text_artifacts("협약에 의하여 발행된 증서는 항상 본SOLAS 선에 비치하여 즉시 점검받을 수 있어야 한다.") == (
        "SOLAS 협약에 의하여 발행된 증서는 항상 본선에 비치하여 즉시 점검받을 수 있어야 한다."
    )
    assert repair_extracted_text_artifacts("조난 신호Distress signals -") == "Distress signals - 조난 신호"
    assert repair_extracted_text_artifacts("의 마찰 오차Pivot") == "Pivot의 마찰 오차"
    assert repair_extracted_text_artifacts("공동현상Cavitation()") == "공동현상(Cavitation)"
    assert repair_extracted_text_artifacts("제어ON-OFF") == "ON-OFF 제어"
    assert repair_extracted_text_artifacts("증서IOPP") == "IOPP 증서"
    assert repair_extracted_text_artifacts("트립장치Reverse power") == "Reverse power 트립장치"
    assert repair_extracted_text_artifacts("선위 오차는 에 비례한다sin.θ") == "선위 오차는 sinθ에 비례한다."
    assert repair_extracted_text_artifacts("전장LOA ()") == "전장(LOA)"
    assert repair_extracted_text_artifacts("와 점이 등전위인 경우a b") == "a와 b점이 등전위인 경우"
    assert repair_extracted_text_artifacts("본선의 화물량이 양보다 많을 경우에는 B/L를 작성하지 않는다Cargo protest.") == (
        "본선의 화물량이 B/L 양보다 많을 경우에는 Cargo protest를 작성하지 않는다."
    )
    assert repair_extracted_text_artifacts("본선의 화물량이 양보다 적을 경우에는 B/L를 작성하지 않는다Cargo protest.") == (
        "본선의 화물량이 B/L 양보다 적을 경우에는 Cargo protest를 작성하지 않는다."
    )
    assert repair_extracted_text_artifacts("본선의 화물량과 양과 차이가 크지 않을 B/L 경우에는 별다른 조치를 취하지 않는다.") == (
        "본선의 화물량과 B/L 양과 차이가 크지 않을 경우에는 별다른 조치를 취하지 않는다."
    )
    assert repair_extracted_text_artifacts("용선계약서의 지침을 따라야 하며 선주사 또는 (용선주 에게 보고 후 를 작성한다) Cargo protest.") == (
        "용선계약서의 지침을 따라야 하며 선주사 또는 용선주에게 보고 후 Cargo protest를 작성한다."
    )
    assert repair_extracted_text_artifacts("NOX 은 질소산화물에 대한 사항을 technical file기록한다.") == (
        "NOx technical file은 질소산화물에 대한 사항을 기록한다."
    )
    assert repair_extracted_text_artifacts("은 질소산화물에 대한 사항을 NOx technical file기록한다.") == (
        "NOx technical file은 질소산화물에 대한 사항을 기록한다."
    )
    assert repair_extracted_text_artifacts("의 하중시험은 그 선회반경을 사용되Jib crane는 범위 중 최소치와 최대치로 하여 행한다.") == (
        "Jib crane의 하중시험은 그 선회반경을 사용되는 범위 중 최소치와 최대치로 하여 행한다."
    )
    assert repair_extracted_text_artifacts("제한하중이 톤 이하의 것에는 일반적으로 10의 앙각을 로 하여 행한다Boom 15. ˚") == (
        "제한하중이 10톤 이하의 것에는 데릭붐의 수평면에 대한 각도를 15˚로 하여 행한다."
    )
    assert repair_extracted_text_artifacts("길이는 에 회 이상 감긴 Cargo fall Wire drum 3 상태에서 가 까지 도달Hook Hatch center line하여야 한다.") == (
        "Cargo fall의 길이는 Wire drum에 3회 이상 감긴 상태에서 Hook이 Hatch center line까지 도달하여야 한다."
    )
    assert repair_extracted_text_artifacts("선체의 종중심 단면과 형 표면- (Moulded과의 교선surface)") == (
        "선체의 종중심 단면과 형표면(Moulded surface)과의 교선"
    )
    assert repair_extracted_text_artifacts("유조선 및 케미컬 탱커의 화물과 하역장치에 관련된 특정한 임무와 책임을 담당하는 자격자와 부원은 기초 승무자격증(Certificate of을 소지하여야 한다proficiency).") == (
        "유조선 및 케미컬 탱커의 화물과 하역장치에 관련된 특정한 임무와 책임을 담당하는 자격자와 부원은 기초 승무자격증(Certificate of proficiency)을 소지하여야 한다."
    )
    assert repair_extracted_text_artifacts("등이 있다Diaphone, Diaphragm horn.") == "Diaphone, Diaphragm horn 등이 있다."
    assert repair_extracted_text_artifacts("우리나라에서는 수중음신호(Submarine sound를 채용하고 있다signal).") == (
        "우리나라에서는 수중음신호(Submarine sound signal)를 채용하고 있다."
    )
    assert repair_extracted_text_artifacts("는 국제항해에 종사하는 고속여객선ISPS code을 포함한 여객선에 적용된다.") == (
        "ISPS code는 국제항해에 종사하는 고속여객선을 포함한 여객선에 적용된다."
    )
    assert repair_extracted_text_artifacts("는 국제항해에 종사하는 총톤수 ISPS code 톤 이상의 고속선을 포함한 화물선에 적용400된다.") == (
        "ISPS code는 국제항해에 종사하는 총톤수 400톤 이상의 고속선을 포함한 화물선에 적용된다."
    )
    assert repair_extracted_text_artifacts("으로 인한 선체 손상 염려가 없다Stock.") == "Stock으로 인한 선체 손상 염려가 없다."
    assert repair_extracted_text_artifacts("이 길기 때문에 피예인선은 예인선과 별Tow line도로 행동할 수 있다.") == (
        "Tow line이 길기 때문에 피예인선은 예인선과 별도로 행동할 수 있다."
    )
    assert repair_extracted_text_artifacts("내의 액 이 감소하면 원격 지Chamber Level 시기가 지시하는 보일러수 은 낮아진다Level.") == (
        "Chamber 내의 액 Level이 감소하면 원격 지시기가 지시하는 보일러수 Level은 낮아진다."
    )
    assert repair_extracted_text_artifacts("부하로 운전 시 3/4 P max와 Pcomp의 차이는 약 이다35[bar].") == (
        "3/4 부하로 운전 시 Pmax와 Pcomp의 차이는 약 35[bar]이다."
    )
    assert repair_extracted_text_artifacts("적당한 값TBN") == "적당한 TBN값"
    assert repair_extracted_text_artifacts("압력조절기에 의해 청수 압력을 제어한다PID.") == "PID 압력조절기에 의해 청수 압력을 제어한다."
    assert repair_extracted_text_artifacts("소자이다PNPN.") == "PNPN 소자이다."
    assert repair_extracted_text_artifacts("논리 게이트XOR") == "XOR 논리 게이트"
    assert repair_extracted_text_artifacts("게이트NAND") == "NAND 게이트"
    assert repair_extracted_text_artifacts("작업전 타입의 안전모를 착용한다AB.") == "작업전 AB 타입의 안전모를 착용한다."
    assert repair_extracted_text_artifacts("용접MIG") == "MIG 용접"
    assert repair_extracted_text_artifacts("용접Spot") == "Spot 용접"
    assert repair_extracted_text_artifacts("만 켜져 있다GL.") == "GL만 켜져 있다."
    assert repair_extracted_text_artifacts("과 이 모두 켜져 있다GL RL.") == "GL과 RL이 모두 켜져 있다."


def test_repair_extracted_text_artifacts_removes_subject_header_fragments():
    assert repair_extracted_text_artifacts("탄화되기 쉬울 것[제2과목:기관2]") == "탄화되기 쉬울 것"
    assert repair_extracted_text_artifacts("우측면도 [제3과목:기관3]") == "우측면도"
    assert repair_extracted_text_artifacts(
        "Chamber의 연결 밸브는 Check valve를 사용한다. [제4과목:직무일반]"
    ) == "Chamber의 연결 밸브는 Check valve를 사용한다."
    assert repair_extracted_text_artifacts(
        "외형선[제3과목:기관3]1.1[kW]를 소비하는 다음과 같은 회로에서 1[Ω]의 양단 전압과 소비전력의 크기는?"
    ) == "외형선"


def test_repair_extracted_text_artifacts_moves_curly_quoted_prompt_tail_only_when_broken():
    broken = (
        "“(  ) is a rotating component of a centrifugal pump which transfers energy.”"
        "에서 에 알맞은 것은(   )?"
    )

    assert repair_extracted_text_artifacts(broken) == (
        '"(  ) is a rotating component of a centrifugal pump which transfers energy."'
        '에서 (   )에 알맞은 것은?'
    )

    normal = "다음 문장의 (   )에 알맞은 것은? “The pump is ready.”"
    assert repair_extracted_text_artifacts(normal) == normal


def test_repair_extracted_text_artifacts_moves_purpose_and_meaning_prompt_tails():
    purpose = '"Renewed 4 worn-out (zinc plates) on condenser에서 부분의 용도는 무엇인가covers" (   )?'
    meaning = '"Before reaching Busan port should be ready a list에서 의 뜻으로 옳은 것은of (stores on hand)." (  )?'

    assert repair_extracted_text_artifacts(purpose) == (
        '"Renewed 4 worn-out (zinc plates) on condenser covers"에서 '
        '(zinc plates) 부분의 용도는 무엇인가?'
    )
    assert repair_extracted_text_artifacts(meaning) == (
        '"Before reaching Busan port should be ready a list of (stores on hand)."에서 '
        '(stores on hand)의 뜻으로 옳은 것은?'
    )


def test_repair_extracted_text_artifacts_fixes_reordered_number_unit_sentences():
    assert repair_extracted_text_artifacts(
        "초 동안 의 전하가 어느 전선을 통과할 때의 2 10[C] 전류는 몇 인가[A]?"
    ) == "2초 동안 10[C]의 전하가 어느 전선을 통과할 때의 전류는 몇 [A]인가?"
    assert repair_extracted_text_artifacts(
        "의 저항 개를 병렬로 연결하여 를 가할 20[] 2 200[V]Ω 때 흐르는 전류는 몇 인가[A]?"
    ) == "20[Ω]의 저항 2개를 병렬로 연결하여 200[V]를 가할 때 흐르는 전류는 몇 [A]인가?"
    assert repair_extracted_text_artifacts("약 80 90[%] ∼") == "약 80∼90[%]"
    assert repair_extracted_text_artifacts(
        '"Intake stroke begins at (   ) and ends at (   )." 에서 에 각각 순서대로 알맞은 것은(   )?'
    ) == (
        '"Intake stroke begins at (   ) and ends at (   )."에서 '
        '(   )에 각각 순서대로 알맞은 것은?'
    )
    assert repair_extracted_text_artifacts(
        "최대눈금 내부저항 의 전압계로 150[V], 15[k] Ω 의 전압을 측정하려면 "
        "직렬로 접속하는 배율기900[V]의 저항은 몇 인가[k]?Ω"
    ) == (
        "최대눈금 150[V], 내부저항 15[kΩ]의 전압계로 900[V]의 전압을 측정하려면 "
        "직렬로 접속하는 배율기의 저항은 몇 [kΩ]인가?"
    )
    assert repair_extracted_text_artifacts("주기가 인 교류 파형의 주파수는 몇 인가0.2[s] [Hz]?") == (
        "주기가 0.2[s]인 교류 파형의 주파수는 몇 [Hz]인가?"
    )
    assert repair_extracted_text_artifacts("상 유도전동기의 고정자에 생기는 자계는3?") == (
        "3상 유도전동기의 고정자에 생기는 자계는?"
    )
    assert repair_extracted_text_artifacts(
        "선수흘수가 선미흘수가 중앙부 흘수가 8.48m, 8.99m, 인 선박의 상태는8.82m?"
    ) == "선수흘수가 8.48m, 선미흘수가 8.99m, 중앙부 흘수가 8.82m인 선박의 상태는?"
    assert repair_extracted_text_artifacts(
        "단면적이 1[m2 인 덕트 내를 시간당] (duct) 7,200[m 3]의 공기가 흐를 경우 풍속은 몇 인가[m/s]?"
    ) == "단면적이 1[m2]인 덕트(duct) 내를 시간당 7,200[m3]의 공기가 흐를 경우 풍속은 몇 [m/s]인가?"


def test_repair_extracted_text_artifacts_moves_english_tail_before_korean_particle_prompt():
    assert repair_extracted_text_artifacts("를 이용하여 구할 수 있는 것은Star finder?") == (
        "Star finder를 이용하여 구할 수 있는 것은?"
    )
    assert repair_extracted_text_artifacts("에 대한 설명으로 옳지 않은 것은IGBT?") == (
        "IGBT에 대한 설명으로 옳지 않은 것은?"
    )
    assert repair_extracted_text_artifacts("의 기본 원리는Echo sounder?") == (
        "Echo sounder의 기본 원리는?"
    )
    assert repair_extracted_text_artifacts("에서 전파의 도달 시간차가 가장 큰 경우는Loran-C?") == (
        "Loran-C에서 전파의 도달 시간차가 가장 큰 경우는?"
    )


def test_repair_extracted_text_artifacts_rebuilds_complex_english_korean_prompt_misorders():
    assert repair_extracted_text_artifacts("에서 개의 을 연결하는 것은Anchor chain 2 Shackle?") == (
        "Anchor chain에서 2개의 Shackle을 연결하는 것은?"
    )
    assert repair_extracted_text_artifacts(
        "로 운용되는 수신 전용의 수신장치로서 518kHz NBDP 연안 항행 선박에 대해서 "
        "필요한 해사안전정보의 수신에 이용되는 의 장치는GMDSS?"
    ) == (
        "518kHz NBDP로 운용되는 수신 전용의 수신장치로서 연안 항행 선박에 대해서 "
        "필요한 해사안전정보의 수신에 이용되는 GMDSS의 장치는?"
    )
    assert repair_extracted_text_artifacts("에서 의사 거리 란 무엇인가GPS (Pseudo range)?") == (
        "GPS에서 의사 거리(Pseudo range)란 무엇인가?"
    )
    assert repair_extracted_text_artifacts("과 동일한 의장법이 아닌 것은Burtoning system Derrick?") == (
        "Burtoning system과 동일한 Derrick 의장법이 아닌 것은?"
    )
    assert repair_extracted_text_artifacts('의 에 해당되는 것은"2 stroke cycle engine" 1 cycle?') == (
        '"2 stroke cycle engine"의 1 cycle에 해당되는 것은?'
    )
    assert repair_extracted_text_artifacts(
        '"Heat exchangers on board ship are mainly cooler에서 에where a hot liquid is cooled by (   )." (   ) 알 맞은 것은?'
    ) == (
        '"Heat exchangers on board ship are mainly cooler where a hot liquid is cooled by (   )."'
        '에서 (   )에 알맞은 것은?'
    )


def test_repair_extracted_text_artifacts_rebuilds_tail_escaped_latin_terms():
    assert repair_extracted_text_artifacts(
        "다음과 같은 정류회로에서 입력 전압 가 정현파이면 Vi 출력측 전압 의 파형은Vo?"
    ) == "다음과 같은 정류회로에서 입력 전압 Vi가 정현파이면 출력측 전압 Vo의 파형은?"
    assert repair_extracted_text_artifacts("다이오드에서 형 반도체에 연결된 단자의 명칭은N?") == (
        "다이오드에서 N형 반도체에 연결된 단자의 명칭은?"
    )
    assert repair_extracted_text_artifacts("불활성 가스 장치에서 의 역할은Scrubber?") == (
        "불활성 가스 장치에서 Scrubber의 역할은?"
    )
    assert repair_extracted_text_artifacts("급 대형 화재 시 냉각소화에 가장 효과적인 방법은A?") == (
        "A급 대형 화재 시 냉각소화에 가장 효과적인 방법은?"
    )
    assert repair_extracted_text_artifacts("다음 중 협약이 적용되는 선박은SOLAS?") == (
        "다음 중 SOLAS 협약이 적용되는 선박은?"
    )
    assert repair_extracted_text_artifacts(
        "국제해상충돌방지규칙상 연안통항대(Inshore traffic를 이용할 수 없는 선박은zone)?"
    ) == "국제해상충돌방지규칙상 연안통항대(Inshore traffic zone)를 이용할 수 없는 선박은?"
    assert repair_extracted_text_artifacts(
        "부정기선 화물운송에서 선주와 화주 사이의 항해용선계 약에서 를 지불해야 하는 사람은Brokerage?"
    ) == "부정기선 화물운송에서 선주와 화주 사이의 항해용선계약에서 Brokerage를 지불해야 하는 사람은?"


def test_repair_extracted_text_artifacts_rebuilds_embedded_english_korean_prompt_misorders():
    assert repair_extracted_text_artifacts("상 증서에 대한 설명으로 옳지 않은 것은ISM Code?") == (
        "ISM Code상 증서에 대한 설명으로 옳지 않은 것은?"
    )
    assert repair_extracted_text_artifacts("선도에서 사이클 내부의 면적은 무엇을 나타내는가P-V?") == (
        "P-V 선도에서 사이클 내부의 면적은 무엇을 나타내는가?"
    )
    assert repair_extracted_text_artifacts(
        "보일러 장치 중 공기분리 급수가열기(deaerating feed의 기능이 아닌 것은water heater)?"
    ) == (
        "보일러 장치 중 공기분리 급수가열기(deaerating feed water heater)의 기능이 아닌 것은?"
    )
    assert repair_extracted_text_artifacts(
        "다음 중 기계식 자이로컴퍼스에서 부정오차(Wandering를 일으키는 원인이 아닌 것은error)?"
    ) == (
        "다음 중 기계식 자이로컴퍼스에서 부정오차(Wandering error)를 일으키는 원인이 아닌 것은?"
    )
    assert repair_extracted_text_artifacts('에서 에 "Engine speed is measured by (   )." (   ) 알맞은 것은?') == (
        '"Engine speed is measured by (   )."에서 (   )에 알맞은 것은?'
    )
    assert repair_extracted_text_artifacts("다음 회로는 어떤 회로인가OP Amp?") == (
        "다음 OP Amp 회로는 어떤 회로인가?"
    )
    assert repair_extracted_text_artifacts("가스용접에서 용제 의 역할 중 가장 중요한 것은(flux)?") == (
        "가스용접에서 용제(flux)의 역할 중 가장 중요한 것은?"
    )
    assert repair_extracted_text_artifacts('"(   ) the water from the oil in the settling tank". 에서 에 들어갈 단어로 옳지 않은 것은(   )?') == (
        '"(   ) the water from the oil in the settling tank."에서 (   )에 들어갈 단어로 옳지 않은 것은?'
    )
    assert repair_extracted_text_artifacts(
        '양묘기는 정격하중을 감아올릴 때 정격속도가 " (  ) 이상의 능력을 갖추어야 한다 에서 에 [m/min]." (  ) 알맞은 것은?'
    ) == (
        '양묘기는 정격하중을 감아올릴 때 정격속도가 "(  ) [m/min] 이상의 능력을 갖추어야 한다."'
        '에서 (  )에 알맞은 것은?'
    )


def test_repair_extracted_text_artifacts_rebuilds_english_quote_prompt_spillovers():
    assert repair_extracted_text_artifacts(
        '"Suction and exhaust valves are closed and combustion occurs with a resultant increase in는 어느 행pressure, '
        'forcing the piston downward." 정에 해당하는가?'
    ) == (
        '"Suction and exhaust valves are closed and combustion occurs with a resultant increase in pressure, '
        'forcing the piston downward."는 어느 행정에 해당하는가?'
    )
    assert repair_extracted_text_artifacts(
        'Intake and exhaust valves are closed, and combustion occurs with a resultant increase in pressure, '
        'forcing the piston downward."는 4행정 디젤기관의 어느 행정에 해당되는가?'
    ) == (
        '"Intake and exhaust valves are closed, and combustion occurs with a resultant increase in pressure, '
        'forcing the piston downward."는 4행정 디젤기관의 어느 행정에 해당되는가?'
    )
    assert repair_extracted_text_artifacts(
        '"The mechanical efficiency of an engine is the ratio of BHP to IHP에서 밑줄 친 부분의 뜻은."?'
    ) == '"The mechanical efficiency of an engine is the ratio of BHP to IHP."에서 밑줄 친 부분의 뜻은?'
    assert repair_extracted_text_artifacts(
        '"Oily mixture means a mixture with any oil에서 밑줄 친 부분의 뜻은content."?'
    ) == '"Oily mixture means a mixture with any oil content."에서 밑줄 친 부분의 뜻은?'
    assert repair_extracted_text_artifacts(
        '"(   ) is a heat-transfer device in the distilling에서 plant, which utilizes steam to heat sea water." 에 알맞은 것은(    )?'
    ) == '"(   ) is a heat-transfer device in the distilling plant, which utilizes steam to heat sea water."에서 (   )에 알맞은 것은?'
    assert repair_extracted_text_artifacts(
        '"Adjusted 에서 밑줄 fuel handle notch of M/E to 7." 친 단어와 뜻이 같은 것은?'
    ) == '"Adjusted fuel handle notch of M/E to 7."에서 밑줄 친 단어와 뜻이 같은 것은?'
    assert repair_extracted_text_artifacts(
        '"One of the bearings supporting the tunnel shafting is called the plumber block에서 밑줄 친." 부분과 같은 것은?'
    ) == '"One of the bearings supporting the tunnel shafting is called the plumber block."에서 밑줄 친 부분과 같은 것은?'
    assert repair_extracted_text_artifacts(
        '번 발전기의 태핏 간극을 재조정하였다 를 영문으로 "2 " 기재할 경우 에 알맞은 것은(   )? '
        '"Readjusted (   ) of No. 2 G/E."'
    ) == (
        '"2번 발전기의 태핏 간극을 재조정하였다."를 영문으로 기재할 경우 (   )에 알맞은 것은? '
        '"Readjusted (   ) of No. 2 G/E."'
    )
    assert repair_extracted_text_artifacts(
        '발전기 여자기 코일을 재권선 했다 를 영문으로 나"." 타낼 때 에 알맞은 것은(     )? '
        '"Rewound (     ) windings in the generator."'
    ) == (
        '"발전기 여자기 코일을 재권선했다."를 영문으로 나타낼 때 (     )에 알맞은 것은? '
        '"Rewound (     ) windings in the generator."'
    )
    assert repair_extracted_text_artifacts(
        '검사에 대비하여 중간축 베어링을 개방할 것 의 영문" " 표기로 에 알맞은 것은(   )? '
        '"No. 2 intermediate shaft bearing to be opened for (   )."'
    ) == (
        '"검사에 대비하여 중간축 베어링을 개방할 것"의 영문 표기로 (   )에 알맞은 것은? '
        '"No. 2 intermediate shaft bearing to be opened for (   )."'
    )


def test_repair_extracted_text_artifacts_rebuilds_remaining_korean_english_prompt_misorders():
    assert repair_extracted_text_artifacts(
        "협약 및 개정규정상 선박에서의 화재 및 폭발SOLAS의 예방을 위해 기름의 사용 제한에 대한 설명으로 옳지 않은 것은?"
    ) == "SOLAS 협약 및 개정규정상 선박에서의 화재 및 폭발의 예방을 위해 기름의 사용 제한에 대한 설명으로 옳지 않은 것은?"
    assert repair_extracted_text_artifacts("제어동작은 제어계의 무엇을 개선하기 위하여 사용PI되는가?") == (
        "PI 제어동작은 제어계의 무엇을 개선하기 위하여 사용되는가?"
    )
    assert repair_extracted_text_artifacts(
        "필리핀의 항 입항 중 관측할 수 있는 측방표지Manila의 색상으로 옳은 것은?"
    ) == "필리핀의 Manila항 입항 중 관측할 수 있는 측방표지의 색상으로 옳은 것은?"
    assert repair_extracted_text_artifacts(
        "협약에서 규정하고 있는 생존정의 적임증명서STCW를 발급받(Certificate of proficiency in survival craft)을 수 있는 선원의 최저 연령은?"
    ) == (
        "STCW 협약에서 규정하고 있는 생존정의 적임증명서(Certificate of proficiency in survival craft)를 "
        "발급받을 수 있는 선원의 최저 연령은?"
    )
    assert repair_extracted_text_artifacts(
        "협약상 퇴선 훈련에 포함되어야 할 사항이 아SOLAS닌 것은?"
    ) == "SOLAS 협약상 퇴선 훈련에 포함되어야 할 사항이 아닌 것은?"
    assert repair_extracted_text_artifacts(
        "협약에 의한 증서 및 설비기록부에 관한 설명SOLAS으로 옳은 것은?"
    ) == "SOLAS 협약에 의한 증서 및 설비기록부에 관한 설명으로 옳은 것은?"
    assert repair_extracted_text_artifacts(
        "협약상 선내 퇴선훈련의 내용으로 규정되어 있SOLAS지 않은 것은?"
    ) == "SOLAS 협약상 선내 퇴선훈련의 내용으로 규정되어 있지 않은 것은?"
    assert repair_extracted_text_artifacts(
        "협약상 소방원장구에 대한 설명으로 옳지 않SOLAS은 것은?"
    ) == "SOLAS 협약상 소방원장구에 대한 설명으로 옳지 않은 것은?"
    assert repair_extracted_text_artifacts(
        '에 적합한 것은(   )? 협약상 유조선에 장치된 에"SOLAS Inert gas system서 의 송풍 용량은 용량 Fan(Blower) Cargo oil pump 총합의 이상이어야 한다(   )."'
    ) == (
        '"SOLAS 협약상 유조선에 장치된 Inert gas system에서 Fan(Blower)의 송풍 용량은 '
        'Cargo oil pump 용량 총합의 (   ) 이상이어야 한다."에서 (   )에 적합한 것은?'
    )
    assert repair_extracted_text_artifacts(
        '에 적합한 것은(   )? 협약상 주조타기의 성능은 최대 항해 흘수에"SOLAS서 최대 항해 속력으로 전진 중에 한쪽 현 타각 도35에서 반대쪽 현 타각 도까지 이내에 전타 가30 (   ) 능하여야 한다."'
    ) == (
        '"SOLAS 협약상 주조타기의 성능은 최대 항해 흘수에서 최대 항해 속력으로 전진 중에 '
        '한쪽 현 타각 35도에서 반대쪽 현 타각 30도까지 (   ) 이내에 전타 가능하여야 한다."'
        '에서 (   )에 적합한 것은?'
    )
    assert repair_extracted_text_artifacts(
        '에 순서대로 적합한 것은(   )? 해양환경관리법상 근해구역 또는 원양구역을 운항하" 는 총톤수 톤 이상 톤 미만의 유조선에 1,000 10,000 비치하여야 하는 오일펜스 형의 길이는 선박길이의 B 배 또는 미터 중 큰 쪽의 길이이어야 한다(   ) (   )."'
    ) == (
        '"해양환경관리법상 근해구역 또는 원양구역을 운항하는 총톤수 1,000톤 이상 10,000톤 미만의 유조선에 '
        '비치하여야 하는 오일펜스 B형의 길이는 선박길이의 (   )배 또는 (   )미터 중 큰 쪽의 길이이어야 한다."'
        '에서 (   )에 순서대로 적합한 것은?'
    )
    assert repair_extracted_text_artifacts(
        '전자해도표시정보시스템 의 자선 심벌과 관련ECDIS() 된 설명으로 에 순서대로 적합한 것은(   )? '
        '" 화면상의 자선 위치는 해도의 축척이 확대되ECDIS면 자선의 윤곽선이 표시되는 방식이며 이는 선수방, '
        '위를 표시하는 과 정횡방향을 Heading line Beam line으로 표시하는 방식이 있다 은 윤곽선을. '
        'Beam line 표시할 경우 로부터 정횡위치를 표시하지만 심(   ), 벌 표시의 경우에는 에 표시한다(   )."'
    ) == (
        '전자해도표시정보시스템(ECDIS)의 자선 심벌과 관련된 설명으로 (   )에 순서대로 적합한 것은? '
        '"ECDIS 화면상의 자선 위치는 해도의 축척이 확대되면 자선의 윤곽선이 표시되는 방식이며 이는 선수방위를 '
        '표시하는 Heading line과 정횡방향을 Beam line으로 표시하는 방식이 있다. Beam line은 윤곽선을 표시할 경우 '
        '(   )로부터 정횡위치를 표시하지만 심벌 표시의 경우에는 (   )에 표시한다."'
    )
    assert repair_extracted_text_artifacts(
        '에 공통으로 적합한 것은(   )? 는 에 의하여 에 있는 "Snug Rudder pintle Rudder post에 연결되어 있고 은 항상 (   ), Rudder pintle (   ) 내에서 회전한다."'
    ) == (
        '(   )에 공통으로 적합한 것은? "Snug는 Rudder pintle에 의하여 Rudder post에 있는 (   )에 연결되어 있고, '
        'Rudder pintle은 항상 (   ) 내에서 회전한다."'
    )


def test_repair_extracted_text_artifacts_rebuilds_quoted_term_prompt_order():
    assert repair_extracted_text_artifacts('의 뜻은"Hydraulic control system"?') == (
        '"Hydraulic control system"의 뜻은?'
    )
    assert repair_extracted_text_artifacts('의 뜻은"Hydraulic power systems"?') == (
        '"Hydraulic power systems"의 뜻은?'
    )
    assert repair_extracted_text_artifacts('의 뜻은"A portable fire extinguisher"?') == (
        '"A portable fire extinguisher"의 뜻은?'
    )
    assert repair_extracted_text_artifacts('란"The classification society"?') == (
        '"The classification society"란?'
    )
    assert repair_extracted_text_artifacts('다음 중 와 가장 관련이 있는 기관은"scavenging port"?') == (
        '다음 중 "scavenging port"와 가장 관련이 있는 기관은?'
    )
    assert repair_extracted_text_artifacts('가 뜻하는 것은"Energy Efficiency Design Index(EEDI)"?') == (
        '"Energy Efficiency Design Index(EEDI)"가 뜻하는 것은?'
    )
    assert repair_extracted_text_artifacts('가 뜻하는 것"Energy Efficiency Design Index(EEDI)" 은?') == (
        '"Energy Efficiency Design Index(EEDI)"가 뜻하는 것은?'
    )
    assert repair_extracted_text_artifacts('가 아닌 것은"Lifesaving Appliances"?') == (
        '"Lifesaving Appliances"가 아닌 것은?'
    )
    assert repair_extracted_text_artifacts(
        '에서 "Took indicator cards for all cylinder of M/E" 에 속하는 것은"indicator cards"?'
    ) == '"Took indicator cards for all cylinder of M/E"에서 "indicator cards"에 속하는 것은?'
    assert repair_extracted_text_artifacts(
        '다음 중 이면서 동시"One revolution of crank shaft" 에 인 기관은 어느 것"Half revolution of cam shaft" 인가?'
    ) == (
        '다음 중 "One revolution of crank shaft"이면서 동시에 '
        '"Half revolution of cam shaft"인 기관은 어느 것인가?'
    )


def test_repair_extracted_text_artifacts_fixes_db_audit_numeric_and_latin_findings():
    assert repair_extracted_text_artifacts(
        "평형 상 교류에서 각상 기전력의 순시값을 모두 합3하면 그 크기는?"
    ) == "평형 3상 교류에서 각상 기전력의 순시값을 모두 합하면 그 크기는?"
    assert repair_extracted_text_artifacts(
        "선원법상 선박소유자는 선원에게 임의의 시간 동안24에 몇 시간 이상의 휴식시간을 부여하여야 하는가?"
    ) == "선원법상 선박소유자는 선원에게 임의의 24시간 동안에 몇 시간 이상의 휴식시간을 부여하여야 하는가?"
    assert repair_extracted_text_artifacts(
        "선박직원법령상 급 기관사 면허 소지자가 기관장으4로 승선할 수 없는 선박은?"
    ) == "선박직원법령상 4급 기관사 면허 소지자가 기관장으로 승선할 수 없는 선박은?"
    assert repair_extracted_text_artifacts(
        "선박을 점유하여 선박운항 중 제 자에게 손해3를 끼쳤다면 책임은 용선자에게 있다."
    ) == "선박을 점유하여 선박운항 중 제3자에게 손해를 끼쳤다면 책임은 용선자에게 있다."
    assert repair_extracted_text_artifacts(
        "기적이나 사이렌을 이용하여 연속 회의 단음7과 계속 회의 장음으로 한다1."
    ) == "기적이나 사이렌을 이용하여 연속 7회의 단음과 계속 1회의 장음으로 한다."
    assert repair_extracted_text_artifacts("컨테이너 화물운송에서 화물이란LCL?") == (
        "컨테이너 화물운송에서 LCL 화물이란?"
    )
    assert repair_extracted_text_artifacts("수화인의 이름을 기재하여 발행한 선하증권(Bill of은lading)?") == (
        "수화인의 이름을 기재하여 발행한 선하증권(Bill of lading)은?"
    )
    assert repair_extracted_text_artifacts(
        "상 구명부환은 담수 중에서 몇 의 철편을LSA code kg 달고서 시간 이상 떠 있을 수 있어야 하는가24?"
    ) == "LSA code상 구명부환은 담수 중에서 몇 kg의 철편을 달고서 24시간 이상 떠 있을 수 있어야 하는가?"


def test_repair_extracted_text_artifacts_fixes_residual_numeric_order_findings():
    assert repair_extracted_text_artifacts(
        "국제해상충돌방지규칙상 서로 시계 안에서 척의 동2 력선이 상대의 진로를 횡단할 경우 충돌의 위험이 있을 때 항법으로 옳지 않은 것은?"
    ) == (
        "국제해상충돌방지규칙상 서로 시계 안에서 2척의 동력선이 상대의 진로를 횡단할 경우 충돌의 위험이 있을 때 항법으로 옳지 않은 것은?"
    )
    assert repair_extracted_text_artifacts(
        "횡단상태 항법은 후진 중인 선박들 간에도 적 용한다."
    ) == "횡단상태 항법은 후진 중인 선박들 간에도 적용한다."
    assert repair_extracted_text_artifacts(
        "상 유도전동기에서 전원의 주파수가 저하하면 회전3 수와 전류는 어떻게 되는가 단 전원 전압의 크기는? (, 일정하다.)"
    ) == (
        "3상 유도전동기에서 전원의 주파수가 저하하면 회전수와 전류는 어떻게 되는가? (단, 전원 전압의 크기는 일정하다.)"
    )
    assert repair_extracted_text_artifacts(
        "전압 증폭률이 배인 증폭기의 증폭도를 이득으로 100 나타내면 몇 [dB]인가?"
    ) == "전압 증폭률이 100배인 증폭기의 증폭도를 이득으로 나타내면 몇 [dB]인가?"
    assert repair_extracted_text_artifacts(
        "국제해상충돌방지규칙상 제한된 시계 안에서 분을 2 넘지 아니하는 간격으로 장음 회와 단음 회 신호를 1 2 울려야 하는 선박이 아닌 것은 단 선박의 길이는? (, 미터 이상이다12.)"
    ) == (
        "국제해상충돌방지규칙상 제한된 시계 안에서 2분을 넘지 아니하는 간격으로 장음 1회와 단음 2회 신호를 울려야 하는 선박이 아닌 것은? (단, 선박의 길이는 12미터 이상이다.)"
    )
    assert repair_extracted_text_artifacts(
        "해양환경관리법령상 총톤수 톤 이상 만톤 미만의 400 1 선박으로 유조선이 아닌 선박의 기관구역에 설치하는기름오염방지설비가 아닌 것은?"
    ) == (
        "해양환경관리법령상 총톤수 400톤 이상 1만톤 미만의 선박으로 유조선이 아닌 선박의 기관구역에 설치하는 기름오염방지설비가 아닌 것은?"
    )
    assert repair_extracted_text_artifacts(
        "건강진단서는 발급일부터 최대 년간 유효하2 다 다만 세 미만의 선원의 경우 건강진단서. 16의 최대 유효기간은 년이다1."
    ) == (
        "건강진단서는 발급일부터 최대 2년간 유효하다. 다만 16세 미만의 선원의 경우 건강진단서의 최대 유효기간은 1년이다."
    )
    assert repair_extracted_text_artifacts(
        "길이 미터 이상의 예인선이 예인선열의 길50 이 미터를 초과하는 예인을 하고 있을 때200"
    ) == "길이 50미터 이상의 예인선이 예인선열의 길이 200미터를 초과하는 예인을 하고 있을 때"
    assert repair_extracted_text_artifacts(
        "총톤수 톤 이상의 모든 선박 및 승선인원 100 인 이상의 정원을 가진 모든 선박은 선원이 15 실행할 수 있는 폐기물 관리계획서를 비치하여야 한다."
    ) == (
        "총톤수 100톤 이상의 모든 선박 및 승선인원 15인 이상의 정원을 가진 모든 선박은 선원이 실행할 수 있는 폐기물 관리계획서를 비치하여야 한다."
    )
    assert repair_extracted_text_artifacts(
        "형상물로 가장 잘 보이는 곳에 수직선으로 원 뿔꼴 형상물 개를 그 꼭대기가 아래로 향하도2 록 표시한 선박이다."
    ) == "형상물로 가장 잘 보이는 곳에 수직선으로 원뿔꼴 형상물 2개를 그 꼭대기가 아래로 향하도록 표시한 선박이다."
    assert repair_extracted_text_artifacts(
        "협약 및 개정규정상 선박용 주기관의 연료로 SOLAS 사용할 수 있는 기름의 인화점에 대한 기준은?"
    ) == "SOLAS 협약 및 개정규정상 선박용 주기관의 연료로 사용할 수 있는 기름의 인화점에 대한 기준은?"
    assert repair_extracted_text_artifacts(
        "의 특성으로 볼 때 선박에서 부적합사항의 ISM code 식별 및 보고에 관한 업무는 누구의 소관이라고 할 수 있는가?"
    ) == "ISM code의 특성으로 볼 때 선박에서 부적합사항의 식별 및 보고에 관한 업무는 누구의 소관이라고 할 수 있는가?"
    assert repair_extracted_text_artifacts(
        "CFR 기관에 의해 비교 시험하는 방법20.12노트의 속력으로 달리고 있는 선박의 프로펠러 슬립이 20[%]였다면 프로펠러의 속도는 몇 노트인가?"
    ) == "CFR 기관에 의해 비교 시험하는 방법"
    assert repair_extracted_text_artifacts(
        "국제해상충돌방지규칙상 항행 중인 예인선이 마름모 꼴 형상물 개를 표시하여야 하는 예인선열의 길이 1기준은?"
    ) == "국제해상충돌방지규칙상 항행 중인 예인선이 마름모꼴 형상물 1개를 표시하여야 하는 예인선열의 길이 기준은?"
    assert repair_extracted_text_artifacts(
        "선박이 가로방향으로 도 경사하는 경우에22.5서도 기름이 넘치지 아니하는 구조일 것"
    ) == "선박이 가로방향으로 22.5도 경사하는 경우에서도 기름이 넘치지 아니하는 구조일 것"


def test_repair_extracted_text_artifacts_fixes_db_audit_formula_findings():
    assert repair_extracted_text_artifacts(
        "함수 f(t)=¯21sin2t의 라플라스 변환으로 옳은 것은?(단, s는 복소수이다.)"
    ) == "함수 f(t)=1/2 sin2t의 라플라스 변환으로 옳은 것은? (단, s는 복소수이다.)"
    assert repair_extracted_text_artifacts("¯s2+41") == "1/(s^2+4)"
    assert repair_extracted_text_artifacts("¯(s+2)22") == "2/(s+2)^2"
    assert repair_extracted_text_artifacts("¯s(s+2)2") == "2/(s(s+2))"
    assert repair_extracted_text_artifacts("K(1+¯T1s1)") == "K(1+1/(T1s))"
    assert repair_extracted_text_artifacts("¯E2E1=¯N2N1=¯I1I2") == "E1/E2=N1/N2=I2/I1"
    assert repair_extracted_text_artifacts("¯A+B=¯A∙¯B") == r"\overline{A+B}=\overline{A}∙\overline{B}"
    assert repair_extracted_text_artifacts("V=¯2V1+V2") == "V=(V1+V2)/2"
    assert repair_extracted_text_artifacts(
        "개루프 전달함수가 G(s)=¯(s+1)(s+2)10이고 단위피드백 시스템일 때 단위계단 입력에 대한 정상편차는?"
    ) == "개루프 전달함수가 G(s)=10/((s+1)(s+2))이고 단위피드백 시스템일 때 단위계단 입력에 대한 정상편차는?"


def test_normalize_latex_text_uses_repaired_private_math_glyphs():
    formatted = normalize_latex_text("P = \ue05c\ue06d\ue036 × \ue004 × \ue008 × cos\ue0a4")

    assert formatted.text == r"P=\sqrt{3} \times E \times I \times \cos\theta"
    assert formatted.spans == [
        {"start": 0, "end": len(formatted.text), "latex": formatted.text}
    ]


def test_normalize_latex_text_keeps_sqrt_radical_from_swallowing_following_text():
    formatted = normalize_latex_text("㉯(1/√2)배가")

    assert formatted.text == r"㉯(1/\sqrt{2})배가"
    assert formatted.spans == [
        {"start": 4, "end": 12, "latex": r"\sqrt{2}"}
    ]


def test_normalize_latex_text_limits_sqrt_digit_before_adjacent_formula_terms():
    formatted = normalize_latex_text("P가 \ue05c\ue06d\ue036EIcosθ일 때")

    assert formatted.text == r"P가 \sqrt{3}EIcosθ일 때"
    assert formatted.spans == [
        {"start": 3, "end": 11, "latex": r"\sqrt{3}"}
    ]


def test_normalize_latex_text_limits_sqrt_digit_before_adjacent_numbers():
    formatted = normalize_latex_text("e=√2200sin314t[V]")

    assert formatted.text == r"e=\sqrt{2}200sin314t[V]"
    assert formatted.spans == [
        {
            "start": 0,
            "end": len(r"e=\sqrt{2}200sin314t"),
            "latex": r"e=\sqrt{2}200sin314t",
        }
    ]
