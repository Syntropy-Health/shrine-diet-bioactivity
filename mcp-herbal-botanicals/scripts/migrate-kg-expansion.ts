/**
 * Migrate herbal_botanicals.db with knowledge graph expansion tables.
 *
 * Adds: symptoms, herb_symptoms, targets, compound_targets, target_diseases.
 * Enriches: herbs table with is_food_plant and is_edible columns.
 * Seeds: symptom data from existing bioactivities in Dr. Duke's AGGREGAC data.
 *
 * This is an incremental migration — it does NOT rebuild the database.
 * Safe to run multiple times (all operations are IF NOT EXISTS / OR IGNORE).
 *
 * Usage:
 *   tsx scripts/migrate-kg-expansion.ts
 */

import * as fs from 'fs';
import * as path from 'path';
import Database from 'better-sqlite3';

const DB_PATH = path.join(process.cwd(), 'data_local', 'herbal_botanicals.db');

// ---------------------------------------------------------------------------
// Bioactivity → symptom mapping
// Maps Dr. Duke's bioactivity tags to structured symptom entries.
// ---------------------------------------------------------------------------

const BIOACTIVITY_SYMPTOM_MAP: Record<string, { name: string; type: 'modern' | 'bioactivity'; description: string }> = {
  'Antiinflammatory': { name: 'Inflammation', type: 'modern', description: 'Chronic or acute inflammation' },
  'Analgesic': { name: 'Pain', type: 'modern', description: 'Pain relief' },
  'Antidepressant': { name: 'Depression', type: 'modern', description: 'Depressive symptoms' },
  'Anxiolytic': { name: 'Anxiety', type: 'modern', description: 'Anxiety and stress' },
  'Sedative': { name: 'Insomnia', type: 'modern', description: 'Sleep difficulty' },
  'Hypnotic': { name: 'Insomnia', type: 'modern', description: 'Sleep difficulty' },
  'Antidiabetic': { name: 'Diabetes', type: 'modern', description: 'Blood sugar dysregulation' },
  'Hypoglycemic': { name: 'High blood sugar', type: 'modern', description: 'Elevated blood glucose' },
  'Hypotensive': { name: 'Hypertension', type: 'modern', description: 'High blood pressure' },
  'Antihypertensive': { name: 'Hypertension', type: 'modern', description: 'High blood pressure' },
  'Antiarthritic': { name: 'Arthritis', type: 'modern', description: 'Joint inflammation and pain' },
  'Antiasthmatic': { name: 'Asthma', type: 'modern', description: 'Respiratory difficulty' },
  'Antiallergic': { name: 'Allergies', type: 'modern', description: 'Allergic reactions' },
  'Antioxidant': { name: 'Oxidative stress', type: 'bioactivity', description: 'Cellular oxidative damage' },
  'Immunostimulant': { name: 'Low immunity', type: 'modern', description: 'Weak immune function' },
  'Immunomodulator': { name: 'Immune dysfunction', type: 'modern', description: 'Immune system imbalance' },
  'Adaptogenic': { name: 'Stress', type: 'modern', description: 'Physical and mental stress adaptation' },
  'Hepatoprotective': { name: 'Liver damage', type: 'modern', description: 'Liver protection and repair' },
  'Cardioprotective': { name: 'Heart disease', type: 'modern', description: 'Cardiovascular protection' },
  'Neuroprotective': { name: 'Neurodegeneration', type: 'modern', description: 'Brain and nerve cell protection' },
  'Antiulcer': { name: 'Stomach ulcer', type: 'modern', description: 'Gastric ulcer' },
  'Antidiarrheal': { name: 'Diarrhea', type: 'modern', description: 'Loose stools' },
  'Laxative': { name: 'Constipation', type: 'modern', description: 'Difficulty with bowel movements' },
  'Diuretic': { name: 'Fluid retention', type: 'modern', description: 'Water retention and edema' },
  'Expectorant': { name: 'Cough', type: 'modern', description: 'Productive cough' },
  'Antitussive': { name: 'Cough', type: 'modern', description: 'Dry cough' },
  'Antipyretic': { name: 'Fever', type: 'modern', description: 'Elevated body temperature' },
  'Antimigraine': { name: 'Migraine', type: 'modern', description: 'Migraine headache' },
  'Antispasmodic': { name: 'Muscle spasm', type: 'modern', description: 'Involuntary muscle contractions' },
  'Antiemetic': { name: 'Nausea', type: 'modern', description: 'Nausea and vomiting' },
  'Anticancer': { name: 'Cancer', type: 'modern', description: 'Cancer prevention or treatment' },
  'Antitumor': { name: 'Cancer', type: 'modern', description: 'Tumor growth inhibition' },
  'Antiviral': { name: 'Viral infection', type: 'modern', description: 'Viral illness' },
  'Antibacterial': { name: 'Bacterial infection', type: 'modern', description: 'Bacterial illness' },
  'Antifungal': { name: 'Fungal infection', type: 'modern', description: 'Fungal illness' },
  'Antiparasitic': { name: 'Parasitic infection', type: 'modern', description: 'Parasitic illness' },
  'Vermifuge': { name: 'Parasitic infection', type: 'modern', description: 'Intestinal worms' },
  'Antiobesity': { name: 'Obesity', type: 'modern', description: 'Weight management difficulty' },
  'Antiaging': { name: 'Aging', type: 'bioactivity', description: 'Age-related decline' },
  'Antifatigue': { name: 'Fatigue', type: 'modern', description: 'Chronic tiredness and low energy' },
  'Tonic': { name: 'Fatigue', type: 'modern', description: 'General weakness and low vitality' },
  'Aphrodisiac': { name: 'Low libido', type: 'modern', description: 'Reduced sexual desire' },
  'Galactagogue': { name: 'Low milk supply', type: 'modern', description: 'Insufficient breast milk production' },
  'Choleretic': { name: 'Bile insufficiency', type: 'modern', description: 'Poor bile production' },
  'Vulnerary': { name: 'Wound healing', type: 'modern', description: 'Slow wound recovery' },
  'Anticoagulant': { name: 'Blood clotting', type: 'modern', description: 'Excess blood coagulation' },
  'Vasorelaxant': { name: 'Poor circulation', type: 'modern', description: 'Restricted blood flow' },
  'Vasodilator': { name: 'Poor circulation', type: 'modern', description: 'Restricted blood flow' },
  'Antidermatitic': { name: 'Skin inflammation', type: 'modern', description: 'Dermatitis and eczema' },
  'Antieczemic': { name: 'Eczema', type: 'modern', description: 'Chronic skin condition' },
  'Antiacne': { name: 'Acne', type: 'modern', description: 'Skin breakouts' },
  'Antialopecic': { name: 'Hair loss', type: 'modern', description: 'Alopecia' },
  'Memory-Enhancer': { name: 'Memory decline', type: 'modern', description: 'Cognitive decline and poor memory' },
  'Nootropic': { name: 'Cognitive decline', type: 'modern', description: 'Reduced mental function' },
};

