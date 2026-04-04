import os

def rename_pngs(folder_path):
    files = [f for f in os.listdir(folder_path) if f.lower().endswith('.png')]
    files.sort()  # 정렬 (선택)

    total = len(files)

    for i, file in enumerate(files, 1):
        old_path = os.path.join(folder_path, file)

        print(f"\n[{i}/{total}] 현재 파일: {file}")
        new_name = input("새 이름 입력 (확장자 제외, Enter=스킵): ").strip()

        if new_name == "":
            print("⏭️ 스킵")
            continue

        new_file = new_name + ".png"
        new_path = os.path.join(folder_path, new_file)

        if os.path.exists(new_path):
            print("⚠️ 이미 존재하는 이름 → 스킵")
            continue

        os.rename(old_path, new_path)
        print(f"✅ 변경됨 → {new_file}")

    print("\n✨ 모든 파일 처리 완료!")

if __name__ == "__main__":
    folder = input("폴더 경로 입력: ").strip()
    rename_pngs(folder)