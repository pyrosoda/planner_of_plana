# GUI Element Glossary

이 문서는 BA Planner v6 GUI를 수정하거나 설명할 때 사용할 공식 명칭을 정의한다.
앞으로 GUI 관련 요청에서는 아래의 `canonical name`을 우선 사용한다.

## Naming Rules

- `Viewer`는 PySide6 기반의 독립 학생 뷰어 창을 뜻한다. 코드 위치: `gui/viewer_app_qt.py`.
- `Control Shell`은 Tk 기반의 스캔 제어 앱과 오버레이를 뜻한다. 코드 위치: `main.py`, `gui/floating.py`.
- `Dialog`는 특정 작업을 위해 잠깐 열리는 모달/보조 창을 뜻한다.
- `Panel`은 테두리와 배경을 가진 큰 영역이다.
- `Section`은 패널 안의 의미 단위이다.
- `Band`는 한 줄짜리 입력/정보 행이다.
- `Card`는 반복되는 개별 항목이다. 예: 학생 카드, 통계 카드, 인벤토리 아이템 카드.
- `Toolbar`는 검색, 정렬, 필터, 새로고침처럼 목록 상태를 바꾸는 컨트롤 묶음이다.
- `Summary Line`은 현재 필터, 개수, 상태를 한 줄 이상으로 설명하는 보조 텍스트이다.

## Top Level Surfaces

| canonical name | Korean name | What it means | Code |
| --- | --- | --- | --- |
| `Control Shell` | 제어 셸 | 앱 시작, 프로필 선택, 대상 창 선택, 스캔 요청을 관리하는 Tk 루트 앱 | `main.py:App` |
| `Floating Overlay` | 플로팅 오버레이 | 게임 창 위/옆에 떠서 스캔 버튼과 상태를 보여주는 작은 제어창 | `gui/floating.py:FloatingOverlay` |
| `Scan Progress Overlay` | 스캔 진행 오버레이 | 스캔 중 표시되는 진행 카드와 중지 버튼 | `gui/floating.py:_draw_scan_overlay` |
| `Input Test Overlay` | 입력 테스트 오버레이 | 클릭, 스크롤, 드래그, 캡처를 수동 검증하는 도구 창 | `gui/input_test_overlay.py:InputTestOverlay` |
| `Region Capture Overlay` | 영역 캡처 오버레이 | 입력 테스트에서 화면 영역을 지정하는 투명 캡처 오버레이 | `gui/input_test_overlay.py:RegionCaptureOverlay` |
| `Viewer Window` | 뷰어 창 | 학생, 계획, 자원, 인벤토리, 통계를 보는 PySide6 메인 창 | `gui/viewer_app_qt.py:StudentViewerWindow` |
| `Fallback Viewer` | 폴백 뷰어 | Qt 뷰어를 열 수 없을 때 쓰는 Tk 학생 뷰어 | `gui/student_viewer.py` |

## Control Shell

