import hashlib
import sys
from pathlib import Path


def get_file_hash(file_path: str) -> str:
    """파일의 SHA-256 해시값을 계산"""
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def compare_files(file1: str, file2: str) -> None:
    path1 = Path(file1)
    path2 = Path(file2)

    if not path1.is_file():
        print(f"오류: 첫 번째 파일이 존재하지 않습니다 -> {file1}")
        return

    if not path2.is_file():
        print(f"오류: 두 번째 파일이 존재하지 않습니다 -> {file2}")
        return

    hash1 = get_file_hash(file1)
    hash2 = get_file_hash(file2)

    if hash1 == hash2:
        print("결과: 동일한 파일입니다.")
    else:
        print("결과: 동일한 파일이 아닙니다.")

    print(f"\n[파일 1 SHA-256] {hash1}")
    print(f"[파일 2 SHA-256] {hash2}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("사용법: python compare_images.py 이미지1 이미지2")
    else:
        compare_files(sys.argv[1], sys.argv[2])