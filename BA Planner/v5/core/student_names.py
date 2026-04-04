"""
student_names.py — 블루아카이브 학생 메타데이터 DB  (V5)

역할:
  - 학생 ID 목록 보관
  - 표시 이름 보관
  - 템플릿 파일명 보관
  - 코스튬 그룹(group) / 변형(variant) 보관

이 파일은 식별 로직을 포함하지 않는다.
학생 판정은 matcher.py 의 텍스처 매칭이 담당한다.
"""

from __future__ import annotations
from typing import TypedDict


# ── 학생 메타데이터 타입 ──────────────────────────────────
class StudentMeta(TypedDict):
    display_name:  str           # UI 표시용 최종 이름 ("시즈코(수영복)" 등)
    template_name: str           # templates/student_texture/ 아래 파일명
    group:         str           # 같은 캐릭터임을 나타내는 그룹 키 ("시즈코")
    variant:       str | None    # 코스튬/변형 태그 (없으면 None)


# ── 학생 메타데이터 DB ────────────────────────────────────
STUDENTS: dict[str, StudentMeta] = {

    # ── 아비도스 ─────────────────────────────────────────
    "ayane": {
        "display_name":  "아야네",
        "template_name": "ayane.png",
        "group":         "아야네",
        "variant":       None,
    },
    "ayane_swimsuit": {
        "display_name":  "아야네(수영복)",
        "template_name": "ayane_swimsuit.png",
        "group":         "아야네",
        "variant":       "수영복",
    },
    "hoshino": {
        "display_name":  "호시노",
        "template_name": "hoshino.png",
        "group":         "호시노",
        "variant":       None,
    },
    "hoshino_battle": {
        "display_name":  "호시노(무장)",
        "template_name": "hoshino_battle.png",
        "group":         "호시노",
        "variant":       "무장",
    },    
    "hoshino_swimsuit": {
        "display_name":  "호시노(수영복)",
        "template_name": "hoshino_swimsuit.png",
        "group":         "호시노",
        "variant":       "수영복",
    },
    "nonomi": {
        "display_name":  "노노미",
        "template_name": "nonomi.png",
        "group":         "노노미",
        "variant":       None,
    },
    "nonomi_swimsuit": {
        "display_name":  "노노미(수영복)",
        "template_name": "nonomi_swimsuit.png",
        "group":         "노노미",
        "variant":       "수영복",
    },
    "serika": {
        "display_name":  "세리카",
        "template_name": "serika.png",
        "group":         "세리카",
        "variant":       None,
    },
    "serika_new_year": {
        "display_name":  "세리카(새해)",
        "template_name": "serika_new_year.png",
        "group":         "세리카",
        "variant":       "새해",
    },
    "serika_swimsuit": {
        "display_name":  "세리카(수영복)",
        "template_name": "serika_swimsuit.png",
        "group":         "세리카",
        "variant":       "수영복",
    },
    "shiroko": {
        "display_name":  "시로코",
        "template_name": "shiroko.png",
        "group":         "시로코",
        "variant":       None,
    },
    "shiroko_riding": {
        "display_name":  "시로코(라이딩)",
        "template_name": "shiroko_ridingsuit.png",
        "group":         "시로코",
        "variant":       "라이딩",
    },
    "shiroko_swimsuit": {
        "display_name":  "시로코(수영복)",
        "template_name": "shiroko_swimsuit.png",
        "group":         "시로코",
        "variant":       "수영복",
    },
    "shiroko_terror": {
        "display_name":  "시로코*테러",
        "template_name": "shiroko_terror.png",
        "group":         "시로코",
        "variant":       "테러",
    },
    # ── 아리우스 ─────────────────────────────────────────
    "atsuko": {
        "display_name":  "아츠코",
        "template_name": "atsuko.png",
        "group":         "아츠코",
        "variant":       None,
    },
    "atsuko_swimsuit": {
        "display_name":  "아츠코(수영복)",
        "template_name": "atsuko_swimsuit.png",
        "group":         "아츠코",
        "variant":       "수영복",
    },
    "misaki": {
        "display_name":  "미사키",
        "template_name": "misaki.png",
        "group":         "미사키",
        "variant":       None,
    },
    "misaki_swimsuit": {
        "display_name":  "미사키(수영복)",
        "template_name": "misaki_swimsuit.png",
        "group":         "미사키",
        "variant":       "수영복",
    },
    "saori": {
        "display_name":  "사오리",
        "template_name": "saori.png",
        "group":         "사오리",
        "variant":       None,
    },
    "saori_dress": {
        "display_name":  "사오리(드레스)",
        "template_name": "saori_dress.png",
        "group":         "사오리",
        "variant":       "드레스",
    },
    "saori_swimsuit": {
        "display_name":  "사오리(수영복)",
        "template_name": "saori_swimsuit.png",
        "group":         "사오리",
        "variant":       "수영복",
    },
    "hiyori": {
        "display_name":  "히요리",
        "template_name": "hiyori.png",
        "group":         "히요리",
        "variant":       None,
    },
    "hiyori_swimsuit": {
        "display_name":  "히요리(수영복)",
        "template_name": "hiyori_swimsuit.png",
        "group":         "히요리",
        "variant":       "수영복",
    },
    "subaru": {
        "display_name":  "스바루",
        "template_name": "subaru.png",
        "group":         "스바루",
        "variant":       None,
    },

    # ── 게헨나 ───────────────────────────────────────────
    "akari": {
        "display_name":  "아카리",
        "template_name": "akari.png",
        "group":         "아카리",
        "variant":       None,
    },
    "akari_new_year": {
        "display_name":  "아카리(새해)",
        "template_name": "akari_new_year.png",
        "group":         "아카리",
        "variant":       "새해",
    },
    "ako": {
        "display_name":  "아코",
        "template_name": "ako.png",
        "group":         "아코",
        "variant":       None,
    },
    "ako_dress": {
        "display_name":  "아코(드레스)",
        "template_name": "ako_dress.png",
        "group":         "아코",
        "variant":       "드레스",
    },
    "aru": {
        "display_name":  "아루",
        "template_name": "aru.png",
        "group":         "아루",
        "variant":       None,
    },
    "aru_dress": {
        "display_name":  "아루(드레스)",
        "template_name": "aru_dress.png",
        "group":         "아루",
        "variant":       "드레스",
    },
    "aru_new_year": {
        "display_name":  "아루(새해)",
        "template_name": "aru_new_year.png",
        "group":         "아루",
        "variant":       "새해",
    },
    "chiaki": {
        "display_name":  "치아키",
        "template_name": "chiaki.png",
        "group":         "치아키",
        "variant":       None,
    },
    "chinatsu": {
        "display_name":  "치나츠",
        "template_name": "chinatsu.png",
        "group":         "치나츠",
        "variant":       None,
    },
    "chinatsu_hot_springs": {
        "display_name":  "치나츠(온천)",
        "template_name": "chinatsu_hot_springs.png",
        "group":         "치나츠",
        "variant":       "온천",
    },
    "fuuka": {
        "display_name":  "후우카",
        "template_name": "fuuka.png",
        "group":         "후우카",
        "variant":       None,
    },
    "fuuka_new_year": {
        "display_name":  "후우카(새해)",
        "template_name": "fuuka_new_year.png",
        "group":         "후우카",
        "variant":       "새해",
    },
    "haruka": {
        "display_name":  "하루카",
        "template_name": "haruka.png",
        "group":         "하루카",
        "variant":       None,
    },
    "haruka_new_year": {
        "display_name":  "하루카(새해)",
        "template_name": "haruka_new_year.png",
        "group":         "하루카",
        "variant":       "새해",
    },
    "haruna": {
        "display_name":  "하루나",
        "template_name": "haruna.png",
        "group":         "하루카",
        "variant":       None,
    },
    "haruna_new_year": {
        "display_name":  "하루나(새해)",
        "template_name": "haruna_new_year.png",
        "group":         "하루나",
        "variant":       "새해",
    },
    "haruna_sportswear": {
        "display_name":  "하루나(체육복)",
        "template_name": "haruna_sportswear.png",
        "group":         "하루나",
        "variant":       "체육복",
    },
    "hina": {
        "display_name":  "히나",
        "template_name": "hina.png",
        "group":         "히나",
        "variant":       None,
    },
    "hina_dress": {
        "display_name":  "히나(드레스)",
        "template_name": "hina_dress.png",
        "group":         "히나",
        "variant":       "드레스",
    },
    "hina_swimsuit": {
        "display_name":  "히나(수영복)",
        "template_name": "hina_swimsuit.png",
        "group":         "히나",
        "variant":       "수영복",
    },
    "ibuki": {
        "display_name":  "이부키",
        "template_name": "ibuki.png",
        "group":         "이부키",
        "variant":       None,
    },
    "iori": {
        "display_name":  "이오리",
        "template_name": "iori.png",
        "group":         "이오리",
        "variant":       None,
    },
    "iori_swimsuit": {
        "display_name":  "이오리(수영복)",
        "template_name": "iori_swimsuit.png",
        "group":         "이오리",
        "variant":       "수영복",
    },
    "iroha": {
        "display_name":  "이로하",
        "template_name": "iroha.png",
        "group":         "이로하",
        "variant":       None,
    },
    "izumi": {
        "display_name":  "이즈미",
        "template_name": "izumi.png",
        "group":         "이즈미",
        "variant":       None,
    },
    "izumi_new_year": {
        "display_name":  "이즈미(새해)",
        "template_name": "izumi_new_year.png",
        "group":         "이즈미",
        "variant":       "새해",
    },
    "izumi_swimsuit": {
        "display_name":  "이즈미(수영복)",
        "template_name": "izumi_swimsuit.png",
        "group":         "이즈미",
        "variant":       "수영복",
    },
    "zunko": {
        "display_name":  "준코",
        "template_name": "zunko.png",
        "group":         "준코",
        "variant":       None,
    },
    "zunko_new_year": {
        "display_name":  "준코(새해)",
        "template_name": "zunko_new_year.png",
        "group":         "준코",
        "variant":       "새해",
    },
    "juri": {
        "display_name":  "주리",
        "template_name": "juri.png",
        "group":         "주리",
        "variant":       None,
    },
    "juri_part_timer": {
        "display_name":  "주리(아르바이트)",
        "template_name": "juri_part_timer.png",
        "group":         "주리",
        "variant":       "아르바이트",
    },
    "kasumi": {
        "display_name":  "카스미",
        "template_name": "kasumi.png",
        "group":         "카스미",
        "variant":       None,
    },
    "kayoko": {
        "display_name":  "카요코",
        "template_name": "kayoko.png",
        "group":         "카요코",
        "variant":       None,
    },
    "kayoko_dress": {
        "display_name":  "카요코(드레스)",
        "template_name": "kayoko_dress.png",
        "group":         "카요코",
        "variant":       "드레스",
    },
    "kayoko_new_year": {
        "display_name":  "카요코(새해)",
        "template_name": "kayoko_new_year.png",
        "group":         "카요코",
        "variant":       "새해",
    },
    "kirara": {
        "display_name":  "키라라",
        "template_name": "kirara.png",
        "group":         "키라라",
        "variant":       None,
    },
    "makoto": {
        "display_name":  "마코토",
        "template_name": "makoto.png",
        "group":         "마코토",
        "variant":       None,
    },
    "megu": {
        "display_name":  "메구",
        "template_name": "megu.png",
        "group":         "메구",
        "variant":       None,
    },
    "mutsuki": {
        "display_name":  "무츠키",
        "template_name": "mutsuki.png",
        "group":         "무츠키",
        "variant":       None,
    },
    "mutsuki_new_year": {
        "display_name":  "무츠키(새해)",
        "template_name": "mutsuki_new_year.png",
        "group":         "무츠키",
        "variant":       "새해",
    },
    "satsuki": {
        "display_name":  "사츠키",
        "template_name": "satsuki.png",
        "group":         "사츠키",
        "variant":       None,
    },
    "sena": {
        "display_name":  "세나",
        "template_name": "sena.png",
        "group":         "세나",
        "variant":       None,
    },
    "sena_casual": {
        "display_name":  "세나(사복)",
        "template_name": "sena_casual.png",
        "group":         "세나",
        "variant":       "사복",
    },

    # ── 하이랜더 ─────────────────────────────────────────
    "aoba": {
        "display_name":  "아오바",
        "template_name": "aoba.png",
        "group":         "아오바",
        "variant":       None,
    },
    "hikari": {
        "display_name":  "히카리",
        "template_name": "hikari.png",
        "group":         "히카리",
        "variant":       None,
    },
    "nozomi": {
        "display_name":  "노조미",
        "template_name": "nozomi.png",
        "group":         "노조미",
        "variant":       None,
    },

    # ── 백귀야행 ─────────────────────────────────────────
    "chise": {
        "display_name":  "치세",
        "template_name": "chise.png",
        "group":         "치세",
        "variant":       None,
    },
    "chise_swimsuit": {
        "display_name":  "치세(수영복)",
        "template_name": "chise_swimsuit.png",
        "group":         "치세",
        "variant":       "수영복",
    },
    "izuna": {
        "display_name":  "이즈나",
        "template_name": "izuna.png",
        "group":         "이즈나",
        "variant":       None,
    },
    "izuna_swimsuit": {
        "display_name":  "이즈나(수영복)",
        "template_name": "izuna_swimsuit.png",
        "group":         "이즈나",
        "variant":       "수영복",
    },
    "kaede": {
        "display_name":  "카에데",
        "template_name": "kaede.png",
        "group":         "카에데",
        "variant":       None,
    },
    "kaho": {
        "display_name":  "카호",
        "template_name": "kaho.png",
        "group":         "카호",
        "variant":       None,
    },
    "kikyou": {
        "display_name":  "키쿄",
        "template_name": "kikyou.png",
        "group":         "키쿄",
        "variant":       None,
    },
    "kikyou_swimsuit": {
        "display_name":  "키쿄(수영복)",
        "template_name": "kikyou_swimsuit.png",
        "group":         "키쿄",
        "variant":       "수영복",
    },       
    "michiru": {
        "display_name":  "미치루",
        "template_name": "michiru.png",
        "group":         "미치루",
        "variant":       None,
    },       
    "michiru_dress": {
        "display_name":  "미치루(드레스)",
        "template_name": "michiru_dress.png",
        "group":         "미치루",
        "variant":       "드레스",
    },       
    "mimori": {
        "display_name":  "미모리",
        "template_name": "mimori.png",
        "group":         "미모리",
        "variant":       None,
    },       
    "mimori_swimsuit": {
        "display_name":  "미모리(수영복)",
        "template_name": "mimori_swimsuit.png",
        "group":         "미모리",
        "variant":       "수영복",
    },       
    "nagusa": {
        "display_name":  "나구사",
        "template_name": "nagusa.png",
        "group":         "나구사",
        "variant":       None,
    },       
    "niya": {
        "display_name":  "니야",
        "template_name": "niya.png",
        "group":         "니야",
        "variant":       None,
    },       
    "pina": {
        "display_name":  "피나",
        "template_name": "pina.png",
        "group":         "피나",
        "variant":       None,
    },       
    "pina_guide": {
        "display_name":  "피나(가이드)",
        "template_name": "pina_guide.png",
        "group":         "피나",
        "variant":       "가이드",
    },       
    "renge": {
        "display_name":  "렌게",
        "template_name": "renge.png",
        "group":         "렌게",
        "variant":       None,
    },       
    "renge_swimsuit": {
        "display_name":  "렌게(수영복)",
        "template_name": "renge_swimsuit.png",
        "group":         "렌게",
        "variant":       "수영복",
    },
    "shizuko": {
        "display_name":  "시즈코",
        "template_name": "shizuko.png",
        "group":         "시즈코",
        "variant":       None,
    },
    "shizuko_swimsuit": {
        "display_name":  "시즈코(수영복)",
        "template_name": "shizuko_swimsuit.png",
        "group":         "시즈코",
        "variant":       "수영복",
    },  
    "tsubaki": {
        "display_name":  "츠바키",
        "template_name": "tsubaki.png",
        "group":         "츠바키",
        "variant":       None,
    }, 
    "tsubaki_guide": {
        "display_name":  "츠바키(가이드)",
        "template_name": "tsubaki_guide.png",
        "group":         "츠바키",
        "variant":       "가이드",
    },
    "tsukuyo": {
        "display_name":  "츠쿠요",
        "template_name": "tsukuyo.png",
        "group":         "츠쿠요",
        "variant":       None,
    },
    "tsukuyo_dress": {
        "display_name":  "츠쿠요(드레스)",
        "template_name": "tsukuyo_dress.png",
        "group":         "츠쿠요",
        "variant":       "드레스",
    },
    "umika": {
        "display_name":  "우미카",
        "template_name": "umika.png",
        "group":         "우미카",
        "variant":       None,
    },
    "wakamo": {
        "display_name":  "와카모",
        "template_name": "wakamo.png",
        "group":         "와카모",
        "variant":       None,
    },
    "wakamo_swimsuit": {
        "display_name":  "와카모(수영복)",
        "template_name": "wakamo_swimsuit.png",
        "group":         "와카모",
        "variant":       "수영복",
    },
    "yukari": {
        "display_name":  "유카리",
        "template_name": "yukari.png",
        "group":         "유카리",
        "variant":       None,
    },
    "yukari_swimsuit": {
        "display_name":  "유카리(수영복)",
        "template_name": "yukari_swimsuit.png",
        "group":         "유카리",
        "variant":       "수영복",
    },
    # ── 밀레니엄 ─────────────────────────────────────────
    "akane": {
        "display_name":  "아카네",
        "template_name": "akane.png",
        "group":         "아카네",
        "variant":       None,
    },
    "akane_bunny_girl": {
        "display_name":  "아카네(바니걸)",
        "template_name": "akane_bunny_girl.png",
        "group":         "아카네",
        "variant":       "바니걸",
    },
    "akane_school_uniform": {
        "display_name":  "아카네(교복)",
        "template_name": "akane_school_uniform.png",
        "group":         "아카네",
        "variant":       "교복",
    },
    "aris": {
        "display_name":  "아리스",
        "template_name": "aris.png",
        "group":         "아리스",
        "variant":       None,
    },
    "aris_battle": {
        "display_name":  "아리스(무장)",
        "template_name": "aris_battle.png",
        "group":         "아리스",
        "variant":       "무장",
    },
    "aris_maid": {
        "display_name":  "아리스(메이드)",
        "template_name": "aris_maid.png",
        "group":         "아리스",
        "variant":       "메이드",
    },
    "asuna": {
        "display_name":  "아스나",
        "template_name": "asuna.png",
        "group":         "아스나",
        "variant":       None,
    },
    "asuna_bunny_girl": {
        "display_name":  "아스나(바니걸)",
        "template_name": "asuna_bunny_girl.png",
        "group":         "아스나",
        "variant":       "바니걸",
    },
    "asuna_school_uniform": {
        "display_name":  "아스나(교복)",
        "template_name": "asuna_school_uniform.png",
        "group":         "아스나",
        "variant":       "교복",
    },
    "chihiro": {
        "display_name":  "치히로",
        "template_name": "chihiro.png",
        "group":         "치히로",
        "variant":       None,
    },
    "eimi": {
        "display_name":  "에이미",
        "template_name": "eimi.png",
        "group":         "에이미",
        "variant":       None,
    },
    "eimi_battle": {
        "display_name":  "에이미(무장)",
        "template_name": "eimi_battle.png",
        "group":         "에이미",
        "variant":       "무장",
    },
    "eimi_swimsuit": {
        "display_name":  "에이미(수영복)",
        "template_name": "eimi_swimsuit.png",
        "group":         "에이미",
        "variant":       "수영복",
    },
    "hare": {
        "display_name":  "하레",
        "template_name": "hare.png",
        "group":         "하레",
        "variant":       None,
    },
    "hare_camping": {
        "display_name":  "하레(캠핑)",
        "template_name": "hare_camping.png",
        "group":         "하레",
        "variant":       "캠핑",
    },
    "hibiki": {
        "display_name":  "히비키",
        "template_name": "hibiki.png",
        "group":         "히비키",
        "variant":       None,
    },
    "hibiki_cheerleader": {
        "display_name":  "히비키(치어리더)",
        "template_name": "hibiki_cheerleader.png",
        "group":         "히비키",
        "variant":       "치어리더",
    },
    "himari": {
        "display_name":  "히마리",
        "template_name": "himari.png",
        "group":         "히마리",
        "variant":       None,
    },
    "himari_battle": {
        "display_name":  "히마리(무장)",
        "template_name": "himari_battle.png",
        "group":         "히마리",
        "variant":       "무장",
    },
    "karin": {
        "display_name":  "카린",
        "template_name": "karin.png",
        "group":         "카린",
        "variant":       None,
    },
    "karin_bunny_girl": {
        "display_name":  "카린(바니걸)",
        "template_name": "karin_bunny_girl.png",
        "group":         "카린",
        "variant":       "바니걸",
    },
    "karin_school_uniform": {
        "display_name":  "카린(교복)",
        "template_name": "karin_school_uniform.png",
        "group":         "카린",
        "variant":       "교복",
    },
    "kei": {
        "display_name":  "케이",
        "template_name": "kei.png",
        "group":         "케이",
        "variant":       None,
    },
    "kotama": {
        "display_name":  "코타마",
        "template_name": "kotama.png",
        "group":         "코타마",
        "variant":       None,
    },
    "kotama_camping": {
        "display_name":  "코타마(캠핑)",
        "template_name": "kotama_camping.png",
        "group":         "코타마",
        "variant":       "캠핑",
    },
    "kotori": {
        "display_name":  "코토리",
        "template_name": "kotori.png",
        "group":         "코토리",
        "variant":       None,
    },
    "kotori_cheerleader": {
        "display_name":  "코토리(치어리더)",
        "template_name": "kotori_cheerleader.png",
        "group":         "코토리",
        "variant":       "치어리더",
    },
    "koyuki": {
        "display_name":  "코유키",
        "template_name": "koyuki.png",
        "group":         "코유키",
        "variant":       None,
    },
    "koyuki_pajama": {
        "display_name":  "코유키(파자마)",
        "template_name": "koyuki_pajama.png",
        "group":         "코유키",
        "variant":       "파자마",
    },
    "maki": {
        "display_name":  "마키",
        "template_name": "maki.png",
        "group":         "마키",
        "variant":       None,
    },
    "maki_camping": {
        "display_name":  "마키(캠핑)",
        "template_name": "maki_camping.png",
        "group":         "마키",
        "variant":       "캠핑",
    },
    "midori": {
        "display_name":  "미도리",
        "template_name": "midori.png",
        "group":         "미도리",
        "variant":       None,
    },
    "midori_maid": {
        "display_name":  "미도리(메이드)",
        "template_name": "midori_maid.png",
        "group":         "미도리",
        "variant":       "메이드",
    },
    "momoi": {
        "display_name":  "모모이",
        "template_name": "momoi.png",
        "group":         "모모이",
        "variant":       None,
    },
    "momoi_maid": {
        "display_name":  "모모이(메이드)",
        "template_name": "momoi_maid.png",
        "group":         "모모이",
        "variant":       "메이드",
    },
    "neru": {
        "display_name":  "네루",
        "template_name": "neru.png",
        "group":         "네루",
        "variant":       None,
    },
    "neru_bunny_girl": {
        "display_name":  "네루(바니걸)",
        "template_name": "neru_bunny_girl.png",
        "group":         "네루",
        "variant":       "바니걸",
    },
    "neru_school_uniform": {
        "display_name":  "네루(교복)",
        "template_name": "neru_school_uniform.png",
        "group":         "네루",
        "variant":       "교복",
    },
    "noa": {
        "display_name":  "노아",
        "template_name": "noa.png",
        "group":         "노아",
        "variant":       None,
    },
    "noa_pajama": {
        "display_name":  "노아(파자마)",
        "template_name": "noa_pajama.png",
        "group":         "노아",
        "variant":       "파자마",
    },
    "rei": {
        "display_name":  "레이",
        "template_name": "rei.png",
        "group":         "레이",
        "variant":       None,
    },
    "rio": {
        "display_name":  "리오",
        "template_name": "rio.png",
        "group":         "리오",
        "variant":       None,
    },
    "rio_battle": {
        "display_name":  "리오(무장)",
        "template_name": "rio_battle.png",
        "group":         "리오",
        "variant":       "무장",
    },
    "sumire": {
        "display_name":  "스미레",
        "template_name": "sumire.png",
        "group":         "스미레",
        "variant":       None,
    },
    "sumire_part_timer": {
        "display_name":  "스미레(아르바이트)",
        "template_name": "sumire_part_timer.png",
        "group":         "스미레",
        "variant":       "아르바이트",
    },
    "toki": {
        "display_name":  "토키",
        "template_name": "toki.png",
        "group":         "토키",
        "variant":       None,
    },
    "toki_battle": {
        "display_name":  "토키(무장)",
        "template_name": "toki_battle.png",
        "group":         "토키",
        "variant":       "무장",
    },
    "toki_bunny_girl": {
        "display_name":  "토키(바니걸)",
        "template_name": "toki_bunny_girl.png",
        "group":         "토키",
        "variant":       "바니걸",
    },
    "utaha": {
        "display_name":  "우타하",
        "template_name": "utaha.png",
        "group":         "우타하",
        "variant":       None,
    },
    "utaha_cheerleader": {
        "display_name":  "우타하(치어리더)",
        "template_name": "utaha_cheerleader.png",
        "group":         "우타하",
        "variant":       "치어리더",
    },
    "yuuka": {
        "display_name":  "유우카",
        "template_name": "yuuka.png",
        "group":         "유우카",
        "variant":       None,
    },
    "yuuka_pajama": {
        "display_name":  "유우카(파자마)",
        "template_name": "yuuka_pajama.png",
        "group":         "유우카",
        "variant":       "파자마",
    },
    "yuuka_sportswear": {
        "display_name":  "유우카(체육복)",
        "template_name": "yuuka_sportswear.png",
        "group":         "유우카",
        "variant":       "체육복",
    },
    "yuzu": {
        "display_name":  "유즈",
        "template_name": "yuzu.png",
        "group":         "유즈",
        "variant":       None,
    },
    "yuzu_battle": {
        "display_name":  "유즈(무장)",
        "template_name": "yuzu_battle.png",
        "group":         "유즈",
        "variant":       "무장",
    },
    "yuzu_maid": {
        "display_name":  "유즈(메이드)",
        "template_name": "yuzu_maid.png",
        "group":         "유즈",
        "variant":       "메이드",
    },
    # ── 레드윈터 ─────────────────────────────────────────
    "cherino": {
        "display_name":  "체리노",
        "template_name": "cherino.png",
        "group":         "체리노",
        "variant":       None,
    },
    "cherino_hot_springs": {
        "display_name":  "체리노(온천)",
        "template_name": "cherino_hot_springs.png",
        "group":         "체리노",
        "variant":       "온천",
    },
    "marina": {
        "display_name":  "마리나",
        "template_name": "marina.png",
        "group":         "마리나",
        "variant":       None,
    },
    "marina_qipao": {
        "display_name":  "마리나(치파오)",
        "template_name": "marina_qipao.png",
        "group":         "마리나",
        "variant":       "치파오",
    },
    "meru": {
        "display_name":  "메루",
        "template_name": "meru.png",
        "group":         "메루",
        "variant":       None,
    },
    "minori": {
        "display_name":  "미노리",
        "template_name": "minori.png",
        "group":         "미노리",
        "variant":       None,
    },
    "momiji": {
        "display_name":  "모미지",
        "template_name": "momiji.png",
        "group":         "모미지",
        "variant":       None,
    },
    "nodoka": {
        "display_name":  "노도카",
        "template_name": "nodoka.png",
        "group":         "노도카",
        "variant":       None,
    },
    "nodoka_hot_springs": {
        "display_name":  "노도카(온천)",
        "template_name": "nodoka_hot_springs.png",
        "group":         "노도카",
        "variant":       "온천",
    },
    "shigure": {
        "display_name":  "시구레",
        "template_name": "shigure.png",
        "group":         "시구레",
        "variant":       None,
    },
    "shigure_hot_springs": {
        "display_name":  "시구레(온천)",
        "template_name": "shigure_hot_springs.png",
        "group":         "시구레",
        "variant":       "온천",
    },
    "takane": {
        "display_name":  "타카네",
        "template_name": "takane.png",
        "group":         "타카네",
        "variant":       None,
    },
    "tomoe": {
        "display_name":  "토모에",
        "template_name": "tomoe.png",
        "group":         "토모에",
        "variant":       None,
    },
    "tomoe_qipao": {
        "display_name":  "토모에(치파오)",
        "template_name": "tomoe_qipao.png",
        "group":         "토모에",
        "variant":       "치파오",
    },
    "yakumo": {
        "display_name":  "야쿠모",
        "template_name": "yakumo.png",
        "group":         "야쿠모",
        "variant":       None,
    },    
    # ── 산해경 ───────────────────────────────────────────
    "kisaki": {
        "display_name":  "키사키",
        "template_name": "kisaki.png",
        "group":         "키사키",
        "variant":       None,
    },
    "kokona": {
        "display_name":  "코코나",
        "template_name": "kokona.png",
        "group":         "코코나",
        "variant":       None,
    },
    "mina": {
        "display_name":  "미나",
        "template_name": "mina.png",
        "group":         "미나",
        "variant":       None,
    },
    "reijo": {
        "display_name":  "레이죠",
        "template_name": "reizyo.png",
        "group":         "레이죠",
        "variant":       None,
    },
    "rumi": {
        "display_name":  "루미",
        "template_name": "rumi.png",
        "group":         "루미",
        "variant":       None,
    },
    "saya": {
        "display_name":  "사야",
        "template_name": "saya.png",
        "group":         "사야",
        "variant":       None,
    },
    "saya_casual": {
        "display_name":  "사야(사복)",
        "template_name": "saya_casual.png",
        "group":         "사야",
        "variant":       "사복",
    },
    "shun": {
        "display_name":  "슌",
        "template_name": "shun.png",
        "group":         "슌",
        "variant":       None,
    },
    "shun_kid": {
        "display_name":  "슌(어린이)",
        "template_name": "shun_kid.png",
        "group":         "슌",
        "variant":       "어린이",
    },
    # ── SRT ─────────────────────────────────────────────
    "miyako": {
        "display_name":  "미야코",
        "template_name": "miyako.png",
        "group":         "미야코",
        "variant":       None,
    },
    "miyako_swimsuit": {
        "display_name":  "미야코(수영복)",
        "template_name": "miyako_swimsuit.png",
        "group":         "미야코",
        "variant":       "수영복",
    },
    "miyu": {
        "display_name":  "미유",
        "template_name": "miyu.png",
        "group":         "미유",
        "variant":       None,
    },
    "miyu_swimsuit": {
        "display_name":  "미유(수영복)",
        "template_name": "miyu_swimsuit.png",
        "group":         "미유",
        "variant":       "수영복",
    },
    "moe": {
        "display_name":  "모에",
        "template_name": "moe.png",
        "group":         "모에",
        "variant":       None,
    },
    "moe_swimsuit": {
        "display_name":  "모에(수영복)",
        "template_name": "moe_swimsuit.png",
        "group":         "모에",
        "variant":       "수영복",
    },
    "saki": {
        "display_name":  "사키",
        "template_name": "saki.png",
        "group":         "사키",
        "variant":       None,
    },
    "saki_swimsuit": {
        "display_name":  "사키(수영복)",
        "template_name": "saki_swimsuit.png",
        "group":         "사키",
        "variant":       "수영복",
    },
    # ── 트리니티 ─────────────────────────────────────────
    "airi": {
        "display_name":  "아이리",
        "template_name": "airi.png",
        "group":         "아이리",
        "variant":       None,
    },
    "airi_band": {
        "display_name":  "아이리(밴드)",
        "template_name": "airi_band.png",
        "group":         "아이리",
        "variant":       "밴드",
    },
    "azusa": {
        "display_name":  "아즈사",
        "template_name": "azusa.png",
        "group":         "아즈사",
        "variant":       None,
    },
    "azusa_swimsuit": {
        "display_name":  "아즈사(수영복)",
        "template_name": "azusa_swimsuit.png",
        "group":         "아즈사",
        "variant":       "수영복",
    },
    "hanae": {
        "display_name":  "하나에",
        "template_name": "hanae.png",
        "group":         "하나에",
        "variant":       None,
    },
    "hanae_christmas": {
        "display_name":  "하나에(크리스마스)",
        "template_name": "hanae_christmas.png",
        "group":         "하나에",
        "variant":       "크리스마스",
    },
    "hanako": {
        "display_name":  "하나코",
        "template_name": "hanako.png",
        "group":         "하나코",
        "variant":       None,
    },
    "hanako_swimsuit": {
        "display_name":  "하나코(수영복)",
        "template_name": "hanako_swimsuit.png",
        "group":         "하나코",
        "variant":       "수영복",
    },
    "hasumi": {
        "display_name":  "하스미",
        "template_name": "hasumi.png",
        "group":         "하스미",
        "variant":       None,
    },
    "hasumi_sportswear": {
        "display_name":  "하스미(체육복)",
        "template_name": "hasumi_sportswear.png",
        "group":         "하스미",
        "variant":       "체육복",
    },
    "hasumi_swimsuit": {
        "display_name":  "하스미(수영복)",
        "template_name": "hasumi_swimsuit.png",
        "group":         "하스미",
        "variant":       "수영복",
    },
    "hifumi": {
        "display_name":  "히후미",
        "template_name": "hifumi.png",
        "group":         "히후미",
        "variant":       None,
    },
    "hifumi_swimsuit": {
        "display_name":  "히후미(수영복)",
        "template_name": "hifumi_swimsuit.png",
        "group":         "히후미",
        "variant":       "수영복",
    },
    "hinata": {
        "display_name":  "히나타",
        "template_name": "hinata.png",
        "group":         "히나타",
        "variant":       None,
    },
    "hinata_swimsuit": {
        "display_name":  "히나타(수영복)",
        "template_name": "hinata_swimsuit.png",
        "group":         "히나타",
        "variant":       "수영복",
    },
    "ichika": {
        "display_name":  "이치카",
        "template_name": "ichika.png",
        "group":         "이치카",
        "variant":       None,
    },
    "ichika_swimsuit": {
        "display_name":  "이치카(수영복)",
        "template_name": "ichika_swimsuit.png",
        "group":         "이치카",
        "variant":       "수영복",
    },
    "kazusa": {
        "display_name":  "카즈사",
        "template_name": "kazusa.png",
        "group":         "카즈사",
        "variant":       None,
    },
    "kazusa_band": {
        "display_name":  "카즈사(밴드)",
        "template_name": "kazusa_band.png",
        "group":         "카즈사",
        "variant":       "밴드",
    },
    "koharu": {
        "display_name":  "코하루",
        "template_name": "koharu.png",
        "group":         "코하루",
        "variant":       None,
    },
    "koharu_swimsuit": {
        "display_name":  "코하루(수영복)",
        "template_name": "koharu_swimsuit.png",
        "group":         "코하루",
        "variant":       "수영복",
    },
    "mari": {
        "display_name":  "마리",
        "template_name": "mari.png",
        "group":         "마리",
        "variant":       None,
    },
    "mari_idol": {
        "display_name":  "마리(아이돌)",
        "template_name": "mari_idol.png",
        "group":         "마리",
        "variant":       "아이돌",
    },
    "mari_sportswear": {
        "display_name":  "마리(체육복)",
        "template_name": "mari_sportswear.png",
        "group":         "마리",
        "variant":       "체육복",
    },
    "mashiro": {
        "display_name":  "마시로",
        "template_name": "mashiro.png",
        "group":         "마시로",
        "variant":       None,
    },
    "mashiro_swimsuit": {
        "display_name":  "마시로(수영복)",
        "template_name": "mashiro_swimsuit.png",
        "group":         "마시로",
        "variant":       "수영복",
    },
    "mika": {
        "display_name":  "미카",
        "template_name": "mika.png",
        "group":         "미카",
        "variant":       None,
    },
    "mika_swimsuit": {
        "display_name":  "미카(수영복)",
        "template_name": "mika_swimsuit.png",
        "group":         "미카",
        "variant":       "수영복",
    },
    "mine": {
        "display_name":  "미네",
        "template_name": "mine.png",
        "group":         "미네",
        "variant":       None,
    },
    "mine_idol": {
        "display_name":  "미네(아이돌)",
        "template_name": "mine_idol.png",
        "group":         "미네",
        "variant":       "아이돌",
    },
    "nagisa": {
        "display_name":  "나기사",
        "template_name": "nagisa.png",
        "group":         "나기사",
        "variant":       None,
    },
    "nagisa_swimsuit": {
        "display_name":  "나기사(수영복)",
        "template_name": "nagisa_swimsuit.png",
        "group":         "나기사",
        "variant":       "수영복",
    },
    "natsu": {
        "display_name":  "나츠",
        "template_name": "natsu.png",
        "group":         "나츠",
        "variant":       None,
    },
    "natsu_band": {
        "display_name":  "나츠(밴드)",
        "template_name": "natsu_band.png",
        "group":         "나츠",
        "variant":       "밴드",
    },
    "rabu": {
        "display_name":  "라브",
        "template_name": "rabu.png",
        "group":         "라브",
        "variant":       None,
    },
    "reisa": {
        "display_name":  "레이사",
        "template_name": "reisa.png",
        "group":         "레이사",
        "variant":       None,
    },
    "reisa_magical": {
        "display_name":  "레이사(매지컬)",
        "template_name": "reisa_magical.png",
        "group":         "레이사",
        "variant":       "매지컬",
    },
    "sakurako": {
        "display_name":  "사쿠라코",
        "template_name": "sakurako.png",
        "group":         "사쿠라코",
        "variant":       None,
    },
    "sakurako_idol": {
        "display_name":  "사쿠라코(아이돌)",
        "template_name": "sakurako_idol.png",
        "group":         "사쿠라코",
        "variant":       "아이돌",
    },
    "seia": {
        "display_name":  "세이아",
        "template_name": "seia.png",
        "group":         "세이아",
        "variant":       None,
    },
    "seia_swimsuit": {
        "display_name":  "세이아(수영복)",
        "template_name": "seia_swimsuit.png",
        "group":         "세이아",
        "variant":       "수영복",
    },
    "serina": {
        "display_name":  "세리나",
        "template_name": "serina.png",
        "group":         "세리나",
        "variant":       None,
    },
    "serina_christmas": {
        "display_name":  "세리나(크리스마스)",
        "template_name": "serina_christmas.png",
        "group":         "세리나",
        "variant":       "크리스마스",
    },
    "shimiko": {
        "display_name":  "시미코",
        "template_name": "shimiko.png",
        "group":         "시미코",
        "variant":       None,
    },
    "suzumi": {
        "display_name":  "스즈미",
        "template_name": "suzumi.png",
        "group":         "스즈미",
        "variant":       None,
    },
    "suzumi_magical": {
        "display_name":  "스즈미(매지컬)",
        "template_name": "suzumi_magical.png",
        "group":         "스즈미",
        "variant":       "매지컬",
    },
    "tsurugi": {
        "display_name":  "츠루기",
        "template_name": "tsurugi.png",
        "group":         "츠루기",
        "variant":       None,
    },
    "tsurugi_swimsuit": {
        "display_name":  "츠루기(수영복)",
        "template_name": "tsurugi_swimsuit.png",
        "group":         "츠루기",
        "variant":       "수영복",
    },
    "ui": {
        "display_name":  "우이",
        "template_name": "ui.png",
        "group":         "우이",
        "variant":       None,
    },
    "ui_swimsuit": {
        "display_name":  "우이(수영복)",
        "template_name": "ui_swimsuit.png",
        "group":         "우이",
        "variant":       "수영복",
    },
    "yoshimi": {
        "display_name":  "요시미",
        "template_name": "yoshimi.png",
        "group":         "요시미",
        "variant":       None,
    },
    "yoshimi_band": {
        "display_name":  "요시미(밴드)",
        "template_name": "yoshimi_band.png",
        "group":         "요시미",
        "variant":       "밴드",
    },
    # ── 발키리 ───────────────────────────────────────────
    "fubuki": {
        "display_name":  "후부키",
        "template_name": "fubuki.png",
        "group":         "후부키",
        "variant":       None,
    },
    "fubuki_swimsuit": {
        "display_name":  "후부키(수영복)",
        "template_name": "fubuki_swimsuit.png",
        "group":         "후부키",
        "variant":       "수영복",
    },
    "kanna": {
        "display_name":  "칸나",
        "template_name": "kanna.png",
        "group":         "칸나",
        "variant":       None,
    },
    "kanna_swimsuit": {
        "display_name":  "칸나(수영복)",
        "template_name": "kanna_swimsuit.png",
        "group":         "칸나",
        "variant":       "수영복",
    },
    "kirino": {
        "display_name":  "키리노",
        "template_name": "kirino.png",
        "group":         "키리노",
        "variant":       None,
    },
    "kirino_swimsuit": {
        "display_name":  "키리노(수영복)",
        "template_name": "kirino_swimsuit.png",
        "group":         "키리노",
        "variant":       "수영복",
    },
    "konoka": {
        "display_name":  "코노카",
        "template_name": "konoka.png",
        "group":         "코노카",
        "variant":       None,
    },
    # ── 와일드헌트 ───────────────────────────────────────
    "eri": {
        "display_name":  "에리",
        "template_name": "eri.png",
        "group":         "에리",
        "variant":       None,
    },
    "fuyu": {
        "display_name":  "후유",
        "template_name": "fuyu.png",
        "group":         "후유",
        "variant":       None,
    },
    "kanoe": {
        "display_name":  "카노에",
        "template_name": "kanoe.png",
        "group":         "카노에",
        "variant":       None,
    },
    "miyo": {
        "display_name":  "미요",
        "template_name": "miyo.png",
        "group":         "미요",
        "variant":       None,
    },
    "rena": {
        "display_name":  "레나",
        "template_name": "rena.png",
        "group":         "레나",
        "variant":       None,
    },
    "ritsu": {
        "display_name":  "리츠",
        "template_name": "ritsu.png",
        "group":         "리츠",
        "variant":       None,
    },    
    # ── 콜라보 ───────────────────────────────────────────
    "hatsune_miku": {
        "display_name":  "하츠네 미쿠",
        "template_name": "hatsune_miku.png",
        "group":         "하츠네 미쿠",
        "variant":       None,
    },
    "misaka_mikoto": {
        "display_name":  "미사카 미코토",
        "template_name": "misaka_mikoto.png",
        "group":         "미사카 미코토",
        "variant":       None,
    },
    "shoukouhou_misaki": {
        "display_name":  "쇼쿠호 미사키",
        "template_name": "shoukouhou_misaki.png",
        "group":         "쇼쿠호 미사키",
        "variant":       None,
    },
    "saten_ruiko": {
        "display_name":  "사텐 루이코",
        "template_name": "saten_ruiko.png",
        "group":         "사텐 루이코",
        "variant":       None,
    },
}


