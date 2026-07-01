# Model verification & validation tests

Run the full suite from the repo root:

```bash
python tests/run_model_tests.py
```

## Disclaimer

In addition to manual checks by the authors, an AI agent was used to develop the full test suite to verify and validate every part of the model (e.g., constraints are being enforced in the code properly, objective values are computed correctly, no erroneous behavior, etc.). The authors spot-checked parts of the test suite in detail but were unable to perform a thorough audit of the test suites in full.
