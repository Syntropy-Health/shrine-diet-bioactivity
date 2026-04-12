"""
Ingest textual corpus into Graphiti KG via Railway REST API + OpenRouter.

Unlike direct Neo4j ingestion (ingest_direct.py), this uses Graphiti's
LLM-powered entity extraction for unstructured text. Graphiti discovers
entities and relationships that aren't explicit in structured databases.

This script:
1. Constructs text episodes from SQLite data (herb monographs, compound profiles)
2. Sends them to the Graphiti Railway server via POST /messages
3. Graphiti's LLM extracts entities/relationships and writes to Neo4j

The Railway Graphiti server must be configured with:
  - OPENAI_API_KEY (= OpenRouter key, since OpenRouter is OpenAI-compatible)
  - OPENAI_BASE_URL=https://openrouter.ai/api/v1
  - MODEL_NAME=nvidia/nemotron-3-nano-30b-a3b:free
  - EMBEDDING_MODEL=nvidia/llama-nemotron-embed-vl-1b-v2:free
  - EMBEDDING_DIM=2048
  - NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

Usage:
    python ingest_graphiti.py              # Ingest herb monographs
    python ingest_graphiti.py --dry-run    # Preview episodes without sending
    python ingest_graphiti.py --corpus     # Ingest text corpus (PubMed-like)
"""

import asyncio
import json
import os
import sqlite3
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

GRAPHITI_URL = os.getenv("GRAPHITI_URL", "https://graphiti-test.up.railway.app")
SQLITE_DB_PATH = os.getenv(
    "SQLITE_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data_local", "herbal_botanicals.db"),
)
MAX_HERBS = int(os.getenv("MAX_HERBS", "50"))
MAX_COMPOUNDS = int(os.getenv("MAX_COMPOUNDS", "50"))


def get_db():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def build_herb_monographs(conn, limit: int) -> list[dict]:
    """Build natural-language monographs from herb data for Graphiti to parse."""
    episodes = []
    cursor = conn.execute("""
        SELECT h.id, h.scientific_name, h.common_name, h.family,
               h.is_food_plant, h.is_edible
        FROM herbs h
        ORDER BY (SELECT COUNT(*) FROM herb_compounds WHERE herb_id = h.id) DESC
        LIMIT ?
    """, (limit,))

    for herb in cursor.fetchall():
        herb = dict(herb)
        herb_id = herb["id"]
        name = herb["common_name"] or herb["scientific_name"]

        # Get top compounds
        compounds = conn.execute("""
            SELECT c.name, c.compound_class, c.bioactivities,
                   hc.plant_part, hc.concentration_high_ppm
            FROM herb_compounds hc
            JOIN compounds c ON hc.compound_id = c.id
            WHERE hc.herb_id = ?
            ORDER BY hc.concentration_high_ppm DESC NULLS LAST
            LIMIT 10
        """, (herb_id,)).fetchall()

        # Get symptoms
        symptoms = conn.execute("""
            SELECT s.name FROM herb_symptoms hs
            JOIN symptoms s ON hs.symptom_id = s.id
            WHERE hs.herb_id = ?
        """, (herb_id,)).fetchall()

        # Build monograph text
        text = f"{name} ({herb['scientific_name']}) is a plant from the {herb['family']} family."
        if herb["is_food_plant"]:
            text += f" {name} is commonly used as a food plant."
        if herb["is_edible"]:
            text += f" {name} is edible."

        if compounds:
            compound_list = []
            for c in compounds:
                c = dict(c)
                entry = c["name"]
                if c["compound_class"]:
                    entry += f" ({c['compound_class']})"
                if c["concentration_high_ppm"]:
                    entry += f" at {c['concentration_high_ppm']} ppm"
                if c["plant_part"]:
                    entry += f" in {c['plant_part']}"
                compound_list.append(entry)
            text += f" Key active compounds include: {', '.join(compound_list[:8])}."

            # Add bioactivities
            all_activities = set()
            for c in compounds:
                try:
                    acts = json.loads(dict(c).get("bioactivities", "[]") or "[]")
                    all_activities.update(acts[:3])
                except (json.JSONDecodeError, TypeError):
                    pass
            if all_activities:
                text += f" Known bioactivities: {', '.join(sorted(all_activities)[:10])}."

        if symptoms:
            symptom_names = [dict(s)["name"] for s in symptoms]
            text += f" Traditionally used for: {', '.join(symptom_names[:8])}."

        episodes.append({
            "group_id": "herbal-monographs",
            "name": f"herb-{herb_id}-{name}",
            "content": text,
            "source": "herb_monograph",
            "source_description": f"Generated monograph for {name} from Duke's Phytochemical DB + bioactivity data",
        })

    return episodes


