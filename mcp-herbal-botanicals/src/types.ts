/** Shared types for the mcp-herbal-botanicals server. */

export interface Herb {
  id: string;
  scientific_name: string;
  common_name: string | null;
  family: string | null;
  genus: string | null;
  species: string | null;
  usage_type: string | null;
  alternate_names: string[];
  is_food_plant: boolean;
  is_edible: boolean;
}

export interface Compound {
  id: string;
  name: string;
  name_normalized: string;
  cas_number: string | null;
  pubchem_cid: string | null;
  compound_class: string | null;
  bioactivities: string[];
}

export interface HerbCompound {
  herb_id: string;
  compound_id: string;
  compound_name: string;
  plant_part: string | null;
  plant_part_code: string | null;
  concentration_low_ppm: number | null;
  concentration_high_ppm: number | null;
  compound_class: string | null;
}

export interface CompoundFood {
  compound_id: string;
  compound_name: string;
  food_name: string;
  food_name_scientific: string | null;
  food_group: string | null;
  content_value: number | null;
  content_min: number | null;
  content_max: number | null;
  content_unit: string | null;
  food_part: string | null;
}

export interface HerbFoodOverlap {
  food_name: string;
  food_name_scientific: string | null;
  food_group: string | null;
  shared_compounds: number;
  compound_names: string[];
  overlap_score: number;
}

export interface PaginatedResult<T> {
  data: T[];
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
}

export interface Symptom {
  id: string;
  name: string;
  symptom_type: 'tcm' | 'modern' | 'bioactivity';
  mm_symptom_id: string | null;
  description: string | null;
}

export interface Target {
  id: string;
  name: string;
  uniprot_id: string | null;
  gene_symbol: string | null;
}

export interface CompoundTarget {
  compound_id: string;
  compound_name: string;
  target_id: string;
  target_name: string;
  activity_value: number | null;
  activity_type: string | null;
  interaction_type: string | null;
}

export interface SymptomSearchResult {
  symptoms_matched: Symptom[];
  herbs: Array<{
    id: string;
    common_name: string | null;
    scientific_name: string;
    is_food_plant: boolean;
    compound_count: number;
  }>;
  compounds: Array<{
    id: string;
    name: string;
    compound_class: string | null;
    bioactivities: string[];
    herb_count: number;
    food_count: number;
  }>;
  functional_foods: Array<{
    food_name: string;
    food_group: string | null;
    shared_compounds: number;
    compound_names: string[];
  }>;
}

export interface FunctionalFood {
  food_name: string;
  food_group: string | null;
  herb_name: string | null;
  herb_scientific_name: string;
  compound_count: number;
  compound_names: string[];
}
