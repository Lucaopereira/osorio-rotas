"""Manda para a VPS o que o servidor gerencial mostra. Roda no PC, depois do `python -m pipeline`.

    python -m gerencial.publicar root@IP              # os painéis da pasta da reunião da semana
    python -m gerencial.publicar root@IP --codigo     # o código (gerencial/ e robo_rotas/) para instalar ou atualizar

Usa o `scp` do próprio Windows (OpenSSH) com a chave SSH do Lucas. Os painéis têm folha com nome: só vão para a VPS
do projeto, atrás da senha da gestão. Nada de base bruta sobe: só o HTML e o xlsx que o pipeline gerou.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from gerencial.app import NOME_PAINEL, RAIZ


def _scp(origens: list[Path], destino: str, recursivo: bool = False):
    cmd = ["scp", "-q"] + (["-r"] if recursivo else []) + [str(p) for p in origens] + [destino]
    print("  " + " ".join(f'"{c}"' if " " in c else c for c in cmd[:3]) + f" ... ({len(origens)}) {destino}")
    subprocess.run(cmd, check=True)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0].startswith("-"):
        print(__doc__)
        return 1
    alvo = argv[0]
    if "--codigo" in argv:
        subprocess.run(["ssh", alvo, "mkdir -p /root/osorio"], check=True)
        _scp([RAIZ / "gerencial", RAIZ / "robo_rotas"], f"{alvo}:/root/osorio/", recursivo=True)
        print(f"Código enviado. Para instalar ou atualizar: ssh {alvo} 'bash /root/osorio/gerencial/deploy/instalar.sh'")
        return 0
    from pipeline.config import ENTREGA_ATUAL
    arquivos = sorted(p for p in Path(ENTREGA_ATUAL).iterdir() if p.is_file() and NOME_PAINEL.match(p.name))
    if not arquivos:
        print(f"Nada para publicar em {ENTREGA_ATUAL}.")
        return 1
    _scp(arquivos, f"{alvo}:/home/robo/dados/paineis/")
    subprocess.run(["ssh", alvo, "chown -R robo:robo /home/robo/dados/paineis"], check=True)
    print(f"{len(arquivos)} arquivos publicados. Aparecem em /paineis/ na hora.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