def build_compound_profiles(conn, limit: int) -> list[dict]:
    """Build compound profiles describing what each compound does and where it's found."""
    episodes = []
    cursor = conn.execute("""
        SELECT c.id, c.name, c.compound_class, c.bioactivities,
               (SELECT COUNT(DISTINCT herb_id) FROM herb_compounds WHERE compound_id = c.id) as herb_count,
               (SELECT COUNT(DISTINCT food_name) FROM compound_foods WHERE compound_id = c.id) as food_count
        FROM compounds c
        ORDER BY herb_count DESC
        LIMIT ?
    """, (limit,))

    for cpd in cursor.fetchall():
        cpd = dict(cpd)
        name = cpd["name"]

        bioactivities = []
        try:
            bioactivities = json.loads(cpd.get("bioactivities", "[]") or "[]")
        except (json.JSONDecodeError, TypeError):
            pass

        # Get herbs containing this compound
        herbs = conn.execute("""
            SELECT h.common_name, h.scientific_name
            FROM herb_compounds hc JOIN herbs h ON hc.herb_id = h.id
            WHERE hc.compound_id = ? LIMIT 5
        """, (cpd["id"],)).fetchall()

        # Get targets
        targets = conn.execute("""
            SELECT t.name, ct.activity_type
            FROM compound_targets ct JOIN targets t ON ct.target_id = t.id
            WHERE ct.compound_id = ? LIMIT 5
        """, (cpd["id"],)).fetchall()

        text = f"{name} is a {cpd['compound_class'] or 'phytochemical'} compound."
        text += f" It is found in {cpd['herb_count']} herbs and {cpd['food_count']} foods."

        if herbs:
            herb_names = [dict(h)["common_name"] or dict(h)["scientific_name"] for h in herbs]
            text += f" Source herbs include: {', '.join(herb_names)}."

        if bioactivities:
            text += f" Bioactivities: {', '.join(bioactivities[:8])}."

        if targets:
            target_info = [f"{dict(t)['name']} ({dict(t)['activity_type'] or 'binding'})" for t in targets]
            text += f" Molecular targets: {', '.join(target_info)}."

        episodes.append({
            "group_id": "compound-profiles",
            "name": f"compound-{cpd['id']}-{name}",
            "content": text,
            "source": "compound_profile",
            "source_description": f"Generated profile for {name} from Duke + CMAUP data",
        })

    return episodes