| canonical name | Korean name | What it means | Code |
| --- | --- | --- | --- |
| `Profile Dialog` | 프로필 선택 창 | 시작 시 기존 프로필을 고르거나 새 프로필 이름을 입력하는 창 | `gui/profile_dialog.py:ProfileDialog` |
| `Profile List` | 프로필 목록 | 기존 프로필을 보여주는 리스트박스 | `ProfileDialog._listbox` |
| `Profile Name Field` | 프로필 이름 입력칸 | 새 프로필 또는 선택 프로필 이름을 입력하는 필드 | `ProfileDialog._entry` |
| `Profile Actions` | 프로필 작업 버튼줄 | Delete, OK, Cancel 버튼 영역 | `ProfileDialog._build` |
| `Window Picker Dialog` | 대상 창 선택 창 | Blue Archive 실행 창을 고르는 창 | `gui/window_picker.py:WindowPicker` |
| `Window Picker Header` | 대상 창 선택 헤더 | 창 선택 안내 제목 영역 | `WindowPicker._build_ui` |
| `Current Target Bar` | 현재 대상 창 표시줄 | 현재 선택된 대상 창 제목을 보여주는 상태줄 | `WindowPicker._cur_var` |
| `Window List` | 창 목록 | 실행 중인 창 제목과 크기를 보여주는 리스트 | `WindowPicker._listbox` |
| `Window Picker Actions` | 대상 창 선택 버튼줄 | Refresh, Use selected window, Cancel 버튼 영역 | `WindowPicker._build_ui` |
| `Item Scan Filter Dialog` | 아이템 스캔 필터 창 | 이번 아이템 스캔에서 사용할 인벤토리 필터를 고르는 간단한 Tk 창 | `main.py:_choose_item_scan_filter` |
| `Item Scan Filter Options` | 아이템 스캔 필터 체크목록 | All, 장비/재화 등 스캔 범위 체크박스 목록 | `_ITEM_SCAN_FILTER_OPTIONS` |
| `Fast Scan Choice Dialog` | 빠른 학생 스캔 선택 창 | 일반 스캔, 빠른 스캔, 롤백, 목록 편집 중 하나를 고르는 창 | `gui/fast_scan_dialog.py:FastScanDialog` |
| `Fast Scan Info Panel` | 빠른 스캔 정보 패널 | 스캔 모드, 기준 목록 출처, 저장 데이터 개수를 보여주는 패널 | `FastScanDialog._build` |
| `Fast Scan Roster Preview` | 빠른 스캔 기준 목록 미리보기 | 빠른 스캔에 사용할 학생 순서를 보여주는 리스트 | `FastScanDialog._listbox` |
| `Fast Scan Confirmation Checks` | 빠른 스캔 확인 체크 | 순서와 보유 학생 일치 여부를 확인하는 체크박스 2개 | `FastScanDialog._check_order`, `_check_owned` |
| `Fast Scan Actions` | 빠른 스캔 버튼줄 | Rollback, Edit, Cancel, Normal Scan, Fast Scan 버튼 영역 | `FastScanDialog._build` |
| `Fast Scan Config Dialog` | 빠른 스캔 목록 설정 창 | 빠른 스캔 기준 학생 목록을 선택/저장하는 창 | `gui/fast_scan_config_dialog.py:FastScanConfigDialog` |
| `Fast Scan Count Bar` | 빠른 스캔 선택 개수 표시줄 | 선택 학생 수와 저장 데이터 학생 수를 보여주는 상단 패널 | `FastScanConfigDialog._count_label` |
| `Fast Scan Search Field` | 빠른 스캔 검색칸 | 목록 안 학생을 검색하는 입력칸 | `FastScanConfigDialog._search` |
| `Fast Scan Student Checklist` | 빠른 스캔 학생 체크목록 | 학생별 포함 여부를 고르는 스크롤 체크리스트 | `FastScanConfigDialog._rows` |
| `Fast Scan Bulk Actions` | 빠른 스캔 일괄 버튼줄 | Select all, Clear all, Restore initial selection 영역 | `FastScanConfigDialog._build` |
| `Fast Scan Save Actions` | 빠른 스캔 저장 버튼줄 | Save, Cancel 버튼 영역 | `FastScanConfigDialog._build` |

## Floating Overlay

| canonical name | Korean name | What it means | Code |
| --- | --- | --- | --- |
| `Overlay Bubble` | 접힌 오버레이 버블 | 접힌 상태의 원형/작은 진입 버튼 | `FloatingOverlay._draw_collapsed` |
| `Overlay Expanded Panel` | 펼친 오버레이 패널 | 상태, 자원, 작업 버튼, 로그를 담는 확장 패널 | `FloatingOverlay._draw_expanded` |
| `Overlay Header` | 오버레이 헤더 | 제목과 접기 버튼이 있는 드래그 가능한 상단 바 | `FloatingOverlay._draw_expanded` |
| `Overlay Status Row` | 오버레이 상태 행 | 앱 상태와 로비 감지 상태를 보여주는 행 | `FloatingOverlay._status_label` |
| `Overlay Resource Row` | 오버레이 자원 행 | 청휘석/크레딧 등 스캔된 자원을 보여주는 행 | `FloatingOverlay._pyrox_label`, `_credit_label` |
| `Overlay Action Grid` | 오버레이 작업 버튼 영역 | 학생/장비/아이템/전체 스캔, 현재 학생 스캔, 뷰어 열기 등 버튼 묶음 | `FloatingOverlay._actions_frame` |
| `Overlay Log Panel` | 오버레이 로그 패널 | 최근 상태 메시지를 보여주는 짧은 로그 영역 | `FloatingOverlay._log_label` |
| `Overlay Footer` | 오버레이 하단 버튼 | 입력 테스트/설정 계열 보조 버튼 영역 | `FloatingOverlay._draw_footer` |
| `Scan Progress Card` | 스캔 진행 카드 | 스캔 중 제목, 진행바, 메시지, 중지 버튼을 담는 카드 | `FloatingOverlay._draw_scan_overlay` |
| `Scan Progress Title` | 스캔 진행 제목 | 현재 스캔 종류/상태 제목 | `FloatingOverlay._scan_title_label` |
| `Scan Progress Bar` | 스캔 진행바 | indeterminate 또는 정량 진행률 표시 | `FloatingOverlay._scan_progress` |
| `Scan Progress Counter` | 스캔 진행 카운터 | 현재/전체 진행 숫자 또는 계산 중 문구 | `FloatingOverlay._scan_progress_label` |
| `Scan Progress Message` | 스캔 진행 메시지 | 현재 처리 중인 학생/단계 설명 | `FloatingOverlay._scan_message_label` |
| `Scan Stop Button` | 스캔 중지 버튼 | 현재 스캔 중지 요청 버튼 | `FloatingOverlay._draw_scan_overlay` |