// Known food plants — herbs that are commonly eaten as food
const FOOD_PLANT_NAMES = new Set([
  'turmeric', 'ginger', 'garlic', 'onion', 'cinnamon', 'black pepper',
  'cayenne', 'rosemary', 'thyme', 'oregano', 'basil', 'sage', 'parsley',
  'dill', 'cilantro', 'coriander', 'cumin', 'fenugreek', 'fennel',
  'cardamom', 'clove', 'nutmeg', 'saffron', 'vanilla', 'cocoa',
  'tea', 'coffee', 'chamomile', 'peppermint', 'spearmint', 'lemongrass',
  'lavender', 'hibiscus', 'dandelion', 'nettle', 'elderberry', 'elderflower',
  'cranberry', 'blueberry', 'grape', 'pomegranate', 'olive', 'coconut',
  'flax', 'sesame', 'sunflower', 'almond', 'walnut', 'hazelnut',
  'oat', 'barley', 'rice', 'wheat', 'corn', 'quinoa', 'buckwheat',
  'soy', 'lentil', 'chickpea', 'mung', 'adzuki',
  'spinach', 'kale', 'broccoli', 'cabbage', 'cauliflower', 'carrot',
  'beet', 'celery', 'artichoke', 'asparagus', 'sweet potato',
  'avocado', 'tomato', 'bell pepper', 'chili', 'jalapeño',
  'lemon', 'lime', 'orange', 'grapefruit', 'banana', 'mango',
  'papaya', 'pineapple', 'watermelon', 'fig', 'date', 'raisin',
  'honey', 'maple', 'stevia', 'licorice', 'anise', 'star anise',
  'mustard', 'horseradish', 'wasabi', 'ginseng',
]);

