import { describe, it, expect } from "vitest";
import cases from "../../../../tests/compositions/fixtures/contracts.json";
import * as models from "./models.js";
it("accepts saved experiment samples above the former fixed cap", () => {
  const request = {
    algorithm_id: "hdbscan", algorithm_version: null, parameters: {},
    seed: 42, sample_size: 20001, full_population: false,
    source_kind: "active", snapshot_id: null,
  };
  expect(models.ExperimentRequestSchema.safeParse(request).success).toBe(true);
  for (const sample_size of [0, -1, 1.5]) {
    expect(models.ExperimentRequestSchema.safeParse({ ...request, sample_size }).success).toBe(false);
  }
});
describe("shared Pydantic/Zod wire fixtures", () => {
  for (const fixture of cases)
    it(fixture.name, () => {
      expect(
        models[`${fixture.schema}Schema`].safeParse(fixture.value).success,
      ).toBe(fixture.valid);
    });
});
