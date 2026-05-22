# Deploy

This directory holds the Alas installer.

Install Alas by running `python -m deploy.installer` in Alas root folder.

On Linux and macOS this entry point bootstraps a local `.venv` with `uv` and
syncs the platform requirements file before continuing. It does not install
packages into the system Python environment.



# Launcher

Launcher `Alas.exe` is a `.bat` file converted to `.exe` file by [Bat To Exe Converter](https://f2ko.de/programme/bat-to-exe-converter/).

If you have warnings from your anti-virus software, replace `alas.exe` with `deploy/launcher/Alas.bat`. They should do the same thing.
