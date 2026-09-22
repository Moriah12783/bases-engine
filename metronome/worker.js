// Métronome Bases — frappe les passes de bases-engine à la minute via workflow_dispatch.
// Ne parle qu'à api.github.com, pour le seul dépôt ci-dessous. Aucune URL publique.
const OWNER_REPO = "Moriah12783/bases-engine";
const WORKFLOW_FILE = "bases.yml";
const INPUT_COMMANDE = "command";   // nom exact de l'input de commande dans bases.yml

// Clé = expression cron telle qu'écrite dans wrangler.toml (égalité stricte de chaîne).
const COMMANDES = {
  "5 9 * * *":  "matin",
  "3 22 * * *": "soir",
  "28 7 * * MON": "hebdo",   // Cloudflare numérote les jours 1 = dimanche … 7 = samedi : le nom du jour lève l'ambiguïté
};

async function dispatch(env, commande) {
  const url = `https://api.github.com/repos/${OWNER_REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`;
  return fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GH_DISPATCH_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "bases-metronome/1.0",          // obligatoire : GitHub refuse les requêtes sans User-Agent
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: "main", inputs: { [INPUT_COMMANDE]: commande, source: "metronome" } }),
  });
}

export default {
  async scheduled(controller, env, ctx) {
    const commande = COMMANDES[controller.cron];
    const quand = new Date(controller.scheduledTime).toISOString();
    if (!commande) {
      console.warn(`métronome : cron non mappé « ${controller.cron} » (${quand}), rien envoyé`);
      return;
    }
    let res = await dispatch(env, commande);
    if (res.status !== 204) {
      const detail = (await res.text()).slice(0, 300);
      console.error(`métronome : ${commande} refusé HTTP ${res.status} — ${detail} — nouvel essai dans 60 s`);
      await new Promise((r) => setTimeout(r, 60_000));   // attente réseau : ne consomme pas le CPU
      res = await dispatch(env, commande);
    }
    if (res.status === 204) {
      console.log(`métronome : ${commande} envoyé (${controller.cron}, prévu ${quand})`);
      return;
    }
    throw new Error(`métronome : ${commande} échoué HTTP ${res.status} après 2 essais`);   // visible dans Metrics → Errors
  },
  async fetch() {
    return new Response("bases-metronome", { status: 404 });
  },
};
