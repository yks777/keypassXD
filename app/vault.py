"""Persistência KDBX4 usando PyKeePass; NÃO implementa criptografia própria.

A UI jamais armazena segredos em cache em disco. Este programa Python não oferece
proteção contra dump de memória, keylogger, processos do mesmo usuário ou malware.
"""
from __future__ import annotations

import gc
import os
from pathlib import Path
import shutil
import tempfile
from uuid import UUID

# Import adiado de propósito: este módulo precisa ser importável nos testes
# de segurança offline mesmo sem PyKeePass instalado. As funções que tocam
# no KDBX importam dentro do próprio corpo e falham com mensagem clara.
try:
    from pykeepass.kdbx_parsing import kdf_uuids as _KDF_UUIDS
except ImportError:  # pragma: no cover - ambiente sem dependências
    _KDF_UUIDS = {
        "argon2": b"\xefcm\xdf\x8c)DK\x91\xf7\xa9\xa4\x03\xe3\n\x0c",
        "argon2id": b"\x9e)\x8b\x19V\xdbGs\xb2=\xfc>\xc6\xf0\xa1\xe6",
        "aeskdf": b"\xc9\xd9\xf3\x9ab\x8aD`\xbft\r\x08\xc1\x8aO\xea",
    }

# Padrão KeePassXC moderno: Argon2id com custo mínimo relevante. Só elevamos
# (nunca rebaixamos) bancos existentes: quem já tem custo maior mantém.
KDF_STRONG_UUID = _KDF_UUIDS["argon2id"]
KDF_MIN_MEMORY = 64 * 1024 * 1024  # 64 MiB
KDF_MIN_ITERATIONS = 3
KDF_MIN_PARALLELISM = 2

VAULT_DIR = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "keypassxd"
VAULT_PATH = VAULT_DIR / "vault.kdbx"
# Cofres novos nascem vazios: nenhuma pasta padrão. O usuário cria as
# próprias pastas pela interface. A raiz ("Geral") é mantida como rótulo
# virtual das entradas sem pasta, sem criar grupo no KDBX.
INITIAL_GROUPS: tuple[str, ...] = ()


KDBX_MAGIC = b"\x03\xd9\xa2\x9a"
KDBX_MAX_BYTES = 100 * 1024 * 1024  # 100 MiB: trava arquivo absurdo no import.


def is_kdbx_file(path: Path) -> bool:
    """Checagem barata e 100% local: magic + tamanho plausível (sem abrir senha)."""
    try:
        if path.is_symlink() or not path.is_file():
            return False
        if path.stat().st_size < 124 or path.stat().st_size > KDBX_MAX_BYTES:
            return False
        with path.open("rb") as stream:
            return stream.read(4) == KDBX_MAGIC
    except OSError:
        return False


def kdf_needs_upgrade(uuid: bytes, memory: int = 0, iterations: int = 0) -> bool:
    """Decisão pura (sem PyKeePass): True se o KDF deve migrar para Argon2id forte."""
    if uuid != KDF_STRONG_UUID:
        return True
    try:
        if int(memory) < KDF_MIN_MEMORY or int(iterations) < KDF_MIN_ITERATIONS:
            return True
    except (TypeError, ValueError):
        return True
    return False


def _directory() -> None:
    VAULT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if VAULT_DIR.is_symlink():
        raise RuntimeError("O diretório do cofre não pode ser um link simbólico.")
    os.chmod(VAULT_DIR, 0o700)