## Input Test Overlay

| canonical name | Korean name | What it means | Code |
| --- | --- | --- | --- |
| `Input Test Header` | 입력 테스트 헤더 | Input Test 제목과 Close 버튼이 있는 상단 바 | `InputTestOverlay._draw` |
| `Input Test Scroll Body` | 입력 테스트 스크롤 본문 | 모든 입력 테스트 섹션을 담는 스크롤 영역 | `InputTestOverlay._scroll_canvas`, `_scroll_body` |
| `Click Method Section` | 클릭 방식 섹션 | 클릭 구현 방식을 고르는 라디오 버튼 묶음 | `_draw_click_method_section` |
| `Click Action Section` | 클릭 실행 섹션 | 현재 커서 클릭, 게임 중앙 클릭 버튼 묶음 | `_draw_click_action_section` |
| `Exact Coordinate Section` | 정확 좌표 클릭 섹션 | 좌표 모드, X/Y 입력, 좌표 로드, 즉시/지연 클릭 버튼 | `_draw_exact_coord_section` |
| `Capture Point Section` | 캡처 포인트 섹션 | 포인트 이름, 프리셋, 커서 기록 버튼 | `_draw_capture_section` |
| `Region Capture Section` | 영역 캡처 섹션 | 영역 이름, 템플릿 프로필, 평행사변형/사각형 영역 캡처 버튼 | `_draw_region_capture_section` |
| `Scroll Test Section` | 스크롤 테스트 섹션 | 휠 amount/raw delta 입력과 스크롤 실행 버튼 | `_draw_scroll_test_section` |
| `Drag Test Section` | 드래그 테스트 섹션 | dY, duration, 좌표 모드, 좌표 입력, 드래그 실행 버튼 | `_draw_scroll_test_section` |
| `Input Countdown Line` | 입력 대기 카운트다운 | 지연 클릭/캡처 대기 상태 표시 | `InputTestOverlay._countdown_text` |
| `Input Status Line` | 입력 테스트 상태줄 | 실행 결과와 오류 메시지 표시 | `InputTestOverlay._status_text` |

## Viewer Window

| canonical name | Korean name | What it means | Code / objectName |
| --- | --- | --- | --- |
| `Viewer Root` | 뷰어 루트 | 전체 Qt 창의 중앙 위젯 | `viewerRoot` |
| `Main Tabs` | 메인 탭 바 | Students, Plans, Requirements, Inventory, Statistics 탭 | `mainTabs` |
| `Students Tab` | 학생 탭 | 학생 탐색과 상세 보기 화면 | `_build_students_tab` |
| `Plans Tab` | 계획 탭 | 성장 목표 계획 편집 화면 | `_build_plan_tab` |
| `Requirements Tab` | 필요 재화 탭 | scope 학생 집합의 누적 필요 재화 계산 화면 | `_build_resource_tab` |
| `Inventory Tab` | 인벤토리 탭 | 스캔된 보유 재화/장비 목록 화면 | `_build_inventory_tab` |
| `Statistics Tab` | 통계 탭 | 보유/속성/학교/역할 분포 화면 | `_build_stats_tab` |
| `Tab Header` | 탭 헤더 | 각 탭 최상단 제목/설명 영역 | `header` |
| `Standard Panel` | 표준 패널 | 도구막대, 목록, 상세 영역 등 일반 패널 | `panel` |
| `Section Title` | 섹션 제목 | 패널 또는 섹션의 제목 라벨 | `sectionTitle` |
| `Filter Summary Line` | 필터 요약줄 | 적용된 필터나 현재 검색 상태를 보여주는 줄 | `filterSummary` |
| `Parallelogram Button Row` | 평행사변형 버튼줄 | Filters/Refresh/Add 같은 커스텀 버튼 묶음 | `ParallelogramButtonRow` |
| `Student Card Grid` | 학생 카드 그리드 | 학생 카드를 반응형 그리드로 보여주는 스크롤 영역 | `ParallelogramCardGrid`, `studentGrid` |
| `Student Card` | 학생 카드 | 학생 1명을 나타내는 평행사변형 카드 | `StudentCardWidget` |
| `Student Portrait` | 학생 초상 | 카드 또는 상세 상단의 학생 이미지 | `StudentPortraitWidget` |
| `Unowned Badge` | 미보유 배지 | 미보유 학생 카드에 표시되는 배지 | `StudentCardWidget._paint_unowned_badge` |

