"""Gardes sur le workflow bases.yml (texte) : le déploiement dépend du marqueur « site reconstruit », jamais de la commande."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_deploy_step_requires_site_built_marker_not_command():
    yml = (ROOT / ".github" / "workflows" / "bases.yml").read_text(encoding="utf-8")
    assert yml.count("- name: Déploiement Cloudflare Pages") == 1
    deploy = yml.split("- name: Déploiement Cloudflare Pages", 1)[1]
    assert "[ ! -s .cache/site_built ]" in deploy and "exit 0" in deploy
    assert "wrangler@4 pages deploy site" in deploy
    assert "steps.cmd.outputs.cmd == 'matin'" not in deploy and "steps.cmd.outputs.cmd == 'soir'" not in deploy
    assert "env.CLOUDFLARE_API_TOKEN_BASES != ''" in deploy
