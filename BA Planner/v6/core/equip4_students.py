"""
core/equip4_students.py — 4번 장비(T2 상한) 장착 가능 학생 목록

게임 내에서 4번 슬롯 장비를 장착할 수 있는 학생은 한정적.
이 목록에 포함된 학생만 equip4 스캔 + T2 최대값 판정을 수행.
포함되지 않은 학생은 equip4 스킵 처리.

업데이트 방법:
  EQUIP4_STUDENT_IDS 에 student_id 추가/제거
"""

# equip4 장착 가능 student_id 집합
# ※ 현재 확인된 목록 — 추후 업데이트 필요
EQUIP4_STUDENT_IDS: frozenset[str] = frozenset({
    # 아비도스
    "shiroko",
    "serika",
    "nonomi",
    "hoshino",
    # 아리우스
    "misaki",
    "saori",
    # 게헨나
    "aru",
    "zunko",
    "izumi",
    "hina_swimsuit",
    "izumi_swimsuit",
    "hina",
    "iori_swimsuit",
    "chinatsu",
    "haruna_sportswear",
    "kirara",
    # 밀레니엄
    "asuna_bunny_girl",
    "yuuka",
    "hare",
    "utaha",
    "neru",
    "eimi",
    "sumire",
    "aris_maid",
    "hibiki",
    "toki",
    "kotori",
    "midori",
    "koyuki",
    "momoi",
    "aris",
    "yuzu",
    "asuna",
    # 트리니티
    "tsurugi",
    "hinata",
    "suzumi",
    "hifumi_swimsuit",
    "hanako",
    "hanae_christmas",
    "yoshimi",
    "mari",
    "mashiro",
    "hasumi",
    "kazusa_band",
    # 레드윈터
    "cherino_hot_springs",
    "momiji",
    # 백귀야행
    "wakamo",
    "mimori",
    "chise_swimsuit",
    "kaho",
    "kaede",
    "chise",
    "shizuko",
    "wakamo_swimsuit",
    "renge",
    "umika",
    "michiru",
    # 발키리
    # SRT
    "miyako",
    "miyu",
    "saki",
    "moe",
    # 산해경
    "shun_kid",
    "saya_casual",
    # 와일드헌트
})


def has_equip4(student_id: str) -> bool:
    """해당 학생이 equip4 슬롯을 보유하는지 반환."""
    return student_id in EQUIP4_STUDENT_IDS


# equip4 최대 티어
EQUIP4_MAX_TIER = "T2"