## Students Tab

| canonical name | Korean name | What it means | Code |
| --- | --- | --- | --- |
| `Students Header` | 학생 탭 헤더 | Blue Archive Planner 제목, 설명, 현재 학생 개수 | `_build_students_tab`, `header` |
| `Students Count Label` | 학생 수 라벨 | 필터 적용 후 표시 학생 수 | `self._count_label` |
| `Students Toolbar` | 학생 도구막대 | 검색, 정렬, 보유/JP 필터, 필터/새로고침 버튼 영역 | `toolbar`, `panel` |
| `Students Search Field` | 학생 검색칸 | 이름, ID, 태그 검색 입력 | `self._search` |
| `Students Sort Dropdown` | 학생 정렬 드롭다운 | Star/Level/Name 기준 정렬 선택 | `self._sort_mode` |
| `Show Unowned Toggle` | 미보유 표시 토글 | 미보유 학생을 목록에 포함할지 선택 | `self._show_unowned` |
| `Hide JP-only Toggle` | JP-only 숨김 토글 | JP-only 학생을 숨길지 선택 | `self._hide_jp_only` |
| `Students Filter Button` | 학생 필터 버튼 | 필터 대화상자 열기 | `self._filter_button` |
| `Students Refresh Button` | 학생 새로고침 버튼 | DB/JSON 데이터를 다시 읽기 | local `refresh_button` |
| `Students Filter Summary` | 학생 필터 요약줄 | 검색/필터 상태 요약 | `self._filter_summary` |
| `Students Splitter` | 학생 화면 분할바 | 좌측 카드 그리드와 우측 상세 패널을 나누는 스플리터 | local `content` |
| `Students List Panel` | 학생 목록 패널 | 학생 카드 그리드를 담는 좌측 패널 | local `list_panel` |
| `Student Detail Panel` | 학생 상세 패널 | 선택 학생 상세 정보를 담는 우측 패널 | local `detail` |
| `Detail Scroll Body` | 학생 상세 스크롤 본문 | 우측 상세 패널의 내부 스크롤 영역 | `self._detail_scroll`, `_detail_panel` |
| `Detail Hero Wrap` | 상세 히어로 래퍼 | 학생 초상 이미지를 감싸는 상단 프레임 | `self._hero_wrap`, `heroWrap` |
| `Detail Hero Portrait` | 상세 히어로 초상 | 선택 학생의 큰 초상 이미지 | `self._hero`, `hero` |
| `Detail Info Card` | 상세 정보 카드 | 이름, 속성, 레벨, 스킬, 장비 정보를 담는 카드 | local `detail_card`, `detailCard` |
| `Detail Affinity Bars` | 상세 속성 바 | 공격/방어 타입 색상을 보여주는 두 개의 상단 바 | `_detail_attack_bar`, `_detail_defense_bar` |
| `Detail Progress Strip` | 상세 성장 스트립 | 별/무기 별 등 성장 상태를 시각화하는 스트립 | `_detail_progress_strip` |
| `Detail Name Block` | 상세 이름 블록 | 학교 아이콘, 이름, 부제, 배지를 묶은 영역 | `_detail_school_icon`, `_name`, `_subtitle`, `_detail_badges` |
| `Detail Type Chips` | 상세 타입 칩 | 공격 타입, 방어 타입 칩 | `_detail_attack_chip`, `_detail_defense_chip` |
| `Detail Add To Plan Button` | 상세 계획 추가 버튼 | 선택 학생을 Plans 탭에 추가 | `_detail_plan_button` |
| `Detail Level Tile` | 상세 레벨 타일 | 학생 레벨 큰 숫자 카드 | `_detail_level_value` |
| `Detail Position Tile` | 상세 포지션 타일 | Front/Middle/Back 등 위치 표시 카드 | `_detail_position_value` |
| `Detail Class Tile` | 상세 클래스 타일 | Striker/Special 등 전투 클래스 표시 카드 | `_detail_class_value` |
| `Detail Weapon Tile` | 상세 무기 타일 | 전용무기 별/레벨 표시 카드 | `_detail_weapon_card`, `_detail_weapon_value`, `_detail_weapon_sub` |
| `Detail Skill Tiles` | 상세 스킬 타일 | EX, Normal, Passive, Sub 스킬 레벨 4개 카드 | `_detail_skill_labels` |
| `Detail Equipment Tiles` | 상세 장비 타일 | Equip 1-3 티어/레벨 카드 | `_detail_equip_cards` |
| `Detail Stats Line` | 상세 스탯 줄 | HP/ATK/HEAL 등 보조 스탯 요약 | `_detail_stats_line` |