# Sample textual corpus — simulated PubMed-style abstracts
SAMPLE_CORPUS = [
    {
        "group_id": "pubmed-abstracts",
        "name": "pmid-anti-inflammatory-curcumin",
        "content": (
            "Curcumin, the principal curcuminoid of turmeric (Curcuma longa), has been shown to "
            "inhibit NF-κB signaling pathway, reducing the production of pro-inflammatory cytokines "
            "including TNF-α, IL-1β, and IL-6. In a randomized controlled trial of 40 patients with "
            "rheumatoid arthritis, curcumin supplementation (500mg/day for 8 weeks) significantly "
            "reduced joint swelling and morning stiffness compared to placebo (p<0.001). The mechanism "
            "involves direct binding to IKKβ, preventing IκBα phosphorylation and subsequent nuclear "
            "translocation of NF-κB. These findings suggest curcumin as a promising adjunct therapy "
            "for inflammatory conditions."
        ),
        "source": "pubmed_abstract",
        "source_description": "Simulated PubMed abstract on curcumin anti-inflammatory mechanism",
    },
    {
        "group_id": "pubmed-abstracts",
        "name": "pmid-ashwagandha-stress",
        "content": (
            "Withania somnifera (Ashwagandha) root extract containing withanolides demonstrated "
            "significant anxiolytic and adaptogenic effects in a double-blind RCT of 64 adults with "
            "chronic stress. The treatment group receiving 300mg KSM-66 extract twice daily showed "
            "reduced serum cortisol levels by 27.9% (p=0.002) and improved scores on the Hamilton "
            "Anxiety Rating Scale after 60 days. Withanolide A was identified as the primary active "
            "compound, modulating GABAergic neurotransmission via positive allosteric modulation of "
            "GABA-A receptors. Ashwagandha also upregulated BDNF expression in hippocampal neurons, "
            "suggesting neuroprotective properties beyond acute stress relief."
        ),
        "source": "pubmed_abstract",
        "source_description": "Simulated PubMed abstract on ashwagandha adaptogenic mechanism",
    },
    {
        "group_id": "pubmed-abstracts",
        "name": "pmid-quercetin-allergy",
        "content": (
            "Quercetin, a flavonoid abundant in onions, apples, and green tea, has demonstrated "
            "potent mast cell stabilizing activity. In vitro studies show quercetin inhibits histamine "
            "release from human basophils and mast cells by suppressing calcium influx through TRPV1 "
            "channels. A meta-analysis of 7 clinical trials (n=380) found quercetin supplementation "
            "(500-1000mg/day) reduced allergic rhinitis symptoms by 36% vs placebo. Quercetin also "
            "inhibits lipoxygenase and cyclooxygenase pathways, reducing leukotriene and prostaglandin "
            "synthesis. Foods with highest quercetin content include capers (234mg/100g), red onions "
            "(32mg/100g), and cranberries (15mg/100g)."
        ),
        "source": "pubmed_abstract",
        "source_description": "Simulated PubMed abstract on quercetin anti-allergic mechanism",
    },
    {
        "group_id": "pubmed-abstracts",
        "name": "pmid-ginger-nausea",
        "content": (
            "Zingiber officinale (ginger) contains gingerols and shogaols that act on 5-HT3 "
            "serotonin receptors in the gastrointestinal tract, providing antiemetic effects. "
            "A Cochrane review of 12 RCTs (n=1,278) confirmed ginger's efficacy for pregnancy-related "
            "nausea (RR 0.45, 95% CI 0.28-0.73) at doses of 1g/day. 6-gingerol specifically "
            "antagonizes 5-HT3 receptors with IC50 of 8.2μM, comparable to ondansetron. Ginger also "
            "promotes gastric motility through cholinergic M3 receptor agonism. Functional foods rich "
            "in gingerols include fresh ginger root, crystallized ginger, and ginger tea."
        ),
        "source": "pubmed_abstract",
        "source_description": "Simulated PubMed abstract on ginger antiemetic mechanism",
    },
    {
        "group_id": "pubmed-abstracts",
        "name": "pmid-berberine-diabetes",
        "content": (
            "Berberine, an isoquinoline alkaloid from Coptis chinensis and Berberis species, "
            "activates AMP-activated protein kinase (AMPK) in skeletal muscle and liver, enhancing "
            "glucose uptake and insulin sensitivity. A meta-analysis of 14 RCTs (n=1,068 T2DM patients) "
            "found berberine reduced HbA1c by 0.9% (95% CI 0.6-1.2%), fasting glucose by 1.2 mmol/L, "
            "and triglycerides by 0.4 mmol/L. The mechanism involves inhibition of mitochondrial "
            "complex I, increasing AMP:ATP ratio, which triggers AMPK phosphorylation. Berberine also "
            "modulates gut microbiota composition, increasing Akkermansia muciniphila abundance. "
            "Unlike metformin, berberine has additional lipid-lowering effects via PCSK9 downregulation."
        ),
        "source": "pubmed_abstract",
        "source_description": "Simulated PubMed abstract on berberine antidiabetic mechanism",
    },
]


