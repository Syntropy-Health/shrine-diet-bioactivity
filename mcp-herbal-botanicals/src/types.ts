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