## Plans Tab

| canonical name | Korean name | What it means | Code |
| --- | --- | --- | --- |
| `Plans Header` | 계획 탭 헤더 | Plan Workspace 제목과 설명 | `_build_plan_tab`, `header` |
| `Quick Add Panel` | 빠른 추가 패널 | 계획에 넣을 학생을 검색하고 추가하는 상단 패널 | `quick_add_panel` |
| `Quick Add Search Field` | 빠른 추가 검색칸 | 계획 추가용 학생 검색 입력 | `_plan_search` |
| `Quick Add Button` | 빠른 추가 버튼 | 선택된 검색 결과를 계획에 추가 | `_plan_add_button` |
| `Quick Add Result List` | 빠른 추가 결과 목록 | 검색 결과 학생 리스트 | `_plan_all_list` |
| `Quick Add State Line` | 빠른 추가 상태줄 | 검색 전/결과/상태 메시지 | `_plan_search_state` |
| `Plans Splitter` | 계획 화면 분할바 | 좌측 계획 목록과 우측 편집기를 나누는 스플리터 | local `splitter` |
| `Planned Students Panel` | 계획 학생 패널 | 계획에 들어간 학생 카드 그리드 | local `plan_panel` |
| `Planned Students Count` | 계획 학생 수 라벨 | 계획된 학생 수 | `_plan_count_label` |
| `Planned Students Empty Line` | 계획 빈 상태 문구 | 계획 학생이 없을 때 안내 문구 | `_plan_empty_label` |
| `Planned Students Grid` | 계획 학생 카드 그리드 | 계획 학생 카드 목록 | `_plan_grid` |
| `Plan List Actions` | 계획 목록 버튼줄 | Remove, Open In Viewer 버튼 영역 | `_plan_remove_button`, `_plan_open_button` |
| `Plan Editor Panel` | 계획 편집 패널 | 선택 학생의 목표 수치를 편집하는 우측 패널 | local `editor_panel` |
| `Plan Editor Name` | 계획 편집 학생 이름 | 편집 중인 학생 이름 | `_plan_name` |
| `Plan Editor Current Summary` | 계획 편집 현재값 요약 | 현재 성장 상태 요약 | `_plan_current` |
| `Plan Editor Controls` | 계획 편집 컨트롤 영역 | 목표 섹션들을 담는 내부 2열 영역 | local `controls_wrap` |
| `Growth Target Section` | 성장 목표 섹션 | 별/무기 별 목표를 편집하는 섹션 | `progression_panel` |
| `Star Weapon Selector` | 별/무기 별 선택기 | 학생 별과 무기 별을 하나의 9칸 선택기로 편집 | `_plan_segment_inputs["star_weapon"]` |
| `Skills Section` | 스킬 섹션 | EX/Normal/Passive/Sub 목표 레벨 선택 | `skill_panel` |
| `Skill Target Row` | 스킬 목표 행 | 스킬 하나의 목표 레벨 선택 행 | dynamic `planBand` |
| `Equipment Tier Section` | 장비 티어 섹션 | Equip 1-3 및 Unique Item 티어 목표 편집 | `equipment_panel` |
| `Unique Item Row` | 애용품 행 | Unique Item 티어 목표 선택 | `_plan_unique_item_panel`, `_plan_unique_item_selector` |
| `Equipment Tier Row` | 장비 티어 행 | Equip 1/2/3 티어 목표 선택 행 | `_plan_equipment_labels`, `_plan_segment_inputs` |
| `Level Targets Section` | 레벨 목표 섹션 | 학생, 무기, 장비 레벨 목표 편집 | `level_panel` |
| `Level Target Row` | 레벨 목표 행 | 한 종류의 레벨 목표를 숫자로 편집하는 행 | `_plan_level_rows`, `_plan_level_inputs` |
| `Bond Stats Caption` | 인연 스탯 제목 | HP/ATK/HEAL 목표 영역 제목 | `_plan_stat_caption` |
| `Bond Stat Row` | 인연 스탯 행 | HP/ATK/HEAL 목표 값을 편집하는 행 | `_plan_stat_rows` |
| `Plan Segment Selector` | 구간 선택기 | 1..N 칸으로 목표값을 고르는 커스텀 컨트롤 | `PlanSegmentSelector` |
| `Plan Stepper` | 숫자 스테퍼 | 숫자 입력과 MAX 버튼으로 목표값을 편집하는 컨트롤 | `PlanStepper` |
| `Plan Dual Digit Selector` | 두 자리 선택기 | 10의 자리/1의 자리 방식 목표값 선택기 | `PlanDualDigitSelector` |

