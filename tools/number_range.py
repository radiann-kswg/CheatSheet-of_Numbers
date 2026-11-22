MAX_NUMBER = 1188


def number_folder(n: int) -> str:
    """収録値から numbers/ 内のフォルダ名を返す。"""
    return f"{n // 100}xx" if n < 1000 else "1xxx"