// Edible but not commonly eaten as food
const EDIBLE_PLANT_NAMES = new Set([
  'ashwagandha', 'valerian', 'echinacea', 'milk thistle', 'ginkgo',
  'saw palmetto', "st. john's wort", 'passionflower', 'skullcap',
  'rhodiola', 'astragalus', 'maca', 'moringa', 'neem', 'tulsi',
  'holy basil', 'aloe', 'cat claw', 'devils claw',
  'black cohosh', 'dong quai', 'evening primrose', 'boswellia',
  'hawthorn', 'gotu kola', 'bacopa', 'schisandra', 'tribulus',
  'pygeum', 'cranberry', 'marshmallow', 'slippery elm',
  'goldenseal', 'kava', 'kratom', 'yerba mate',
]);

function slugify(name: string): string {
  return name.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
}

function runMigration(): void {
  if (!fs.existsSync(DB_PATH)) {
    throw new Error(`Database not found at ${DB_PATH}. Run 'npm run convert-data' first.`);
  }

  console.error('=== KG Expansion Migration ===');
  const db = new Database(DB_PATH);
  db.pragma('journal_mode = WAL');
  db.pragma('foreign_keys = OFF');

  try {
    // -----------------------------------------------------------------------
    // Step 1: Add new columns to herbs table
    // -----------------------------------------------------------------------
    console.error('  Adding food plant columns to herbs table...');
    try {
      db.exec('ALTER TABLE herbs ADD COLUMN is_food_plant INTEGER DEFAULT 0');
    } catch { /* column already exists */ }
    try {
      db.exec('ALTER TABLE herbs ADD COLUMN is_edible INTEGER DEFAULT 0');
    } catch { /* column already exists */ }

    // -----------------------------------------------------------------------
    // Step 2: Create new tables
    // -----------------------------------------------------------------------
    console.error('  Creating new tables...');
    db.exec(`
      CREATE TABLE IF NOT EXISTS symptoms (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        symptom_type TEXT NOT NULL,
        mm_symptom_id TEXT,
        description TEXT,
        source TEXT DEFAULT 'duke_bioactivity'
      );

      CREATE TABLE IF NOT EXISTS herb_symptoms (
        herb_id TEXT NOT NULL,
        symptom_id TEXT NOT NULL,
        evidence_type TEXT DEFAULT 'bioactivity_derived',
        source TEXT DEFAULT 'duke_bioactivity',
        PRIMARY KEY (herb_id, symptom_id)
      );

      CREATE TABLE IF NOT EXISTS targets (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        uniprot_id TEXT,
        gene_symbol TEXT,
        source TEXT DEFAULT 'cmaup'
      );

      CREATE TABLE IF NOT EXISTS compound_targets (
        compound_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        activity_value REAL,
        activity_type TEXT,
        interaction_type TEXT,
        source TEXT DEFAULT 'cmaup',
        PRIMARY KEY (compound_id, target_id, source)
      );

      CREATE TABLE IF NOT EXISTS target_diseases (
        target_id TEXT NOT NULL,
        disease_name TEXT NOT NULL,
        disease_id TEXT,
        evidence_layer TEXT,
        source TEXT DEFAULT 'cmaup',
        PRIMARY KEY (target_id, disease_name, source)
      );

      -- Indexes for new tables
      CREATE INDEX IF NOT EXISTS idx_symptoms_name ON symptoms(name);
      CREATE INDEX IF NOT EXISTS idx_symptoms_type ON symptoms(symptom_type);
      CREATE INDEX IF NOT EXISTS idx_herb_symptoms_herb ON herb_symptoms(herb_id);
      CREATE INDEX IF NOT EXISTS idx_herb_symptoms_symptom ON herb_symptoms(symptom_id);
      CREATE INDEX IF NOT EXISTS idx_targets_name ON targets(name);
      CREATE INDEX IF NOT EXISTS idx_targets_uniprot ON targets(uniprot_id);
      CREATE INDEX IF NOT EXISTS idx_compound_targets_compound ON compound_targets(compound_id);
      CREATE INDEX IF NOT EXISTS idx_compound_targets_target ON compound_targets(target_id);
      CREATE INDEX IF NOT EXISTS idx_target_diseases_target ON target_diseases(target_id);
    `);

    // -----------------------------------------------------------------------
    // Step 3: Seed symptoms from bioactivity mapping
    // -----------------------------------------------------------------------
    console.error('  Seeding symptoms from bioactivity data...');
    const insertSymptom = db.prepare(`
      INSERT OR IGNORE INTO symptoms (id, name, symptom_type, mm_symptom_id, description, source)
      VALUES (?, ?, ?, NULL, ?, 'duke_bioactivity')
    `);

    const seenSymptoms = new Set<string>();
    const seedSymptoms = db.transaction(() => {
      for (const [, mapping] of Object.entries(BIOACTIVITY_SYMPTOM_MAP)) {
        const symptomId = slugify(mapping.name);
        if (seenSymptoms.has(symptomId)) continue;
        seenSymptoms.add(symptomId);
        insertSymptom.run(symptomId, mapping.name, mapping.type, mapping.description);
      }
    });
    seedSymptoms();
    console.error(`    Seeded ${seenSymptoms.size} symptoms`);

    // -----------------------------------------------------------------------
    // Step 4: Build herb_symptoms from compounds.bioactivities
    // -----------------------------------------------------------------------
    console.error('  Building herb-symptom links from bioactivity data...');

    // For each herb, get its compounds' bioactivities, map to symptoms
    const herbCompounds = db.prepare(`
      SELECT DISTINCT hc.herb_id, c.bioactivities
      FROM herb_compounds hc
      JOIN compounds c ON hc.compound_id = c.id
      WHERE c.bioactivities IS NOT NULL AND c.bioactivities != '[]'
    `).all() as Array<{ herb_id: string; bioactivities: string }>;

    const insertHerbSymptom = db.prepare(`
      INSERT OR IGNORE INTO herb_symptoms (herb_id, symptom_id, evidence_type, source)
      VALUES (?, ?, 'bioactivity_derived', 'duke_bioactivity')
    `);

    let herbSymptomCount = 0;
    const buildHerbSymptoms = db.transaction(() => {
      for (const row of herbCompounds) {
        let activities: string[];
        try {
          activities = JSON.parse(row.bioactivities);
        } catch { continue; }

        for (const activity of activities) {
          const mapping = BIOACTIVITY_SYMPTOM_MAP[activity];
          if (!mapping) continue;
          const symptomId = slugify(mapping.name);
          insertHerbSymptom.run(row.herb_id, symptomId);
          herbSymptomCount++;
        }
      }
    });
    buildHerbSymptoms();

    const actualLinks = (db.prepare('SELECT COUNT(*) as cnt FROM herb_symptoms').get() as { cnt: number }).cnt;
    console.error(`    Created ${actualLinks} herb-symptom links`);

    // -----------------------------------------------------------------------
    // Step 5: Flag food plants and edible plants
    // -----------------------------------------------------------------------
    console.error('  Flagging food plants and edible plants...');

    const allHerbs = db.prepare('SELECT id, common_name, alternate_names FROM herbs').all() as Array<{
      id: string;
      common_name: string | null;
      alternate_names: string | null;
    }>;

    const updateFoodPlant = db.prepare('UPDATE herbs SET is_food_plant = 1 WHERE id = ?');
    const updateEdible = db.prepare('UPDATE herbs SET is_edible = 1 WHERE id = ?');

    let foodCount = 0;
    let edibleCount = 0;

    const flagPlants = db.transaction(() => {
      for (const herb of allHerbs) {
        const names: string[] = [];
        if (herb.common_name) names.push(herb.common_name.toLowerCase());
        try {
          const alts = JSON.parse(herb.alternate_names || '[]');
          if (Array.isArray(alts)) {
            for (const a of alts) names.push(String(a).toLowerCase());
          }
        } catch { /* ignore */ }

        let isFood = false;
        let isEdible = false;

        for (const name of names) {
          for (const foodName of FOOD_PLANT_NAMES) {
            if (name.includes(foodName)) { isFood = true; break; }
          }
          if (isFood) break;
          for (const edibleName of EDIBLE_PLANT_NAMES) {
            if (name.includes(edibleName)) { isEdible = true; break; }
          }
          if (isEdible) break;
        }

        if (isFood) {
          updateFoodPlant.run(herb.id);
          updateEdible.run(herb.id); // food plants are also edible
          foodCount++;
        } else if (isEdible) {
          updateEdible.run(herb.id);
          edibleCount++;
        }
      }
    });
    flagPlants();
    console.error(`    Flagged ${foodCount} food plants, ${edibleCount} additional edible plants`);

    // -----------------------------------------------------------------------
    // Summary
    // -----------------------------------------------------------------------
    const stats = {
      symptoms: (db.prepare('SELECT COUNT(*) as cnt FROM symptoms').get() as { cnt: number }).cnt,
      herb_symptoms: (db.prepare('SELECT COUNT(*) as cnt FROM herb_symptoms').get() as { cnt: number }).cnt,
      targets: (db.prepare('SELECT COUNT(*) as cnt FROM targets').get() as { cnt: number }).cnt,
      compound_targets: (db.prepare('SELECT COUNT(*) as cnt FROM compound_targets').get() as { cnt: number }).cnt,
      target_diseases: (db.prepare('SELECT COUNT(*) as cnt FROM target_diseases').get() as { cnt: number }).cnt,
      food_plants: (db.prepare('SELECT COUNT(*) as cnt FROM herbs WHERE is_food_plant = 1').get() as { cnt: number }).cnt,
      edible_plants: (db.prepare('SELECT COUNT(*) as cnt FROM herbs WHERE is_edible = 1').get() as { cnt: number }).cnt,
    };

    console.error('\n=== KG Expansion Summary ===');
    console.error(`  Symptoms:          ${stats.symptoms}`);
    console.error(`  Herb-Symptoms:     ${stats.herb_symptoms}`);
    console.error(`  Targets:           ${stats.targets} (empty — awaiting CMAUP data)`);
    console.error(`  Compound-Targets:  ${stats.compound_targets} (empty — awaiting CMAUP data)`);
    console.error(`  Target-Diseases:   ${stats.target_diseases} (empty — awaiting CMAUP data)`);
    console.error(`  Food plants:       ${stats.food_plants}`);
    console.error(`  Edible plants:     ${stats.edible_plants}`);
    console.error('=== Migration complete ===');
  } finally {
    db.close();
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  runMigration();
}

export { runMigration };