## Requirements Tab

| canonical name | Korean name | What it means | Code |
| --- | --- | --- | --- |
| `Requirements Header` | 필요 재화 탭 헤더 | Requirement Scope 제목과 설명 | `_build_resource_tab`, `header` |
| `Resource Left Mode Tabs` | 자원 좌측 모드 탭 | Scope/Search 좌측 창 전환 탭 | `_resource_left_tabs` |
| `Resource Left Mode Stack` | 자원 좌측 모드 스택 | Scope 창과 Search 창을 담는 스택 | `_resource_left_stack` |
| `Resources Toolbar` | 자원 도구막대 | Search 창 안의 검색, 정렬, 보유/JP 필터, 필터/새로고침 버튼 영역 | `toolbar`, `panel` |
| `Resources Search Field` | 자원 검색칸 | Search 창에서 자원 계산 대상 학생 검색 입력 | `_resource_search` |
| `Resources Sort Dropdown` | 자원 정렬 드롭다운 | 자원 대상 학생 정렬 기준 | `_resource_sort_mode` |
| `Resources Show Unowned Toggle` | 자원 미보유 표시 토글 | 자원 계산 대상에 미보유를 포함할지 선택 | `_resource_show_unowned` |
| `Resources Hide JP-only Toggle` | 자원 JP-only 숨김 토글 | 자원 계산 대상에서 JP-only 숨김 | `_resource_hide_jp_only` |
| `Resources Filter Button` | 자원 필터 버튼 | 공용 학생 필터 대화상자 열기 | `_resource_filter_button` |
| `Resources Refresh Button` | 자원 새로고침 버튼 | 데이터 다시 읽기 | local `resource_refresh_button` |
| `Resources Filter Summary` | 자원 필터 요약줄 | 자원 탭 필터 상태 요약 | `_resource_filter_summary` |
| `Resources Splitter` | 자원 화면 분할바 | 좌측 대상 학생 목록과 우측 결과 영역 분할 | local `splitter` |
| `Resource Scope Panel` | 자원 대상 학생 패널 | 계산 범위에 들어온 학생 리스트 | local `left_panel` |
| `Resource Scope Summary` | 자원 대상 요약줄 | scope 학생 수와 plan 포함/미포함 요약 | `_resource_list_summary` |
| `Resource Scope Count` | 자원 대상 수 | scope에 들어간 학생 수 | `_resource_scope_count` |
| `Resource Unplanned Options` | 미계획 학생 계산 옵션 | plan에 없는 scope 학생의 Level/Equipment/Skills 비용 포함 여부 | `_resource_unplanned_level`, `_resource_unplanned_equipment`, `_resource_unplanned_skills` |
| `Resource Scope Grid` | 자원 대상 학생 그리드 | scope에 들어간 학생 카드 그리드 | `_resource_scope_grid` |
| `Resource Search Result Grid` | 자원 검색 결과 그리드 | 검색/필터 결과를 카드 on 상태로 고른 뒤 scope에 추가하는 그리드 | `_resource_search_grid` |
| `Resource Search Summary` | 자원 검색 결과 요약줄 | 검색 결과 수, plan 포함 수, scope 포함 수, 추가 대기 수 요약 | `_resource_search_summary` |
| `Resource Result Panel` | 자원 결과 패널 | scope 전체 누적 필요 재화 칩 그리드 | local `right_panel` |
| `Aggregate Resource Options` | 합산 자원 옵션 패널 | scope 합산 상태 요약 | `aggregate_options` |
| `Aggregate Resource Output` | 합산 자원 결과 그리드 | scope 합산 비용 칩 그리드 | `_resource_requirement_grid` |

