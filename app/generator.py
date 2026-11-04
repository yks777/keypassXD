"""Gerador de senhas local baseado em secrets (CSPRNG do sistema)."""
import secrets
import string

ALPHABETS = (
    string.ascii_lowercase,
    string.ascii_uppercase,
    string.digits,
    "!@#$%&*+-_=?:",
)


def generate_password(length: int = 22, symbols: bool = True) -> str:
    """Garante ao menos um caractere por classe, quando viável."""
    groups = ALPHABETS if symbols else ALPHABETS[:3]
    if length < max(12, len(groups)) or length > 256:
        raise ValueError("O tamanho deve estar entre 12 e 256 caracteres.")
    result = [secrets.choice(group) for group in groups]
    all_chars = "".join(groups)
    result.extend(secrets.choice(all_chars) for _ in range(length - len(result)))
    secrets.SystemRandom().shuffle(result)
    return "".join(result)
