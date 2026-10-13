Contributing to KNEURA



Thank you for your interest in contributing to KNEURA!



KNEURA is a research prototype for AI-assisted knee MRI analysis. Contributions should preserve patient safety, data privacy, and the existing model integration contracts.



Getting Started



Prerequisites:



\* Python and the dependencies listed in backend/requirements.txt

\* Node.js 22.6 or later

\* Compatible PyTorch and torchvision versions

\* The required KNEE-AI 3.3 model weights for model-dependent workflows



Install the frontend dependencies:



npm ci



Install the backend dependencies:



python -m pip install -r backend/requirements.txt



Follow the main README for application setup and model validation.



Running Checks



Run the frontend build:



npm run build



Run lint:



npm run lint



Run the workflow tests:



npm test



Run backend tests:



npm run test:backend



Backend tests require the Python dependencies to be installed.



Contribution Guidelines



\* Keep pull requests focused and explain the problem being solved.

\* Add or update tests when changing application behavior.

\* Do not commit .env files, credentials, private patient data, local databases, model weights, or generated artifacts.

\* Use synthetic imaging data for software tests; never commit real patient MRI data.

\* Do not introduce unsupported clinical claims or present model probabilities as diagnoses.



AI and Clinical Safety



KNEURA is a research prototype, not a clinically validated diagnostic system.



The KNEE-AI 3.3 model integration is treated as a frozen contract. Do not change its model outputs, 12-class ordering, preprocessing, probability semantics, or clinical threshold assumptions without approval from the model owner.



Grad-CAM visualizations are explanations of model behavior, not confirmed pathology or precise lesion segmentation.



Radiologist review of findings and explicit final report approval must remain in place.



Pull Requests



Before opening a pull request:



1\. Run the relevant checks.

2\. Review the diff and ensure unrelated files are not included.

3\. Describe the change and list the checks performed.

4\. Open the pull request against the repository’s main branch.

5\. Respond to maintainer feedback and update the branch as requested.