## Inventory Tab

| canonical name | Korean name | What it means | Code |
| --- | --- | --- | --- |
| `Inventory Header` | 인벤토리 탭 헤더 | Inventory 제목, 설명, 스캔 요약 | `_build_inventory_tab`, `header` |
| `Inventory Summary` | 인벤토리 요약줄 | 스캔된 인벤토리 상태/개수 요약 | `_inventory_summary` |
| `Inventory Root Tabs` | 인벤토리 루트 탭 | Equipment, Items 상위 탭 | `_inventory_root_tabs` |
| `Inventory Equipment Root` | 인벤토리 장비 루트 | 장비 계열별 하위 탭을 담는 루트 | local `equipment_root` |
| `Inventory Equipment Tabs` | 인벤토리 장비 탭 | 장비 시리즈별 하위 탭 | `_inventory_equipment_tabs` |
| `Inventory Equipment Section` | 인벤토리 장비 섹션 | 장비 시리즈 제목과 요약 | dynamic `planSectionPanel` |
| `Inventory Equipment List` | 인벤토리 장비 목록 | 특정 장비 시리즈의 스캔 항목 목록 | `_inventory_equipment_lists` |
| `Inventory Items Root` | 인벤토리 아이템 루트 | 아이템 종류별 하위 탭을 담는 루트 | local `item_root` |
| `Inventory Item Tabs` | 인벤토리 아이템 탭 | Ooparts, WB, Stones, Reports, Weapon Parts, Tech Notes, BD, Other | `_inventory_item_tabs` |
| `Inventory Item Section` | 인벤토리 아이템 섹션 | 아이템 종류 제목과 요약 | dynamic `planSectionPanel` |
| `Inventory Item List` | 인벤토리 아이템 목록 | 특정 아이템 종류의 스캔 항목 목록 | `_inventory_item_lists` |
| `Inventory Item Row` | 인벤토리 아이템 행 | 아이콘, 이름, 메타정보, 수량을 가진 행 | `InventoryListItem` |
| `Inventory Item Icon` | 인벤토리 아이콘 | 항목 이미지 | `InventoryListItem._icon` |
| `Inventory Item Name` | 인벤토리 항목명 | 항목 표시 이름 | `InventoryListItem._name` |
| `Inventory Item Meta` | 인벤토리 메타 | 티어/종류 등 보조 정보 | `InventoryListItem._meta` |
| `Inventory Item Quantity` | 인벤토리 수량 | 보유 수량 | `InventoryListItem._quantity` |

## Statistics Tab

| canonical name | Korean name | What it means | Code |
| --- | --- | --- | --- |
| `Statistics Header` | 통계 탭 헤더 | Collection Statistics 제목과 설명 | `_build_stats_tab`, `header` |
| `Statistics Summary Line` | 통계 요약줄 | 현재 visible students 기반 요약 문구 | `_stats_summary_line` |
| `Statistics Scroll Body` | 통계 스크롤 본문 | KPI 카드와 분포 카드를 담는 스크롤 영역 | local `scroll`, `host` |
| `Statistics KPI Grid` | 통계 KPI 그리드 | 총 학생, 보유율 등 핵심 지표 카드 영역 | `_stats_summary_cards` |
| `Statistics KPI Card` | 통계 KPI 카드 | 하나의 핵심 지표 카드 | dynamic `summaryCard` |
| `Statistics Distribution Grid` | 통계 분포 그리드 | 속성/학교/역할 분포 카드 영역 | `_stats_cards_layout` |
| `Statistics Distribution Card` | 통계 분포 카드 | 하나의 분포를 보여주는 패널 | dynamic `statPanel` |
| `Statistics Donut` | 통계 도넛 | 분포 비율을 보여주는 원형 차트 | `DonutWidget` |
| `Statistics Top Rows` | 통계 상위 항목 행 | 분포 카드 안 상위 값과 퍼센트 목록 | dynamic labels in `_refresh_stats_tab` |

