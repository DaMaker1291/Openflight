Subject: Robust radar-based localisation and mapping — small computational contribution

Dear Dr. Wang,

I am a Year 11 student at Merchant Taylors' School Northwood with a strong interest in robotics and simultaneous localization and mapping. I have been reading your paper *RadarSLAM: A Robust Simultaneous Localization and Mapping System for All Weather Conditions* (Sage Journal, 2022) and am writing because your lab opportunities page invites prospective collaborators to enquire about potential topics.

**My background:**

I have built OpenFlight, an open-source toolkit for validating sensor-to-model compatibility in embedded ML deployment. At a pinned development revision (commit `972e23e`, October 2026), a clean-checkout Linux/WSL run passed 298/300 software tests, and I have generated `experiment-package.json` with full provenance (model metadata, contracts, genome, parity results, SHA-256 artifact hashes, and `human_notes`). I also maintain a reproducibility pipeline that records environment, commands, and output for every experiment.

**RadarSLAM — what interests me:**

Your paper documents a robust SLAM system that operates across all weather conditions, using radar data for simultaneous localization and mapping. I am particularly interested in the robustness evaluation — how the system handles dynamic obstacles, sensor dropouts, and varying environmental conditions. While OpenFlight does not implement SLAM, my skills in experiment design, numerical parity testing, and reproducibility pipelines could be useful for evaluating or extending published results.

**A concrete task I could carry out:**

I would like to offer a small, supervised computational contribution to your lab's existing research. Specifically:

- Reproduce the localization result for one documented sequence from the repository, recording the exact command, environment, and trajectory/metric output
- Implement a documented variation (e.g., a subset of radar sensors, a filtered input pipeline) and compare the resulting trajectory against the baseline
- Write a short reproducibility report documenting the environment, commands, output, and any discrepancies — following the same format as my DiTMoS reproduction report

I have experience running structured experiments, capturing precise output, and documenting limitations. I am available 3–4 hours per week during the school year, remote.

I would be grateful if you could advise whether such a task would be useful, and I am happy to provide my CV and open-source code for your review.

Thank you for your consideration.

Kind regards,

Shaurjesh Basu  
Year 11, Merchant Taylors' School Northwood  
GitHub: github.com/DaMaker1291/Openflight  
Email: shaurjesh.basu (school domain)

---

*Attached: CV (one page)*
*Evidence: OpenFlight at commit `972e23e`; experiment-record/reproduce pipeline; DiTMoS reproducibility experience*