# ── 조회 유틸 ─────────────────────────────────────────────

def get(student_id: str) -> StudentMeta | None:
    """student_id 로 메타데이터 조회. 없으면 None."""
    return STUDENTS.get(student_id)


def display_name(student_id: str) -> str:
    """
    student_id → 표시 이름.
    DB에 없는 미등록 ID는 ID 문자열 그대로 반환.
    """
    meta = STUDENTS.get(student_id)
    return meta["display_name"] if meta else student_id


def template_path(student_id: str) -> str:
    """
    student_id → template_name.
    DB에 없으면 '{student_id}.png' 를 fallback으로 반환.
    """
    meta = STUDENTS.get(student_id)
    return meta["template_name"] if meta else f"{student_id}.png"


def group(student_id: str) -> str | None:
    """같은 캐릭터 그룹 키 반환."""
    meta = STUDENTS.get(student_id)
    return meta["group"] if meta else None


def variant(student_id: str) -> str | None:
    """코스튬/변형 태그 반환. 기본복이거나 미등록이면 None."""
    meta = STUDENTS.get(student_id)
    return meta["variant"] if meta else None


def all_ids() -> list[str]:
    """등록된 모든 student_id 목록."""
    return list(STUDENTS.keys())


def ids_in_group(group_name: str) -> list[str]:
    """같은 group 을 가진 모든 student_id 목록."""
    return [sid for sid, m in STUDENTS.items() if m["group"] == group_name]