## Filter Dialog

| canonical name | Korean name | What it means | Code |
| --- | --- | --- | --- |
| `Student Filter Dialog` | 학생 필터 창 | Students/Resources 탭에서 공용으로 쓰는 필터 창 | `FilterDialog` |
| `Filter Intro Text` | 필터 안내문 | 여러 속성 선택 규칙 안내 | `FilterDialog.__init__` |
| `Filter Scroll Body` | 필터 스크롤 본문 | 필터 그룹들을 담는 스크롤 영역 | local `scroll`, `body` |
| `Filter Group` | 필터 그룹 | 학교, 역할, 공격 타입 등 필드별 체크박스 그룹 | dynamic `QGroupBox` |
| `Filter Option Checkbox` | 필터 옵션 체크박스 | 필터 값 하나를 켜고 끄는 체크박스 | dynamic `QCheckBox` |
| `Filter Dialog Actions` | 필터 창 버튼줄 | Apply, Reset, Cancel 버튼 | `QDialogButtonBox` |

## Reusable Viewer Components

| canonical name | Korean name | What it means | Code |
| --- | --- | --- | --- |
| `Parallelogram Panel` | 평행사변형 패널 | 비스듬한 변을 가진 정보 패널 기반 위젯 | `ParallelogramPanel` |
| `Equipment Detail Card` | 상세 장비 카드 | 상세 패널의 장비 티어/레벨 카드 | `EquipmentDetailCard` |
| `Detail Progress Strip` | 상세 성장 스트립 | 상세 카드 안 성장 상태 표시 위젯 | `DetailProgressStrip` |
| `Plan Editor Cell` | 계획 편집 셀 | 계획 선택기 내부의 단일 칸 | `PlanEditorCell` |
| `Plan Option Strip` | 계획 옵션 스트립 | 계획 선택 버튼들이 한 줄로 배치된 스트립 | `PlanOptionStrip` |
| `Plan Value Input` | 계획 값 입력칸 | 스테퍼 내부 숫자 입력칸 | `planValueInput` |
| `Plan Quick Button` | 계획 빠른 버튼 | MAX, Check visible 등 작고 강조된 액션 버튼 | `planQuickButton` |
| `Plan Section Panel` | 계획 섹션 패널 | Plans/Resources/Inventory에서 쓰는 내부 섹션 패널 | `planSectionPanel` |
| `Plan Band` | 계획 밴드 | 한 줄짜리 목표 행 또는 리스트 행 | `planBand` |
| `Plan Transparent Host` | 계획 투명 호스트 | 섹션 내부에서 배경/테두리 없이 레이아웃만 잡는 위젯 | `planTransparent` |

## Suggested Request Phrases

- "Students Toolbar의 검색칸을 더 넓혀줘."
- "Student Detail Panel의 Detail Hero Portrait 높이를 줄여줘."
- "Plans Tab의 Equipment Tier Section을 오른쪽 컬럼으로 옮겨줘."
- "Requirements Tab의 scope 추가 버튼 간격을 줄여줘."
- "Inventory Item Row에서 수량을 더 눈에 띄게 해줘."
- "Floating Overlay의 Scan Progress Card 메시지 줄바꿈을 고쳐줘."
- "Input Test Overlay의 Region Capture Section에 새 버튼을 추가해줘."

## Maintenance Notes

- 새 GUI 요소를 추가하면 이 문서에 `canonical name`, 한국어 이름, 의미, 코드 위치를 함께 추가한다.
- Qt 요소에 스타일이 필요하면 가능하면 `setObjectName()`을 부여하고 이 문서의 이름과 맞춘다.
- 동적으로 반복되는 항목은 개별 인스턴스명을 모두 나열하지 않고 `Row`, `Card`, `Tile` 단위로 정의한다.
- 같은 모양이어도 역할이 다르면 이름을 분리한다. 예: `Students Filter Summary`, `Resources Filter Summary`.
- 같은 역할이어도 위치가 다르면 탭 접두사를 붙인다. 예: `Students Search Field`, `Resources Search Field`.
