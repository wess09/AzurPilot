# Deploy

This directory holds the AzurPilot installer.

Install AzurPilot by running `python -m deploy.installer` in AzurPilot root folder.

This entry point bootstraps the project-local `.venv` with `uv` and syncs
dependencies from `pyproject.toml` and `uv.lock` before continuing. It does not
install packages into the system Python environment.


# Launcher

Launcher `AzurPilot.exe` is a `.bat` file converted to `.exe` file by [Bat To Exe Converter](https://f2ko.de/programme/bat-to-exe-converter/).

If you have warnings from your anti-virus software, replace `AzurPilot.exe` with `deploy/launcher/Alas.bat`. They should do the same thing.

