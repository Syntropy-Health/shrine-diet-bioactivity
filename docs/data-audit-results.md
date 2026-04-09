# OpenNutrition Data Audit Results

**Date**: 2026-02-25
**Database**: opennutrition_foods.db
**Total foods**: 326,759
**Foods with nutrition_100g data**: 326,759 (100.00%)

## Key Nutrient Coverage

| Nutrient | Count (non-null, non-zero) | Coverage (%) |
|---|---|---|
| calories | 312,216 | 95.55% |
| protein | 244,231 | 74.74% |
| carbohydrates | 294,811 | 90.22% |
| total_fat | 227,118 | 69.51% |
| dietary_fiber | 175,814 | 53.81% |
| total_sugars | 251,666 | 77.02% |
| sodium | 277,868 | 85.04% |
| saturated_fats | 182,996 | 56.00% |

## Observations

- All 326,759 foods have a `nutrition_100g` JSON column present.
- **Calories** have the highest coverage at 95.55%.
- **Carbohydrates** and **sodium** are well-covered (90%+ and 85%+).
- **Protein** and **total_sugars** have good coverage (~75-77%).
- **Total fat** is at ~70% coverage.
- **Dietary fiber** and **saturated fats** have the lowest coverage (~54-56%).
- The nutrition_100g JSON contains 90 distinct nutrient keys including macros, micros, amino acids, and fatty acid subtypes.

## Implications for Macro Calculation

- A `data_completeness` score should be calculated based on how many of the 6 core macro fields (calories, protein, carbs, fat, fiber, sugar) have non-null/non-zero values.
- Foods with missing nutrient data should still return results but flag incomplete data.
