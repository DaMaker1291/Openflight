Subject: Evaluating when online depth training is worth the computational cost

Dr. Karaman,

I am a Year 11 student at Merchant Taylors' School Northwood researching embedded machine learning and systems for deployment on microcontrollers. I read your DecTrain paper *Deciding When to Train a Monocular Depth DNN Online* (arXiv:2410.02980) and am writing because your work on adaptive online training criteria intersects with my interest in evaluating learned systems under deployment constraints.

**My background:**

I have built OpenFlight, an open-source toolkit for validating sensor-to-model compatibility in embedded ML deployment. A clean-checkout Linux/WSL run at commit `972e23e` (October 2026) passed 298/300 software tests, and I have generated `experiment-package.json` with full provenance for every experiment. I also have experience designing reproducibility pipelines that record environment, commands, and output in a structured format — for example, my DiTMoS reproduction report (`openflight/ditmos-reproduction/REPORT.md`) documents exact commands, environment versions, dataset hashes, and measured results.

**DecTrain — what interests me:**

Your paper addresses a core practical question: when is online training worth the computational cost? The method decides dynamically whether to perform a gradient step based on whether it improves the current depth estimator. I am interested in the evaluation framework — how the decision criterion is validated against held-out data, and how the reported results generalize across datasets (ScanNet, SUN3D, KITTI-360).

While OpenFlight does not implement online depth training, my skills in experiment design, numerical parity testing, and reproducibility pipeline construction could be useful for evaluating or extending your published results.

**A concrete task I could carry out:**

I would like to offer a small, supervised computational contribution to your group's existing research. Specifically:

- Reproduce one configured training experiment from the repository, recording the exact command, environment, and evaluation metric (e.g., depth error on the test split)
- Implement a documented variation (e.g., a different decision threshold, a different held-out dataset) and compare the resulting metric against the baseline
- Write a short reproducibility report documenting the environment, commands, output, and any discrepancies — following the format of my previous reproduction reports

I have access to Python, PyTorch, NumPy, and the OpenFlight pipeline for experiment recording and verification. I am available 3–4 hours per week during the school year, remote.

I would be grateful if you could advise whether such a task would be useful, and I am happy to provide my CV and previous reproducibility reports for your review.

Thank you for your time.

Kind regards,

Shaurjesh Basu  
Year 11, Merchant Taylors' School Northwood  
GitHub: github.com/DaMaker1291/Openflight  
Email: shaurjesh.basu (school domain)

---

*Attached: CV (one page)*
*Evidence: OpenFlight at commit `972e23e`; experiment-record/reproduce pipeline; DiTMoS reproducibility experience*