def _refuse_symlink(path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError("Não é permitido usar um cofre que seja um link simbólico.")


def _tighten_file(path: Path) -> None:
    """Garante 0600 no .kdbx (corrige vazamento de permissão sem falhar)."""
    try:
        if path.is_file() and not path.is_symlink():
            mode = path.stat().st_mode & 0o777
            if mode != 0o600:
                os.chmod(path, 0o600)
    except OSError:
        pass


def _apply_strong_kdf(kp) -> bool:
    """Eleva KDBX4 para Argon2id forte. Retorna True se alterou algo.

    Nunca rebaixa: memória/iterações/paralelismo acima do mínimo são mantidos.
    Bancos KDBX3 (AES-KDF legado) não são migrados aqui — o usuário deve
    deixar o KeePassXC converter, ou recriar o cofre.
    """
    try:
        params = kp.kdbx.header.value.dynamic_header.kdf_parameters.data.dict
    except AttributeError:
        return False  # KDBX3 ou formato sem parâmetros KDF: não tocar.
    changed = False
    try:
        uuid = params["$UUID"].value
        memory = int(params["M"].value)
        iterations = int(params["I"].value)
        parallelism = int(params["P"].value)
    except (KeyError, AttributeError, TypeError, ValueError):
        return False
    if not kdf_needs_upgrade(uuid, memory, iterations):
        return False
    if uuid != KDF_STRONG_UUID:
        params["$UUID"].value = KDF_STRONG_UUID
        changed = True
    if memory < KDF_MIN_MEMORY:
        params["M"].value = KDF_MIN_MEMORY
        changed = True
    if iterations < KDF_MIN_ITERATIONS:
        params["I"].value = KDF_MIN_ITERATIONS
        changed = True
    if parallelism < KDF_MIN_PARALLELISM:
        params["P"].value = KDF_MIN_PARALLELISM
        changed = True
    return changed


class Vault:
    def __init__(self) -> None:
        self.kp = None

    @property
    def unlocked(self) -> bool:
        return self.kp is not None

    @staticmethod
    def exists() -> bool:
        _refuse_symlink(VAULT_PATH)
        return VAULT_PATH.is_file()

    def create(self, password: str) -> None:
        if len(password) < 11:
            raise ValueError("A senha mestra precisa ter pelo menos 11 caracteres.")
        _directory()
        if VAULT_PATH.exists() or VAULT_PATH.is_symlink():
            raise FileExistsError("O cofre já existe. Nenhum dado foi sobrescrito.")
        from pykeepass import PyKeePass, create_database
        # O nome temporário é exclusivo, modo 0600, no mesmo filesystem.
        fd, name = tempfile.mkstemp(prefix=".create-", suffix=".kdbx", dir=VAULT_DIR)
        os.close(fd)
        temporary = Path(name)
        try:
            os.chmod(temporary, 0o600)
            kp = create_database(str(temporary), password=password)
            # O template embutido do PyKeePass usa Argon2d legado: elevar para
            # Argon2id (padrão KeePassXC atual) antes do primeiro save final.
            _apply_strong_kdf(kp)
            # Sem pastas padrão: o cofre novo contém só o grupo raiz.
            # INITIAL_GROUPS é vazio de propósito (usuário cria as pastas).
            for group in INITIAL_GROUPS:
                kp.add_group(kp.root_group, group)
            kp.save()
            os.chmod(temporary, 0o600)
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            # Já verificamos a ausência antes; caso outro processo crie neste
            # ínterim, o lock de instância limita a concorrência da própria app.
            os.link(temporary, VAULT_PATH)
            temporary.unlink()
            # Caminho base do objeto aponta ao temporário criado: recarregar.
            self.kp = PyKeePass(str(VAULT_PATH), password=password)
            _tighten_file(VAULT_PATH)
        finally:
            temporary.unlink(missing_ok=True)

    def unlock(self, password: str) -> None:
        from pykeepass import PyKeePass
        _refuse_symlink(VAULT_PATH)
        if not VAULT_PATH.is_file():
            raise FileNotFoundError("Não foi encontrado um cofre.")
        self.kp = PyKeePass(str(VAULT_PATH), password=password)
        _tighten_file(VAULT_PATH)

    def kdf_status(self) -> dict:
        """Algoritmo e custo do banco aberto (para exibir na UI e testar)."""
        kp = self._require()
        algo = getattr(kp, "kdf_algorithm", None)
        if callable(algo):
            algo = algo()
        try:
            params = kp.kdbx.header.value.dynamic_header.kdf_parameters.data.dict
            return {
                "algorithm": algo or "desconhecido",
                "memory": int(params["M"].value),
                "iterations": int(params["I"].value),
                "parallelism": int(params["P"].value),
                "strong": not kdf_needs_upgrade(
                    params["$UUID"].value,
                    int(params["M"].value),
                    int(params["I"].value),
                ),
            }
        except (AttributeError, KeyError, TypeError, ValueError):
            return {"algorithm": algo or "aeskdf", "strong": False}

    def lock(self) -> None:
        self.kp = None
        gc.collect()  # Não garante apagamento de segredos da RAM.

    def _require(self):
        if self.kp is None:
            raise RuntimeError("Cofre bloqueado.")
        return self.kp

    def groups(self) -> list[str]:
        kp = self._require()
        return sorted({g.name for g in kp.groups if g.name and not g.is_root_group}, key=str.casefold)

    def add_group(self, name: str) -> None:
        kp = self._require()
        name = name.strip()
        if not name or len(name) > 60 or "/" in name:
            raise ValueError("Nome de pasta inválido.")
        if kp.find_groups(name=name, first=True):
            raise ValueError("Já existe uma pasta com esse nome.")
        kp.add_group(kp.root_group, name)
        self._save()

    def delete_group(self, name: str, delete_entries: bool = False) -> None:
        """Apaga uma pasta. Sem delete_entries, move as senhas para a raiz
        ("Geral") antes — no KDBX apagar o grupo destrói as entradas filhas.

        Nada sai da máquina. _save mantém a versão anterior do cofre em
        vault.backup.kdbx. 100% local.
        """
        # Argumento puro é validado antes do estado do cofre (locked → RuntimeError).
        name = name.strip()
        if not name:
            raise ValueError("Nome de pasta inválido.")
        kp = self._require()
        group = kp.find_groups(name=name, first=True)
        if group is None:
            raise ValueError("Pasta não encontrada.")
        if group is kp.root_group or group.is_root_group:
            raise ValueError("Não é possível apagar a pasta raiz.")
        if not delete_entries:
            # Materializar antes de mutar: find_entries devolve gerador.
            # recursive=True cobre subgrupos acidentais (a UI não os cria).
            for entry in list(kp.find_entries(group=group, recursive=True)):
                kp.move_entry(entry, kp.root_group)
        kp.delete_group(group)
        self._save()

    def _entry(self, uuid: str):
        kp = self._require()
        entry = kp.find_entries(uuid=UUID(uuid), first=True)
        if entry is None:
            raise ValueError("Entrada não encontrada.")
        return entry

    @staticmethod
    def _favorite(entry) -> bool:
        try:
            return entry.get_custom_property("keypassXD.favorite") == "1"
        except (AttributeError, KeyError, ValueError):
            return False

    def entries(self) -> list[dict]:
        kp = self._require()
        rows = []
        for e in kp.entries:
            rows.append({
                "uuid": str(e.uuid),
                "title": e.title or "Sem título",
                "username": e.username or "",
                "url": e.url or "",
                "notes": e.notes or "",
                "group": (e.group.name if e.group and not e.group.is_root_group else "Geral"),
                "favorite": self._favorite(e),
                "modified": e.mtime.timestamp() if e.mtime else 0.0,
            })
        return sorted(rows, key=lambda row: row["title"].casefold())

    def get_password(self, uuid: str) -> str:
        return self._entry(uuid).password or ""

    def upsert(self, uuid: str | None, values: dict) -> str:
        kp = self._require()
        title = str(values.get("title", "")).strip()
        if not title:
            raise ValueError("Informe o nome do serviço.")
        group_name = str(values.get("group", "Geral"))
        group = kp.root_group if group_name == "Geral" else kp.find_groups(name=group_name, first=True)
        if group is None:
            raise ValueError("Pasta inválida.")
        password = str(values.get("password", ""))
        if uuid:
            e = self._entry(uuid)
            e.save_history()
            e.title = title
            e.username = str(values.get("username", ""))
            e.url = str(values.get("url", ""))
            e.notes = str(values.get("notes", ""))
            if password:
                e.password = password
            if e.group != group:
                kp.move_entry(e, group)
        else:
            if not password:
                raise ValueError("Informe ou gere uma senha.")
            e = kp.add_entry(group, title, str(values.get("username", "")), password,
                             url=str(values.get("url", "")), notes=str(values.get("notes", "")))
        self._save()
        return str(e.uuid)

    def set_favorite(self, uuid: str, favorite: bool) -> None:
        e = self._entry(uuid)
        e.set_custom_property("keypassXD.favorite", "1" if favorite else "0")
        self._save()

    def delete(self, uuid: str) -> None:
        kp = self._require()
        kp.delete_entry(self._entry(uuid))
        self._save()

    def export_to(self, dest: Path) -> None:
        """Exporta cópia bit-a-bit do .kdbx (já criptografado). 100% local.

        Não re-criptografa nem gera plaintext: o destino continua exigindo
        a mesma senha mestra. Usado pelo botão "Exportar backup".
        """
        self._require()
        _refuse_symlink(VAULT_PATH)
        if not VAULT_PATH.is_file():
            raise FileNotFoundError("Não foi encontrado um cofre.")
        _refuse_symlink(dest)
        if dest.resolve() == VAULT_PATH.resolve():
            raise ValueError("Escolha um destino diferente do cofre atual.")
        dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(VAULT_PATH, dest)
        os.chmod(dest, 0o600)

    def import_from(self, src: Path, password: str) -> None:
        """Substitui o cofre pelo .kdbx importado (mesma senha mestra). 100% local.

        Fluxo: valida magic → abre com a senha (prova integridade) →
        migra KDF fraco para Argon2id → instala de forma atômica com
        backup automático do cofre anterior em vault.backup.kdbx.
        Nada é enviado à rede; nenhum plaintext é gravado.
        """
        _refuse_symlink(src)
        if not is_kdbx_file(src):
            raise ValueError("Arquivo inválido: selecione um .kdbx válido.")
        if not password or len(password) < 11:
            raise ValueError("Informe a senha mestra do arquivo importado.")
        from pykeepass import PyKeePass
        # Prova que a senha abre o arquivo antes de tocar no cofre atual.
        # Abre direto do caminho de origem (somente leitura); o save
        # posterior, se houver migração KDF, vai para staging em VAULT_DIR.
        incoming = PyKeePass(str(src), password=password)
        _directory()
        _refuse_symlink(VAULT_PATH)
        backup = VAULT_DIR / "vault.backup.kdbx"
        fd, name = tempfile.mkstemp(prefix=".import-", suffix=".kdbx", dir=VAULT_DIR)
        os.close(fd)
        tmp = Path(name)
        staged_fd, staged_name = tempfile.mkstemp(prefix=".import-src-", suffix=".kdbx", dir=VAULT_DIR)
        os.close(staged_fd)
        staged = Path(staged_name)
        try:
            os.chmod(tmp, 0o600)
            os.chmod(staged, 0o600)
            # Stage: se o KDF for fraco, salva já migrado; senão, cópia fiel.
            if _apply_strong_kdf(incoming):
                incoming.save(str(staged))
            else:
                shutil.copyfile(src, staged)
            os.chmod(staged, 0o600)
            with staged.open("rb") as stream:
                os.fsync(stream.fileno())
            shutil.copyfile(staged, tmp)
            os.chmod(tmp, 0o600)
            with tmp.open("rb") as stream:
                os.fsync(stream.fileno())
            if VAULT_PATH.exists():
                _refuse_symlink(backup)
                shutil.copyfile(VAULT_PATH, backup)
                os.chmod(backup, 0o600)
            os.replace(tmp, VAULT_PATH)
            _tighten_file(VAULT_PATH)
            directory_fd = os.open(VAULT_DIR, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            # Recarrega o objeto a partir do caminho instalado.
            self.kp = PyKeePass(str(VAULT_PATH), password=password)
            _tighten_file(VAULT_PATH)
        finally:
            tmp.unlink(missing_ok=True)
            staged.unlink(missing_ok=True)

    def verify_password(self, password: str) -> None:
        """Prova que a senha abre o cofre, sem alterar nada. 100% local.

        Usado antes de ações destrutivas (ex.: reset): não exige 14+
        caracteres (cofres antigos podem ter menos) e não salva nada.
        Levanta exceção se a senha não conferir ou o arquivo não existir.
        """
        if not password:
            raise ValueError("Informe a senha mestra.")
        from pykeepass import PyKeePass
        _refuse_symlink(VAULT_PATH)
        if not VAULT_PATH.is_file():
            raise FileNotFoundError("Não foi encontrado um cofre.")
        probe = PyKeePass(str(VAULT_PATH), password=password)
        probe.kdbx = None
        del probe
        gc.collect()

    def change_password(self, current: str, new: str) -> None:
        """Troca a senha mestra do cofre. 100% local.

        Prova a senha atual abrindo o .kdbx antes de alterar; depois
        define a nova via setter do PyKeePass e salva (_save faz backup
        automático + Argon2id + escrita atômica + 0600).
        """
        if not new or len(new) < 11:
            raise ValueError("A nova senha mestra precisa ter pelo menos 11 caracteres.")
        if not current:
            raise ValueError("Informe a senha mestra atual.")
        from pykeepass import PyKeePass
        _refuse_symlink(VAULT_PATH)
        if not VAULT_PATH.is_file():
            raise FileNotFoundError("Não foi encontrado um cofre.")
        # Prova antes de tocar no objeto aberto (evita travar com senha errada).
        PyKeePass(str(VAULT_PATH), password=current)
        kp = self._require()
        kp.password = new
        self._save()

    def reset(self) -> None:
        """Apaga vault.kdbx + vault.backup.kdbx (recomeço total). 100% local."""
        self.kp = None
        gc.collect()
        _refuse_symlink(VAULT_PATH)
        backup = VAULT_DIR / "vault.backup.kdbx"
        _refuse_symlink(backup)
        VAULT_PATH.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
        try:
            directory_fd = os.open(VAULT_DIR, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass

    def _save(self) -> None:
        kp = self._require()
        _directory()
        _refuse_symlink(VAULT_PATH)
        # Migração oportunista: banco antigo com AES-KDF/Argon2d sobe para
        # Argon2id no próximo save, sem ação do usuário.
        _apply_strong_kdf(kp)
        fd, name = tempfile.mkstemp(prefix=".save-", suffix=".kdbx", dir=VAULT_DIR)
        os.close(fd)
        tmp = Path(name)
        backup = VAULT_DIR / "vault.backup.kdbx"
        try:
            kp.save(str(tmp))
            os.chmod(tmp, 0o600)
            with tmp.open("rb") as stream:
                os.fsync(stream.fileno())
            # Backup permanece criptografado no mesmo formato e modo restrito.
            if VAULT_PATH.exists():
                _refuse_symlink(backup)
                shutil.copyfile(VAULT_PATH, backup)
                os.chmod(backup, 0o600)
            os.replace(tmp, VAULT_PATH)
            _tighten_file(VAULT_PATH)
            directory_fd = os.open(VAULT_DIR, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            tmp.unlink(missing_ok=True)