async def send_to_graphiti(client: httpx.AsyncClient, episode: dict, dry_run: bool = False) -> bool:
    """Send an episode to the Graphiti Railway server via POST /messages."""
    if dry_run:
        print(f"  [DRY RUN] {episode['name']}: {episode['content'][:80]}...")
        return True

    try:
        resp = await client.post(
            f"{GRAPHITI_URL}/messages",
            json={
                "group_id": episode["group_id"],
                "messages": [{
                    "content": episode["content"],
                    "name": episode.get("name", ""),
                    "role_type": "user",
                    "role": episode.get("source", "researcher"),
                    "timestamp": "2026-04-10T15:00:00Z",
                    "source_description": episode.get("source_description", ""),
                }],
            },
            timeout=120.0,
        )
        if resp.status_code in (200, 202):
            print(f"  ✅ {episode['name']}")
            return True
        else:
            print(f"  ❌ {episode['name']}: HTTP {resp.status_code} — {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  ❌ {episode['name']}: {e}")
        return False


async def main():
    dry_run = "--dry-run" in sys.argv
    corpus_only = "--corpus" in sys.argv

    conn = get_db()
    all_episodes = []

    if not corpus_only:
        print(f"Building herb monographs (limit {MAX_HERBS})...")
        all_episodes.extend(build_herb_monographs(conn, MAX_HERBS))

        print(f"Building compound profiles (limit {MAX_COMPOUNDS})...")
        all_episodes.extend(build_compound_profiles(conn, MAX_COMPOUNDS))

    print(f"Adding sample PubMed corpus ({len(SAMPLE_CORPUS)} abstracts)...")
    all_episodes.extend(SAMPLE_CORPUS)

    conn.close()

    print(f"\n=== Graphiti Text Ingestion ===")
    print(f"  Graphiti URL: {GRAPHITI_URL}")
    print(f"  Total episodes: {len(all_episodes)}")
    print(f"  Groups: {set(e['group_id'] for e in all_episodes)}")

    if dry_run:
        print("\n--- DRY RUN ---")
        for ep in all_episodes:
            print(f"  [{ep['group_id']}] {ep['name']}: {ep['content'][:100]}...")
        print(f"\nWould ingest {len(all_episodes)} episodes.")
        return

    async with httpx.AsyncClient() as client:
        # Check Graphiti health
        health = await client.get(f"{GRAPHITI_URL}/healthcheck", timeout=10)
        print(f"  Graphiti health: {health.json()}")

        success = 0
        failed = 0
        start = time.time()

        for i, episode in enumerate(all_episodes):
            ok = await send_to_graphiti(client, episode)
            if ok:
                success += 1
            else:
                failed += 1

            # Rate limit: 1 episode per 2 seconds to avoid overwhelming free tier
            if i < len(all_episodes) - 1:
                await asyncio.sleep(1.0)

            if (i + 1) % 10 == 0:
                elapsed = time.time() - start
                rate = (i + 1) / elapsed
                print(f"  Progress: {i + 1}/{len(all_episodes)} ({rate:.1f} ep/s)")

        elapsed = time.time() - start
        print(f"\n=== Complete ===")
        print(f"  Success: {success}, Failed: {failed}")
        print(f"  Time: {elapsed:.1f}s ({len(all_episodes) / elapsed:.2f} ep/s)")


if __name__ == "__main__":
    asyncio.run(main())
