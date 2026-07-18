# Labeling operativo — Punto 1

Questa cartella definisce come produrre annotazioni e ground truth per la decomposizione atomica di PlanimetryAI.

Documenti:

- [`ANNOTATION_GUIDELINES.md`](ANNOTATION_GUIDELINES.md): unità annotabili, geometrie, attributi, relazioni e casi ambigui;
- [`QA_WORKFLOW.md`](QA_WORKFLOW.md): ruoli, stati, review, golden task, consensus e congelamento;
- [`DATASET_MINIMUM.md`](DATASET_MINIMUM.md): proposta minima per pilot, calibrazione e dataset di accettazione.

Fonti vincolanti:

1. `PlanParser/DECOMPOSITION_SPEC.md`;
2. `PlanParser/decomposition/taxonomy.v1.json`;
3. `PlanParser/decomposition/decomposition.schema.json`;
4. [`../dataset/DATASET_SPEC.md`](../dataset/DATASET_SPEC.md) e il manifest machine-readable della release per split, diritti, fingerprint e controlli anti-leakage.

In caso di conflitto prevalgono i contratti P1: schema/tassonomia per le annotazioni e specifica/manifest dataset per split e anti-leakage. Questi documenti non estendono lo schema e non descrivono il Knowledge Model del Punto 2.

Versione linee guida: `labeling-guidelines/1.0.0`.
