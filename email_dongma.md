Subject: DiTMoS inference result and small computational contribution

Dear Dr. Ma,

I am a Year 11 student at Merchant Taylors' School Northwood currently exploring research opportunities in embedded machine learning. I came across your DiTMoS paper *Delving into Diverse Tiny-Model Selection on Microcontrollers* (arXiv:2403.09035, PerMed'2024) and was impressed by your work on diverse tiny-model selection under microcontroller constraints.

**My DiTMoS inference result:**

I successfully reproduced the inference accuracy from your publicly released checkpoints (commit `ce195f9`). Using the authors' supplied classifiers and selector on the official UniMiB-SHAR test split, I measured **86.6% accuracy**, which is consistent with your paper's reported result of >86% for the default example.

I want to be clear: this is inference with your supplied checkpoints only. I have not attempted full training from scratch, which would require approximately 300+ seconds and significant compute resources. The reproduction report is available at `openflight/ditmos-reproduction/REPORT.md`, including environment (PyTorch 2.8.0, SciPy 1.13.1, scikit-learn 1.6.1), dataset SHA-256 hashes, and the exact commands used.

**A concrete task I could carry out:**

I would like to offer a small, supervised computational contribution to your group's existing research. Specifically:

- Help evaluate whether the diverse tiny-model selection approach generalizes to a new dataset or model architecture
- Extend the evaluation with an ablation study on the number of models in the selector
- Document the preprocessing randomization issue (your `UniMiB_preprocessing.py` uses a shuffled split without `random_state`) and prepare a cleaned reproduction guide

I have experience with experiment recording (`openflight experiment-record`), parity checking, and generating reproducible evidence packages. I am available 3–4 hours per week during the school year, remote.

I would be grateful if you could advise whether a school-student contribution on a focused sub-problem would be useful to your group, and I am happy to provide my CV and the DiTMoS reproduction report for your review.

Thank you for your time.

Kind regards,

Shaurjesh Basu  
Year 11, Merchant Taylors' School Northwood  
GitHub: github.com/DaMaker1291/Openflight  
Email: shaurjesh.basu (school domain)

---

*Attached: CV (one page)*
*Evidence: DiTMoS reproduction report at `openflight/ditmos-reproduction/REPORT.md`; OpenFlight at commit `972e23e`*