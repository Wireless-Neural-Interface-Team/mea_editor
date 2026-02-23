# MEA-Editor
GUI to create and modify MEA compatible with probeinterface

# Quick installation using "uv"
1. "uv" installation
- On macOS and Linux. Open a terminal and enter _curl -LsSf https://astral.sh/uv/install.sh | sh_
- On Windows. Open an instance of the Powershell and enter _powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"_
2. Exit the session and log in again.
3. Download this file in your "Documents" folder : [requirements.txt ](https://github.com/Wireless-Neural-Interface-Team/MEA-Editor/blob/main/requirements.txt)
4. Open terminal or powershell and run: _uv venv si_env --python 3.12_
5. Activate your virtual environment by running:
- For Mac/Linux: source _si_env/bin/activate_ 
- For Windows: _si_env\Scripts\activate_
You should see (si_env) in your terminal.
6. Run _uv pip install -r requirements.txt_
7. Download the folder _MEA Editor Python Files_ and run _buile_exe.py_
It creates an .exe that is the MEA Editor software.
