# 9. Future Work and Conclusion

## 9.1 Future Work

- **Enforced faithful citation:** constrain cited indices to the retrieved set
  at decode/post-process time; require an explicit "no KG evidence" state
  instead of free-form citation against an empty set (§7.4).
- **Semantic citation-support checking:** verify that a cited chain *supports*
  the claim it is attached to, not only that it was retrieved (§8).
- **Denser, interaction-specific coverage:** curated supplement–drug interaction
  data and improved entity resolution beyond Latin-binomial matching, to close
  the 10/40 coverage gap that drives most fabrication.
- **Base-model sweep + multi-seed:** establish that the verdict-agreement
  confound (§6.2) and the faithfulness rates are stable across base models and
  seeds; companion v2 benchmark (n = 200, two-annotator IAA).
- **Bilingual grounding:** TCM-term coverage + a citation-faithfulness check
  that reads panel deliberation text, not only `candidate_chains`.

## 9.2 Reproducibility

All numbers in this paper are reproducible from the public repository at
`https://github.com/Syntropy-Health/shrine-health-bioactivity`. The full 40 × 7
prediction matrix, per-system summary with the Cite-Faith / Fabricate columns,
and the herb–drug-interaction ablation are committed under
`research-journal/shared/results/`; Appendix A.6 gives re-render commands,
statistics configuration, base-model and KG-gateway details, and pinned commit
SHAs.

## 9.3 Conclusion

Knowledge-graph grounding is offered as the route to trustworthy clinical
LLMs: cite the evidence and the reasoning becomes auditable. Auditing the
citations of a 6-role grounded panel on supplement–drug safety, we find that
grounding instead manufactures a new failure mode — `diet_os` fabricates a
provenance citation in 40% of predictions, citing chains that were never
retrieved, while posting the matrix-best safety recall and a competitive
verdict-agreement score that hide it entirely. We further show that the two
advantages such systems usually claim are confounded: the verdict-agreement
"lift" over non-grounded baselines is a weak-base-model artifact that vanishes
under a stronger model, and the herb–drug-interaction recall is a gold-triage
artifact that an ablation halves even when real KG chains are supplied. Where
the graph is populated, grounding works and agents cite it faithfully — so the
remedy is not to abandon grounding but to *verify* it: measure
citation-faithfulness, enforce it against the retrieved set, and treat unchecked
citation as the safety liability it is. We release the benchmark, the auditing
instrumentation, and the full result matrix at
`https://github.com/Syntropy-Health/shrine-health-bioactivity`.
